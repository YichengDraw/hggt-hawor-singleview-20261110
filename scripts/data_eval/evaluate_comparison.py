#!/usr/bin/env python3
"""Evaluate same-frame, same-hand HGGT and HaWoR against held-out annotations.

This script is the only consumer of evaluation_gt.npz. Inference scripts use
input.npz only. Every metric keeps its exact hand-frame denominator.
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

import numpy as np

TIP_SLOTS = [4, 8, 12, 16, 20]
BASE_SLOTS = [i for i in range(21) if i not in TIP_SLOTS]
TIP_IDS = {"DexYCB": [745, 317, 444, 556, 673],
           "HOT3D-Aria": [744, 320, 443, 554, 671]}


def harmonize(joints, vertices, dataset):
    """Keep MANO FK joints; replace only tips with annotation vertex markers."""
    result = np.array(joints, dtype=np.float64, copy=True)
    result[:, :, TIP_SLOTS] = vertices[:, :, TIP_IDS[dataset]]
    return result


def procrustes(predicted, target):
    """Fit scale, proper rotation and translation for row-vector landmarks."""
    xc = predicted - predicted.mean(axis=0, keepdims=True)
    yc = target - target.mean(axis=0, keepdims=True)
    u, singular, vt = np.linalg.svd(xc.T @ yc)
    signs = np.ones(3)
    signs[-1] = np.linalg.det(u @ vt)
    rotation = (u * signs) @ vt
    scale = float(np.dot(singular, signs) / np.sum(xc * xc))
    fitted = scale * xc @ rotation + target.mean(axis=0, keepdims=True)
    return fitted, scale


def project(points, intrinsics):
    camera = np.einsum("tij,thkj->thki", intrinsics, points)
    return camera[..., :2] / camera[..., 2:3]


def finite_mask(joints):
    return np.isfinite(joints).all(axis=(-1, -2))


def metric_arrays(predicted, ground_truth, timestamps):
    relative = predicted - predicted[:, :, :1]
    relative_gt = ground_truth - ground_truth[:, :, :1]
    errors = {"rr_mpjpe_mm": np.linalg.norm(relative - relative_gt, axis=-1).mean(-1) * 1000,
              "mpjpe_mm": np.linalg.norm(predicted - ground_truth, axis=-1).mean(-1) * 1000,
              "wrist_error_mm": np.linalg.norm(predicted[:, :, 0] - ground_truth[:, :, 0], axis=-1) * 1000,
              "base16_rr_mpjpe_mm": np.linalg.norm(relative[:, :, BASE_SLOTS] - relative_gt[:, :, BASE_SLOTS], axis=-1).mean(-1) * 1000}
    errors["pa_mpjpe_mm"] = np.full(predicted.shape[:2], np.nan)
    errors["pa_scale"] = np.full(predicted.shape[:2], np.nan)
    for t, h in np.argwhere(finite_mask(predicted) & finite_mask(ground_truth)):
        fitted, scale = procrustes(predicted[t, h], ground_truth[t, h])
        errors["pa_mpjpe_mm"][t, h] = np.linalg.norm(fitted - ground_truth[t, h], axis=-1).mean() * 1000
        errors["pa_scale"][t, h] = scale
    dt = np.diff(timestamps)
    v = np.diff(relative, axis=0) / dt[:, None, None, None]
    vg = np.diff(relative_gt, axis=0) / dt[:, None, None, None]
    acc = 2 * np.diff(v, axis=0) / (dt[:-1] + dt[1:])[:, None, None, None]
    acc_gt = 2 * np.diff(vg, axis=0) / (dt[:-1] + dt[1:])[:, None, None, None]
    errors["rr_acceleration_error_m_s2"] = np.full(predicted.shape[:2], np.nan)
    errors["rr_acceleration_error_m_s2"][1:-1] = np.linalg.norm(acc - acc_gt, axis=-1).mean(-1)
    return errors


def average(array, mask):
    use = mask & np.isfinite(array)
    return float(np.mean(array[use])) if use.any() else None


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--hggt-name", default="hggt")
    p.add_argument("--baseline-only", action="store_true")
    args = p.parse_args()
    root = args.root
    # A nontrivial rigid+scale transform tests SVD rotation direction.
    test = np.arange(63, dtype=np.float64).reshape(21, 3)
    test[:, 1] = np.sin(test[:, 1]); test[:, 2] = np.cos(test[:, 2])
    rotation = np.array([[0., -1., 0.], [1., 0., 0.], [0., 0., 1.]])
    transformed = 1.7 * test @ rotation + np.array([2., 3., 4.])
    assert np.max(np.abs(procrustes(test, transformed)[0] - transformed)) < 1e-9
    inputs = json.loads((root / "data/inputs_manifest.json").read_text())
    sample_results, per_frame, aggregate = [], [], {}
    reports = root / "reports"
    reports.mkdir(exist_ok=True)
    for sample in inputs["samples"]:
        sid = sample["id"]
        inp = np.load(sample["input_npz"], allow_pickle=False)
        gt = np.load(root / "data" / sid / "evaluation_gt.npz", allow_pickle=False)
        truth = gt["joints_camera"].astype(np.float64)
        times = inp["timestamps_s"].astype(np.float64)
        gt_mask = gt["valid"].astype(bool) & finite_mask(truth)
        detector = inp["valid"].astype(bool)
        hw = np.load(root / "outputs/hawor" / sid / "predictions.npz", allow_pickle=False)
        hw_j = harmonize(hw["joints_cam"], hw["verts_cam"], sample["dataset"])
        method_data = {"HaWoR": {"joints": hw_j, "native_joints": hw["joints_cam"],
                                "absolute_joints": hw_j, "valid": hw["valid"].astype(bool),
                                "absolute_valid": hw["valid"].astype(bool),
                                "K_used": hw["K_used"]}}
        if not args.baseline_only:
            hg = np.load(root / "outputs" / args.hggt_name / sid / "predictions.npz", allow_pickle=False)
            assert np.array_equal(hg["frame_ids"], inp["frame_ids"]), sid
            hj = harmonize(hg["joints_cam_native"], hg["verts_cam_native"], sample["dataset"])
            hj_cal = harmonize(hg["joints_cam"], hg["verts_cam"], sample["dataset"])
            method_data = {"HGGT": {"joints": hj, "native_joints": hg["joints_cam_native"],
                                    "absolute_joints": hj_cal, "valid": hg["valid"].astype(bool),
                                    "absolute_valid": hg["valid"].astype(bool) & hg["adapter_valid"].astype(bool),
                                    "K_used": inp["K"]}, **method_data}
        paired = gt_mask & detector
        for data in method_data.values():
            paired &= data["valid"] & finite_mask(data["joints"])
        paired_abs = paired.copy()
        for data in method_data.values():
            paired_abs &= data["absolute_valid"] & finite_mask(data["absolute_joints"])
        triplets = np.zeros_like(paired)
        triplets[1:-1] = paired[:-2] & paired[1:-1] & paired[2:]
        rows = []
        arrays = {"paired": paired, "paired_absolute": paired_abs, "gt_valid": gt_mask,
                  "detector_valid": detector, "timestamps_s": times, "frame_ids": inp["frame_ids"]}
        for method, data in method_data.items():
            e = metric_arrays(data["joints"], truth, times)
            e_native = metric_arrays(data["native_joints"].astype(np.float64), truth, times)
            e_abs = metric_arrays(data["absolute_joints"], truth, times)
            coverage_mask = gt_mask & data["valid"] & finite_mask(data["joints"])
            # Metric denominators below are hand-frame pairs, not image frames.
            row = {"method": method, "n": int(paired.sum()), "n_absolute": int(paired_abs.sum()),
                   "n_acceleration_triplets": int(triplets.sum()), "annotation_eligible": int(gt_mask.sum()),
                   "prediction_available": int(coverage_mask.sum()), "coverage": float(coverage_mask.sum()/gt_mask.sum()),
                   "rr_mpjpe_mm": average(e["rr_mpjpe_mm"], paired),
                   "pa_mpjpe_mm": average(e["pa_mpjpe_mm"], paired),
                   "base16_rr_mpjpe_mm": average(e["base16_rr_mpjpe_mm"], paired),
                   "mpjpe_mm": average(e_abs["mpjpe_mm"], paired_abs),
                   "wrist_error_mm": average(e_abs["wrist_error_mm"], paired_abs),
                   "native_mpjpe_mm": average(e["mpjpe_mm"], paired),
                   "native_definition_rr_mpjpe_mm": average(e_native["rr_mpjpe_mm"], paired),
                   "native_definition_pa_mpjpe_mm": average(e_native["pa_mpjpe_mm"], paired),
                   "rr_acceleration_error_m_s2": average(e["rr_acceleration_error_m_s2"], triplets),
                   "pa_scale_median": float(np.median(e["pa_scale"][paired])),
                   "absolute_output": "calibration-only rigid translation adapter" if method == "HGGT" else "calibrated camera-mode output"}
            row["per_hand"] = {}
            for h, side in enumerate(["left", "right"]):
                side_mask = paired.copy(); side_mask[:, 1-h] = False
                row["per_hand"][side] = {"n": int(side_mask.sum()), "rr_mpjpe_mm": average(e["rr_mpjpe_mm"], side_mask),
                                        "pa_mpjpe_mm": average(e["pa_mpjpe_mm"], side_mask)}
            rows.append(row)
            key = method.lower()
            for field, array in e.items():
                arrays[key+"_"+field] = array
            arrays[key+"_adapted_mpjpe_mm"] = e_abs["mpjpe_mm"]
            ag = aggregate.setdefault(method, {"eligible": 0, "available": 0, "values": {}})
            ag["eligible"] += int(gt_mask.sum()); ag["available"] += int(coverage_mask.sum())
            for field, array, mask in [("rr_mpjpe_mm", e["rr_mpjpe_mm"], paired),
                                       ("pa_mpjpe_mm", e["pa_mpjpe_mm"], paired),
                                       ("mpjpe_mm", e_abs["mpjpe_mm"], paired_abs),
                                       ("native_mpjpe_mm", e["mpjpe_mm"], paired),
                                       ("rr_acceleration_error_m_s2", e["rr_acceleration_error_m_s2"], triplets)]:
                ag["values"].setdefault(field, []).extend(array[mask & np.isfinite(array)].tolist())
            for t, h in np.argwhere(paired):
                per_frame.append(dict(sample=sid,method=method,frame_id=int(inp["frame_ids"][t]),side=["left","right"][h],
                                      timestamp_s=float(times[t]),rr_mpjpe_mm=float(e["rr_mpjpe_mm"][t,h]),
                                      pa_mpjpe_mm=float(e["pa_mpjpe_mm"][t,h]),
                                      mpjpe_mm=float(e_abs["mpjpe_mm"][t,h]) if paired_abs[t,h] else ""))
        np.savez_compressed(reports / (sid + "_metric_arrays.npz"), **arrays)
        sample_results.append({"id": sid, "dataset": sample["dataset"], "frames": sample["frame_count"],
                               "annotation_eligible": int(gt_mask.sum()), "detected_hand_frames": int((detector & gt_mask).sum()),
                               "paired_hand_frames": int(paired.sum()), "methods": rows})
    aggregate_rows = []
    for method, ag in aggregate.items():
        ar = {"method": method, "annotation_eligible": ag["eligible"], "prediction_available": ag["available"],
              "coverage": ag["available"]/ag["eligible"], "n": len(ag["values"]["rr_mpjpe_mm"])}
        ar.update({field: float(np.mean(values)) if values else None for field,values in ag["values"].items()})
        aggregate_rows.append(ar)
    report = {"schema": "hggt-hawor-metrics-v1", "baseline_only": args.baseline_only,
              "protocol": {"comparison": "same RGB camera, cached image pixels, detector tracks and calibration",
                           "n_unit": "hand-frame pairs", "coverage_unit": "fraction 0..1 of all annotated hands",
                           "paired_mask": "GT valid AND common detector available AND both methods finite",
                           "primary": "wrist-relative and per-hand-frame similarity-aligned MPJPE in mm",
                           "joint_definition": "16 native MANO FK joints retained; each dataset's 5 GT fingertip vertex markers substituted for both methods",
                           "tip_markers": TIP_IDS,
                           "absolute": "HGGT uses a rigid translation fit to its own predicted 2D points and K; HaWoR uses calibrated scalar-focal/principal-point output",
                           "calibration": "HGGT uses per-frame full K; HaWoR API takes scalar focal=(fx+fy)/2 and median principal point per clip",
                           "world_trajectory": "not evaluated; camera-space hand reconstruction only",
                           "acceleration": "root-relative joint acceleration error in m/s^2, actual timestamps, only triplets valid for both methods",
                           "gt_usage": "scoring only; no GT poses, camera trajectory, boxes or depth enter inference",
                           "scope": "four development examples; no claim of an official benchmark or training-disjoint test"},
              "samples": sample_results, "aggregate": aggregate_rows}
    filename = "baseline_metrics.json" if args.baseline_only else "metrics.json"
    (reports / filename).write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    csvname = "baseline_per_frame_metrics.csv" if args.baseline_only else "per_frame_metrics.csv"
    if per_frame:
        with (reports / csvname).open("w",newline="") as f:
            writer=csv.DictWriter(f,fieldnames=list(per_frame[0]));writer.writeheader();writer.writerows(per_frame)
    print(json.dumps({"output":str(reports/filename),"aggregate":aggregate_rows,"samples":[{"id":s["id"],"methods":s["methods"]} for s in sample_results]},indent=2))


if __name__ == "__main__":
    main()
