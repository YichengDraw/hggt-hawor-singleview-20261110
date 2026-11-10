"""HGGT single-view image and camera geometry, with no 3D GT inputs.

The crop follows ``HGGT/eval/data/mv_image_dataset.py`` at commit
779929115643ebb88abd531c683af7e4ed892d99: rotate the camera toward the detected
hand, then crop around the principal point.  Left hands are reflected around
the *camera principal point* before this rotation, so the network sees a
right-hand image.

All 3D arrays use row vectors, metric units, and OpenCV camera axes.  All image
matrices act on homogeneous *column* pixel coordinates.  The primary geometry
uses HGGT's canonical first-camera convention (extrinsic = identity), matching
its evaluation path.  The demo's additional predicted extrinsic is supported
only through the explicit ``extrinsic`` argument to project_native_to_full.

Known intrinsics are calibration metadata; this module never consumes GT hand
poses, GT 2D joints, GT depths, or GT camera trajectories.  The optional
translation fit preserves pose, shape, and every pairwise 3D distance.  It is
an adapter, not part of native HGGT and not the official per-point intrinsic
correction (which can deform the predicted hand).
"""

from __future__ import annotations

import json
from typing import Any

import cv2
import numpy as np


def transform_pixels(points_xy: np.ndarray, homography: np.ndarray) -> np.ndarray:
    """Apply a pixel homography to (..., 2); invalid projective depths are NaN."""
    xy = np.asarray(points_xy, dtype=np.float64)
    homogeneous = np.concatenate((xy, np.ones(xy.shape[:-1] + (1,))), axis=-1)
    warped = homogeneous @ np.asarray(homography, dtype=np.float64).T
    z = warped[..., 2:3]
    with np.errstate(divide="ignore", invalid="ignore"):
        result = warped[..., :2] / z
    return np.where(np.abs(z) > 1e-12, result, np.nan)


def project_points(points_xyz: np.ndarray, intrinsic: np.ndarray) -> np.ndarray:
    """Project (..., 3) OpenCV camera points with a 3x3 intrinsic matrix.

    This does not silently drop points behind the camera.  Callers should use
    the returned depth diagnostics from rigid_translation_fit or explicitly
    check point Z when drawing a mesh.
    """
    xyz = np.asarray(points_xyz, dtype=np.float64)
    projected = xyz @ np.asarray(intrinsic, dtype=np.float64).T
    z = projected[..., 2:3]
    with np.errstate(divide="ignore", invalid="ignore"):
        result = projected[..., :2] / z
    return np.where(np.abs(z) > 1e-12, result, np.nan)


def _rotation_direction_to_z(direction: np.ndarray) -> np.ndarray:
    """Shortest proper rotation taking a forward-facing unit ray to +Z."""
    d = np.asarray(direction, dtype=np.float64)
    d = d / np.linalg.norm(d)
    target = np.array([0.0, 0.0, 1.0])
    v = np.cross(d, target)
    s = np.linalg.norm(v)
    c = float(d @ target)
    if s < 1e-12:
        if c < 0:
            raise ValueError("The crop-center ray points behind the camera")
        return np.eye(3)
    vx = np.array([[0.0, -v[2], v[1]],
                   [v[2], 0.0, -v[0]],
                   [-v[1], v[0], 0.0]])
    return np.eye(3) + vx + (vx @ vx) * ((1.0 - c) / (s * s))


def rectify_crop(
    image_rgb: np.ndarray,
    K_full: np.ndarray,
    bbox_xyxy: np.ndarray,
    *,
    is_right: bool = True,
    image_size: int = 518,
    bbox_scale: float = 1.2,
) -> dict[str, Any]:
    """Prepare one hand-centric rectified crop from one calibrated RGB frame.

    Args:
        image_rgb: HxWx3 RGB image. Usually uint8; no model normalization here.
        K_full: 3x3 pinhole calibration for *this exact processed RGB image*.
        bbox_xyxy: Detector box [x1,y1,x2,y2], optionally with trailing score.
        is_right: False reflects image and camera X for a left-hand sample.
        image_size: Output square resolution; official HGGT default is 518.
        bbox_scale: Explicit padding factor on max(box_width, box_height).
            Record this value in the run manifest; this is not inferred from GT.

    Returns a dict containing:
        image_rgb: image_size-square RGB crop (same dtype as input).
        K_full, K_crop: Original and rectified/cropped known calibration.
        H_full_to_crop, H_crop_to_full: Total 2D homography and inverse,
            including the optional reflection, virtual rotation, and crop.
        R_mirror_to_crop: Proper rotation from the mirrored camera to the crop.
        S_mirror: diag(-1,1,1) for left hands, identity for right hands.
        camera_to_crop: R_mirror_to_crop @ S_mirror; column-coordinate mapping
            original camera -> crop. Its transpose is crop_to_camera.
        crop_to_camera: Inverse 3D matrix. For row-vector predictions X, use
            ``X @ geometry['camera_to_crop']`` to recover original-camera XYZ.
        affine_pp_crop: Affine from the rotated full canvas to the crop.
        H_mirror: Original-image reflection homography (identity for right).
        bbox_center_original, bbox_center_mirrored, bbox_side, bbox_scale,
            image_size, is_right, flip_winding: Auditable crop metadata.

    The two-stage rotation/crop resampling matches the official evaluation
    procedure. For a left hand, a separate reflection precedes these stages.
    The 3D/pixel mappings remain exact; raster interpolation is approximate.
    """
    image = np.asarray(image_rgb)
    K = np.asarray(K_full, dtype=np.float64).copy()
    box = np.asarray(bbox_xyxy, dtype=np.float64).reshape(-1)[:4]
    if image.ndim != 3 or image.shape[2] != 3:
        raise ValueError("image_rgb must be HxWx3")
    if K.shape != (3, 3) or not np.isfinite(K).all():
        raise ValueError("K_full must be a finite 3x3 matrix")
    if box.shape != (4,) or not np.isfinite(box).all():
        raise ValueError("bbox_xyxy must contain finite x1,y1,x2,y2")
    width, height = box[2] - box[0], box[3] - box[1]
    if min(width, height) <= 0 or bbox_scale <= 0 or image_size <= 0:
        raise ValueError("Box dimensions, bbox_scale, and image_size must be positive")
    if not np.allclose(K[2], [0.0, 0.0, 1.0]) or min(K[0, 0], K[1, 1]) <= 0:
        raise ValueError("K_full must use positive-focal pinhole calibration")

    image_size = int(image_size)
    full_h, full_w = image.shape[:2]
    K_inv = np.linalg.inv(K)
    center = (box[:2] + box[2:]) / 2.0
    S = np.diag([-1.0, 1.0, 1.0]) if not is_right else np.eye(3)
    # For zero-skew K, H_mirror = [[-1,0,2cx],[0,1,0],[0,0,1]].
    H_mirror = K @ S @ K_inv
    mirror_center = transform_pixels(center[None], H_mirror)[0]
    corners = np.array([[box[0], box[1]], [box[2], box[1]],
                        [box[2], box[3]], [box[0], box[3]]])
    mirror_corners = transform_pixels(corners, H_mirror)
    side = float(np.ptp(mirror_corners, axis=0).max() * bbox_scale)
    direction = K_inv @ np.r_[mirror_center, 1.0]
    R = _rotation_direction_to_z(direction)

    principal = K[:2, 2]
    resize_scale = image_size / side
    A = np.array([[resize_scale, 0.0, image_size / 2.0 - resize_scale * principal[0]],
                  [0.0, resize_scale, image_size / 2.0 - resize_scale * principal[1]],
                  [0.0, 0.0, 1.0]])
    H_rotate = K @ R @ K_inv
    C = R @ S
    H_total = A @ H_rotate @ H_mirror

    mirrored = image
    if not is_right:
        mirrored = cv2.warpPerspective(
            image, H_mirror, (full_w, full_h), flags=cv2.INTER_LINEAR,
            borderMode=cv2.BORDER_CONSTANT,
        )
    rotated = cv2.warpPerspective(
        mirrored, H_rotate, (full_w, full_h), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    crop = cv2.warpAffine(
        rotated, A[:2], (image_size, image_size), flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
    )
    return {
        "image_rgb": crop,
        "K_full": K,
        "K_crop": A @ K,
        "H_full_to_crop": H_total,
        "H_crop_to_full": np.linalg.inv(H_total),
        "R_mirror_to_crop": R,
        "S_mirror": S,
        "camera_to_crop": C,
        "crop_to_camera": C.T,
        "affine_pp_crop": A,
        "H_mirror": H_mirror,
        "bbox_center_original": center,
        "bbox_center_mirrored": mirror_center,
        "bbox_side": side,
        "bbox_scale": float(bbox_scale),
        "image_size": image_size,
        "is_right": bool(is_right),
        "flip_winding": not bool(is_right),
    }


def crop_to_camera(points_xyz: np.ndarray, geometry: dict[str, Any]) -> np.ndarray:
    """Native canonical MANO XYZ -> original full-image camera XYZ.

    For left hands this includes the reflection back to a left-hand mesh.
    Reverse face winding as ``faces[:, [0,2,1]]`` when flip_winding is true.
    No predicted first-camera extrinsic or calibration deformation is applied.
    """
    return np.asarray(points_xyz, dtype=np.float64) @ geometry["camera_to_crop"]


def project_native_to_full(
    points_xyz: np.ndarray,
    K_pred: np.ndarray,
    geometry: dict[str, Any],
    *,
    extrinsic: np.ndarray | None = None,
) -> np.ndarray:
    """Project native HGGT geometry back to original-image pixel coordinates.

    Default: u_full ~ H_crop_to_full @ K_pred @ X, using canonical first-view
    identity as in HGGT evaluation. To reproduce the public demo's alternative
    overlay explicitly pass its predicted 3x4/4x4 extrinsic; then the points
    are transformed by pred_R,pred_t first. Never apply both conventions in one
    metric without clearly identifying the extra transformation.
    """
    xyz = np.asarray(points_xyz, dtype=np.float64)
    if extrinsic is not None:
        ext = np.asarray(extrinsic, dtype=np.float64)
        xyz = xyz @ ext[:3, :3].T + ext[:3, 3]
    return transform_pixels(project_points(xyz, K_pred), geometry["H_crop_to_full"])


def rigid_translation_fit(
    points_cam: np.ndarray,
    target_uv_full: np.ndarray,
    K_full: np.ndarray,
    weights: np.ndarray | None = None,
) -> dict[str, Any]:
    """Fit only camera-space translation to predicted full-image 2D joints.

    Use target_uv_full from project_native_to_full, NOT from GT annotations.
    For normalized target rays x,y and original XYZ, solve in least squares:
        tx - x*tz = x*Z - X
        ty - y*tz = y*Z - Y.
    This closed-form fit minimizes the linear ray-equation residual. It does
    not claim to minimize the nonlinear pixel reprojection error exactly.
    Consequently the actual pixel residual is always returned and must be
    reported. No scale, rotation, or joint articulation is optimized.

    Finite points with positive finite weights are used; fewer than two valid
    joints raises ValueError. A nonunique solution (rank<3) or any fitted joint
    behind the camera makes success false. High condition numbers and high
    pixel residuals are reported, not hidden or replaced by another fit method.

    Returns:
        translation: (3,) delta in original-camera metric units.
        points_camera: (N,3) translated points; apply the same delta to mesh.
        projected_uv: (N,2) projection using K_full after translation.
        target_uv: Original target pixels; valid_mask marks fitting joints.
        reprojection_error_px: (N,) Euclidean pixel residual (NaN if unused).
        reprojection_mean_px / reprojection_rms_px / reprojection_max_px:
            Unweighted diagnostics over fitting joints.
        rank, singular_values, condition, linear_residual_rms:
            Least-squares conditioning/fit diagnostics.
        n_valid, positive_depth_fraction, success: Explicit fit validity.
    """
    points = np.asarray(points_cam, dtype=np.float64)
    target = np.asarray(target_uv_full, dtype=np.float64)
    K = np.asarray(K_full, dtype=np.float64)
    if points.ndim != 2 or points.shape[1] != 3 or target.shape != (len(points), 2):
        raise ValueError("Expected points_cam (N,3) and target_uv_full (N,2)")
    if weights is None:
        point_weights = np.ones(len(points), dtype=np.float64)
    else:
        point_weights = np.asarray(weights, dtype=np.float64).reshape(-1)
        if point_weights.shape != (len(points),):
            raise ValueError("weights must have one value per point")
    valid = (np.isfinite(points).all(axis=1) & np.isfinite(target).all(axis=1)
             & np.isfinite(point_weights) & (point_weights > 0))
    n_valid = int(valid.sum())
    if n_valid < 2:
        raise ValueError("Translation fitting requires at least two finite weighted joints")
    points_valid = points[valid]
    target_h = np.c_[target[valid], np.ones(n_valid)]
    rays = target_h @ np.linalg.inv(K).T
    rays = rays / rays[:, 2:3]
    x, y = rays[:, 0], rays[:, 1]
    X, Y, Z = points_valid.T
    A = np.zeros((n_valid, 2, 3), dtype=np.float64)
    A[:, 0, 0] = 1.0
    A[:, 1, 1] = 1.0
    A[:, 0, 2] = -x
    A[:, 1, 2] = -y
    b = np.stack((x * Z - X, y * Z - Y), axis=1)
    sqrt_weight = np.sqrt(point_weights[valid])
    weighted_A = (A * sqrt_weight[:, None, None]).reshape(-1, 3)
    weighted_b = (b * sqrt_weight[:, None]).reshape(-1)
    translation, _, rank, singular_values = np.linalg.lstsq(weighted_A, weighted_b, rcond=None)
    translated = points + translation
    projected = project_points(translated, K)
    errors = np.full(len(points), np.nan, dtype=np.float64)
    errors[valid] = np.linalg.norm(projected[valid] - target[valid], axis=1)
    positive_depth_fraction = float(np.mean(translated[valid, 2] > 1e-9))
    condition = float(singular_values[0] / singular_values[-1]) if singular_values[-1] > 0 else float("inf")
    success = bool(rank == 3 and np.isfinite(translation).all()
                   and np.isfinite(errors[valid]).all() and positive_depth_fraction == 1.0)
    return {
        "translation": translation,
        "points_camera": translated,
        "projected_uv": projected,
        "target_uv": target.copy(),
        "valid_mask": valid,
        "reprojection_error_px": errors,
        "reprojection_mean_px": float(np.mean(errors[valid])),
        "reprojection_rms_px": float(np.sqrt(np.mean(errors[valid] ** 2))),
        "reprojection_max_px": float(np.max(errors[valid])),
        "rank": int(rank),
        "singular_values": singular_values,
        "condition": condition,
        "linear_residual_rms": float(np.sqrt(np.mean((weighted_A @ translation - weighted_b) ** 2))),
        "n_valid": n_valid,
        "positive_depth_fraction": positive_depth_fraction,
        "success": success,
    }


def _geometry_self_check() -> dict[str, Any]:
    """Small analytic checks for inverse homography, reflection, and LS sign."""
    image = np.zeros((480, 640, 3), dtype=np.uint8)
    K = np.array([[520.0, 0.0, 313.0], [0.0, 503.0, 239.0], [0.0, 0.0, 1.0]])
    bbox = np.array([375.0, 180.0, 495.0, 320.0])
    rng = np.random.default_rng(7)
    points = rng.normal(0.0, 0.025, (21, 3)) + np.array([0.10, 0.02, 0.6])
    uv = project_points(points, K)
    max_pixel_error = 0.0
    for is_right in (True, False):
        geom = rectify_crop(image, K, bbox, is_right=is_right)
        canonical = points @ geom["camera_to_crop"].T
        np.testing.assert_allclose(crop_to_camera(canonical, geom), points, atol=1e-12)
        uv_crop_h = transform_pixels(uv, geom["H_full_to_crop"])
        uv_crop_3d = project_points(canonical, geom["K_crop"])
        np.testing.assert_allclose(uv_crop_h, uv_crop_3d, atol=1e-9)
        uv_back = project_native_to_full(canonical, geom["K_crop"], geom)
        np.testing.assert_allclose(uv_back, uv, atol=1e-9)
        np.testing.assert_allclose(np.linalg.det(geom["camera_to_crop"]), 1.0 if is_right else -1.0, atol=1e-12)
        max_pixel_error = max(max_pixel_error, float(np.max(np.abs(uv_back - uv))))
    delta = np.array([-0.03, 0.015, 0.12])
    target = project_points(points + delta, K)
    fitted = rigid_translation_fit(points, target, K)
    np.testing.assert_allclose(fitted["translation"], delta, atol=1e-10)
    assert fitted["success"]
    return {"geometry_self_check": "passed", "right_and_left_inverse_max_error_px": max_pixel_error,
            "translation_max_error_m": float(np.max(np.abs(fitted["translation"] - delta))),
            "translation_reprojection_rms_px": fitted["reprojection_rms_px"]}


if __name__ == "__main__":
    print(json.dumps(_geometry_self_check(), indent=2))
