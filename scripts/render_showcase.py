#!/usr/bin/env python3
"""Render the actual HGGT/HaWoR camera meshes with a CPU z-buffer.

Reads shared input images and the two models' predictions; never opens GT.
The main comparison uses HGGT's explicit translation adapter. The native
projection is exported separately as a 2D diagnostic, not metric 3D geometry.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import time
from pathlib import Path

import cv2
import numpy as np

SIDE_COLORS = [(188, 66, 196), (222, 185, 22)]  # BGR: left magenta, right cyan
JOINT_EDGES = [(0, 1), (1, 2), (2, 3), (3, 4), (0, 5), (5, 6), (6, 7), (7, 8),
               (0, 9), (9, 10), (10, 11), (11, 12), (0, 13), (13, 14), (14, 15), (15, 16),
               (0, 17), (17, 18), (18, 19), (19, 20)]
TITLES = {
    "dexycb_box": ("箱子", "DexYCB", "20200928_143606"),
    "dexycb_banana": ("香蕉", "DexYCB", "20200928_145724"),
    "aria_1976": ("Aria · 双手工具操作", "HOT3D-Aria", "1976"),
    "aria_3209": ("Aria · 黑杯转动", "HOT3D-Aria", "3209"),
}


def json_write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    temp.replace(path)


def rasterize(vertices, faces, K, color, depth, paint):
    """Perspective-correct per-pixel triangle depth, including self occlusion."""
    vertices = np.asarray(vertices, np.float32)
    faces = np.asarray(faces, np.int32)
    if not np.isfinite(vertices).all():
        return 0
    h, w = depth.shape
    z = vertices[:, 2]
    proj = vertices @ np.asarray(K, np.float32).T
    uv = proj[:, :2] / np.maximum(proj[:, 2:3], 1e-6)
    tri = vertices[faces]
    normals = np.cross(tri[:, 1] - tri[:, 0], tri[:, 2] - tri[:, 0])
    normals /= np.maximum(np.linalg.norm(normals, axis=1, keepdims=True), 1e-9)
    light = np.array([0.18, -0.30, -1.0], np.float32)
    light /= np.linalg.norm(light)
    shade = .47 + .53 * np.abs(normals @ light)
    colors = np.clip(np.asarray(color, np.float32)[None, :] * shade[:, None], 0, 255).astype(np.uint8)
    drawn = 0
    for i, f in enumerate(faces):
        if np.min(z[f]) <= .005:
            continue
        p = uv[f]
        left = max(0, int(math.floor(float(np.min(p[:, 0])))))
        right = min(w - 1, int(math.ceil(float(np.max(p[:, 0])))))
        top = max(0, int(math.floor(float(np.min(p[:, 1])))))
        bottom = min(h - 1, int(math.ceil(float(np.max(p[:, 1])))))
        if left > right or top > bottom:
            continue
        x0, y0 = p[0]
        x1, y1 = p[1]
        x2, y2 = p[2]
        denom = (y1 - y2) * (x0 - x2) + (x2 - x1) * (y0 - y2)
        if abs(float(denom)) < 1e-7:
            continue
        xs = np.arange(left, right + 1, dtype=np.float32)[None, :] + .5
        ys = np.arange(top, bottom + 1, dtype=np.float32)[:, None] + .5
        a = ((y1 - y2) * (xs - x2) + (x2 - x1) * (ys - y2)) / denom
        b = ((y2 - y0) * (xs - x2) + (x0 - x2) * (ys - y2)) / denom
        c = 1.0 - a - b
        inside = (a >= -1e-5) & (b >= -1e-5) & (c >= -1e-5)
        inv_z = a / z[f[0]] + b / z[f[1]] + c / z[f[2]]
        triangle_depth = 1.0 / np.maximum(inv_z, 1e-8)
        target = depth[top:bottom + 1, left:right + 1]
        update = inside & (triangle_depth < target)
        if not update.any():
            continue
        target[update] = triangle_depth[update]
        paint[top:bottom + 1, left:right + 1][update] = colors[i]
        drawn += int(update.sum())
    return drawn


def mesh_overlay(rgb, verts, valid, K, face_sets, alpha=.72):
    depth = np.full(rgb.shape[:2], np.inf, np.float32)
    paint = np.zeros_like(rgb)
    touched = []
    for hand in range(2):
        count = rasterize(verts[hand], face_sets[hand], K, SIDE_COLORS[hand], depth, paint) if valid[hand] else 0
        touched.append(count)
    mask = np.isfinite(depth)
    result = rgb.copy()
    result[mask] = np.clip((1 - alpha) * rgb[mask].astype(np.float32) + alpha * paint[mask], 0, 255).astype(np.uint8)
    return result, touched


def skeleton_overlay(rgb, joints, valid, scale):
    result = rgb.copy()
    for side in range(2):
        if not valid[side] or not np.isfinite(joints[side]).all():
            continue
        p = np.asarray(joints[side]) * scale
        p = np.clip(np.rint(p), -10000, 10000).astype(np.int32)
        color = SIDE_COLORS[side]
        for a, b in JOINT_EDGES:
            cv2.line(result, tuple(p[a]), tuple(p[b]), color, 2, cv2.LINE_AA)
        for xy in p:
            cv2.circle(result, tuple(xy), 3, color, -1, cv2.LINE_AA)
            cv2.circle(result, tuple(xy), 3, (245, 245, 245), 1, cv2.LINE_AA)
    return result


def text(image, value, xy, scale=.55, color=(63, 67, 57), thickness=1):
    cv2.putText(image, str(value), xy, cv2.FONT_HERSHEY_SIMPLEX, scale, color, thickness, cv2.LINE_AA)


def titled(rgb, heading, footer, hand_valid=None):
    h, w = rgb.shape[:2]
    result = np.full((h + 64, w, 3), (246, 246, 240), np.uint8)
    result[38:38 + h] = rgb
    text(result, heading, (10, 24), scale=.52, thickness=1)
    if hand_valid is not None:
        for side, label in [(0, "L"), (1, "R")]:
            color = SIDE_COLORS[side] if hand_valid[side] else (155, 155, 155)
            text(result, label, (w - 43 + 22 * side, 24), .47, color, 1)
    text(result, footer, (10, h + 55), scale=.39, color=(105, 109, 99))
    if result.shape[0] % 2:
        result = cv2.copyMakeBorder(result, 0, 1, 0, 0, cv2.BORDER_CONSTANT, value=(246, 246, 240))
    if result.shape[1] % 2:
        result = cv2.copyMakeBorder(result, 0, 0, 0, 1, cv2.BORDER_CONSTANT, value=(246, 246, 240))
    return result


class VideoWriter:
    def __init__(self, path, fps, size):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.log = open(self.path.with_suffix(".ffmpeg.log"), "w")
        self.proc = subprocess.Popen([
            "ffmpeg", "-hide_banner", "-loglevel", "warning", "-y", "-f", "rawvideo",
            "-pixel_format", "bgr24", "-video_size", f"{size[0]}x{size[1]}", "-framerate", str(fps),
            "-i", "pipe:0", "-an", "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(self.path)
        ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=self.log)

    def write(self, frame):
        self.proc.stdin.write(np.ascontiguousarray(frame).tobytes())

    def close(self):
        self.proc.stdin.close()
        code = self.proc.wait()
        self.log.close()
        if code:
            raise RuntimeError(f"ffmpeg exited {code}: {self.path}")


def faces_for(npz, base_faces=None):
    if "faces_left" in npz.files and "faces_right" in npz.files:
        return [np.asarray(npz["faces_left"], np.int32), np.asarray(npz["faces_right"], np.int32)]
    if "faces" in npz.files:
        faces = np.asarray(npz["faces"], np.int32)
        if faces.ndim == 3:
            return [faces[0], faces[1]]
    elif base_faces is not None:
        faces = np.asarray(base_faces, np.int32)
    else:
        raise ValueError("Mesh faces unavailable")
    return [faces[:, [0, 2, 1]], faces]


def validate_frames(inp, pred, method):
    if len(pred["frame_ids"]) != len(inp["frame_ids"]):
        raise ValueError(f"{method} frame count mismatch")
    if not np.array_equal(pred["frame_ids"], inp["frame_ids"]):
        raise ValueError(f"{method} frame identity mismatch")
    if not np.allclose(pred["timestamps_s"], inp["timestamps_s"], atol=1e-6):
        raise ValueError(f"{method} timestamp mismatch")
    if "side_order" in pred.files and list(pred["side_order"].astype(str)) != ["left", "right"]:
        raise ValueError(f"{method} side order mismatch")


def shape_still(path, hggt, hawor, hg_faces, hw_faces, hg_valid, hw_valid, frame_ids):
    common_valid = hg_valid & hw_valid
    candidates = np.flatnonzero(common_valid.any(axis=1))
    if not len(candidates):
        return None
    frame = int(candidates[np.argmin(np.abs(candidates - (len(frame_ids) - 1) / 2))])
    size = 480
    tiles = []
    for side in range(2):
        if not hg_valid[frame, side] and not hw_valid[frame, side]:
            continue
        geometries = []
        for pred, v_key, j_key in [(hggt, "verts_cam_native", "joints_cam_native"), (hawor, "verts_cam", "joints_cam")]:
            geometries.append(pred[v_key][frame, side] - pred[j_key][frame, side, :1])
        finite = [g for g in geometries if np.isfinite(g).all()]
        if not finite:
            continue
        union = np.concatenate(finite)
        center = (np.min(union[:, :2], axis=0) + np.max(union[:, :2], axis=0)) / 2
        # One scale for both models. No independent rotation/scale alignment.
        pixels_per_m = min(1950.0, (size - 70) / max(float(np.ptp(union[:, :2], axis=0).max()), .1))
        K = np.array([[pixels_per_m * 2, 0, size / 2 - center[0] * pixels_per_m],
                      [0, pixels_per_m * 2, size / 2 - center[1] * pixels_per_m], [0, 0, 1]], np.float32)
        row = []
        for method, g, face_sets, display_valid in zip(["HGGT NATIVE SHAPE", "HAWOR"], geometries, [hg_faces, hw_faces], [hg_valid, hw_valid]):
            rgb = np.full((size, size, 3), (246, 246, 240), np.uint8)
            if display_valid[frame, side] and np.isfinite(g).all():
                projected = g.copy()
                # Orthographic shape view with per-vertex true relative z preserved for occlusion.
                z = projected[:, 2] + 2
                projected[:, 0] *= z / 2
                projected[:, 1] *= z / 2
                projected[:, 2] = z
                depth = np.full((size, size), np.inf, np.float32)
                paint = np.zeros_like(rgb)
                rasterize(projected, face_sets[side], K, SIDE_COLORS[side], depth, paint)
                mask = np.isfinite(depth)
                rgb[mask] = paint[mask]
                wrist = np.array([size / 2 - center[0] * pixels_per_m, size / 2 - center[1] * pixels_per_m]).astype(int)
                cv2.drawMarker(rgb, tuple(wrist), (80, 80, 80), cv2.MARKER_CROSS, 13, 1, cv2.LINE_AA)
            else:
                text(rgb, "No valid hand", (150, 230), .6)
            bar_px = int(round(.05 * pixels_per_m))
            cv2.line(rgb, (25, size - 25), (25 + bar_px, size - 25), (85, 85, 85), 2)
            text(rgb, "50 mm", (25, size - 35), .45)
            footer = f"{'LEFT' if side == 0 else 'RIGHT'} | source {frame_ids[frame]} | wrist centered"
            row.append(titled(rgb, method, footer))
        tiles.append(np.concatenate(row, axis=1))
    if not tiles:
        return None
    image = np.concatenate(tiles, axis=0)
    cv2.imwrite(str(path), image, [cv2.IMWRITE_JPEG_QUALITY, 94])
    return {"frame_index": frame, "source_frame_id": int(frame_ids[frame]), "path": str(path),
            "description": "Wrist-centered geometry, same scale and camera axes; no rigid or scale alignment between methods."}


def render_sample(root, site, sample, args):
    sid = sample["id"]
    inp = np.load(sample["input_npz"], allow_pickle=False)
    hg_path = root / "outputs/hggt" / sid / "predictions.npz"
    hw_path = root / "outputs/hawor" / sid / "predictions.npz"
    hggt = np.load(hg_path, allow_pickle=False)
    hawor = np.load(hw_path, allow_pickle=False)
    validate_frames(inp, hggt, "HGGT")
    validate_frames(inp, hawor, "HaWoR")
    hg_faces, hw_faces = faces_for(hggt), faces_for(hawor, hggt["faces"])
    image_paths = inp["image_paths"].astype(str)
    frame_ids = inp["frame_ids"]
    timestamps = inp["timestamps_s"].astype(float)
    total = len(frame_ids)
    n = min(total, args.max_frames) if args.max_frames else total
    dt = float(np.median(np.diff(timestamps))) if total > 1 else 1 / 30
    fps = float(sample.get("fps", 1 / dt))
    if fps <= 0 or not np.isfinite(fps):
        raise ValueError(f"Invalid fps for {sid}: {fps}")
    out = site / "media" / sid
    out.mkdir(parents=True, exist_ok=True)
    keyframes = sorted(set([0, n // 2, n - 1]))
    input_valid = inp["valid"].astype(bool)
    detected = inp["detected"].astype(bool)
    side_has_track = input_valid.any(axis=0)
    hg_valid = hggt["valid"].astype(bool) & hggt["adapter_valid"].astype(bool) & input_valid
    hw_valid = hawor["valid"].astype(bool) & side_has_track[None, :]
    hw_infilled = hw_valid & ~detected
    k_hw = inp["K"].copy()
    if "K_used" in hawor.files:
        k_hw = hawor["K_used"]
        if k_hw.shape == (3, 3): k_hw = np.repeat(k_hw[None], total, axis=0)
    k_difference = float(np.max(np.abs(k_hw[:n] - inp["K"][:n])))
    start = time.time()
    writer = diagnostic = None
    pixel_counts = {"hggt": [], "hawor": []}
    try:
        for t in range(n):
            image = cv2.imread(image_paths[t])
            if image is None:
                raise ValueError(f"Unreadable image {image_paths[t]}")
            scale = min(1.0, args.max_dimension / max(image.shape[:2]))
            if scale != 1:
                image = cv2.resize(image, (int(round(image.shape[1] * scale)), int(round(image.shape[0] * scale))), interpolation=cv2.INTER_AREA)
            K = inp["K"][t].astype(float).copy()
            K[:2] *= scale
            K_hw = k_hw[t].astype(float).copy()
            K_hw[:2] *= scale
            hg_rgb, hg_px = mesh_overlay(image, hggt["verts_cam"][t], hg_valid[t], K, hg_faces)
            hw_rgb, hw_px = mesh_overlay(image, hawor["verts_cam"][t], hw_valid[t], K_hw, hw_faces)
            if hw_infilled[t].any():
                label = "TEMPORAL INFILL: " + ", ".join("L" if side == 0 else "R" for side in range(2) if hw_infilled[t, side])
                cv2.rectangle(hw_rgb, (5, 5), (205, 28), (245, 241, 226), -1)
                text(hw_rgb, label, (11, 21), .43, (75, 82, 59))
            pixel_counts["hggt"].append(hg_px)
            pixel_counts["hawor"].append(hw_px)
            footer = f"{t + 1:03d}/{n} | t={timestamps[t] - timestamps[0]:.3f}s | source {frame_ids[t]}"
            panels = [titled(image, "INPUT RGB", footer),
                      titled(hg_rgb, "HGGT: TRANSLATION ADAPTER", footer, hg_valid[t]),
                      titled(hw_rgb, "HAWOR: CALIBRATED CAMERA", footer, hw_valid[t])]
            combined = np.concatenate(panels, axis=1)
            native = skeleton_overlay(image, hggt["joints2d_native"][t], hggt["valid"][t], scale)
            native = titled(native, "HGGT: NATIVE 2D PROJECTION", footer, hggt["valid"][t])
            if writer is None:
                writer = VideoWriter(out / "combined.mp4", fps, (combined.shape[1], combined.shape[0]))
                diagnostic = VideoWriter(out / "hggt_native_projection.mp4", fps, (native.shape[1], native.shape[0]))
            writer.write(combined)
            diagnostic.write(native)
            if t in keyframes:
                cv2.imwrite(str(out / f"keyframe_{t:06d}.jpg"), combined, [cv2.IMWRITE_JPEG_QUALITY, 94])
                if t == n // 2:
                    cv2.imwrite(str(out / "native_projection_poster.jpg"), native, [cv2.IMWRITE_JPEG_QUALITY, 92])
            if t == 0 or (t + 1) % 30 == 0 or t + 1 == n:
                print(json.dumps({"event": "render_progress", "sample": sid, "frames": t + 1, "total": n,
                                  "seconds": round(time.time() - start, 2)}), flush=True)
    finally:
        if writer is not None: writer.close()
        if diagnostic is not None: diagnostic.close()
    shape = shape_still(out / "shape_comparison.jpg", hggt, hawor, hg_faces, hw_faces,
                        hg_valid, hw_valid, frame_ids)
    report = {
        "sample": sid, "rendered_frames": n, "fps": fps, "input_frame_ids": frame_ids[:n].tolist(),
        "input_source": sample["input_npz"], "hggt_source": str(hg_path), "hawor_source": str(hw_path),
        "renderer": "CPU triangle rasterizer with perspective-correct per-pixel z-buffer and flat normal lighting",
        "mesh_opacity": .72, "side_order": ["left", "right"],
        "colors": {"left": "magenta", "right": "cyan"},
        "gt_opened": False, "camera": "HGGT uses full dataset K; HaWoR uses its recorded median scalar-focal approximation of the same calibration", "frame_identity_verified": True,
        "hawor_max_K_difference_px": k_difference,
        "display_mask_rule": "HGGT valid & adapter_valid & input.valid; HaWoR valid & side_has_input_track",
        "side_has_input_track": side_has_track.tolist(),
        "hawor_temporal_infill_hand_frames": int(hw_infilled[:n].sum()),
        "hawor_temporal_infill_frame_indices": np.argwhere(hw_infilled[:n]).tolist(),
        "hggt_main_geometry": "verts_cam: translation-only adapter using model's own 2D projections and known K",
        "hggt_diagnostic": "joints2d_native: model's native projection in original input image",
        "visible_triangle_pixel_updates": pixel_counts, "shape_comparison": shape,
        "wall_seconds": time.time() - start,
        "model_inference_time_includes_rendering": False,
        "output_resolution": [int(combined.shape[1]), int(combined.shape[0])],
    }
    json_write(out / "render_provenance.json", report)
    title, dataset, sequence = TITLES.get(sid, (sid, sample.get("dataset", ""), sample.get("sequence", sid)))
    prefix = f"media/{sid}"
    item = {
        "id": sid, "title": title, "short_title": title, "dataset": dataset,
        "sequence": str(sample.get("sequence_id", sample.get("sequence", sequence))),
        "camera": str(sample.get("camera_id", sample.get("camera", ""))),
        "frame_count": n, "fps": fps, "source_frame_ids": frame_ids[:n].tolist(), "status": "complete",
        "description": "完全相同的 RGB 帧；逐帧对齐显示两种方法的相机空间网格。",
        "legend": "品红：左手；青色：右手。RGB 网格叠加仅处理手的自遮挡，未模拟物体和场景遮挡。",
        "media": {"comparison": {"src": f"{prefix}/combined.mp4", "poster": f"{prefix}/keyframe_{n // 2:06d}.jpg",
                                   "label": "原始 RGB / HGGT（标定平移适配） / HaWoR（标定相机）",
                                   "width": int(combined.shape[1]), "height": int(combined.shape[0])}},
        "keyframes": [{"src": f"{prefix}/keyframe_{t:06d}.jpg", "frame_index": t,
                       "label": f"回放第 {t + 1} 帧 · 源帧 {frame_ids[t]}"} for t in keyframes],
        "links": [{"label": "HGGT 原生 2D 投影视频", "href": f"{prefix}/hggt_native_projection.mp4"},
                  {"label": "渲染与帧对应记录", "href": f"{prefix}/render_provenance.json"}],
    }
    if shape:
        item["links"].append({"label": "腕中心、同尺度手形对比", "href": f"{prefix}/shape_comparison.jpg"})
    if hw_infilled[:n].any():
        item["notes"] = [f"HaWoR 含 {int(hw_infilled[:n].sum())} 个时序补全手帧，视频以 TEMPORAL INFILL 标注；共同有效手帧用于两方法的主指标比较。"]
    return item, report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--site", type=Path)
    parser.add_argument("--sample", nargs="*")
    parser.add_argument("--max-frames", type=int, default=0)
    parser.add_argument("--max-dimension", type=int, default=640)
    args = parser.parse_args()
    cv2.setNumThreads(2)
    root = args.root.resolve()
    site = (args.site or root / "site").resolve()
    manifest = json.loads((args.manifest or root / "data/inputs_manifest.json").read_text())
    samples = manifest["samples"] if isinstance(manifest, dict) else manifest
    if args.sample:
        samples = [s for s in samples if s["id"] in args.sample]
    entries, reports = [], []
    for sample in samples:
        item, report = render_sample(root, site, sample, args)
        entries.append(item)
        reports.append({k: v for k, v in report.items() if k != "visible_triangle_pixel_updates"})
    json_write(site / "media_manifest.json", {"samples": entries})
    json_write(root / "reports/render_summary.json", {"samples": reports})
    print(json.dumps({"event": "render_complete", "samples": len(entries), "site": str(site)}), flush=True)


if __name__ == "__main__":
    main()
