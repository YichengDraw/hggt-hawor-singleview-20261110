#!/usr/bin/env python3
"""Run official HGGT with one view per timestamp and shared RGB detections.

This adapter never opens ground-truth hand or object files. Camera calibration
is used only for the official evaluation crop and an explicit translation-only
output adapter. The unmodified model outputs are retained in every result.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import cv2
import numpy as np
import torch


def arguments():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--manifest", type=Path)
    p.add_argument("--mano", type=Path, required=True)
    p.add_argument("--device", default="cuda:0")
    p.add_argument("--sample", nargs="*")
    p.add_argument("--max-frames", type=int, default=0)
    p.add_argument("--output-name", default="hggt")
    p.add_argument("--batch-size", type=int, default=1)
    p.add_argument("--crop-scale", type=float, default=1.2)
    return p.parse_args()


def json_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False))
    temp.replace(path)


def main():
    args = arguments()
    root = args.root.resolve()
    os.environ.setdefault("PYOPENGL_PLATFORM", "egl")
    torch.set_num_threads(4)
    cv2.setNumThreads(2)
    sys.path.insert(0, str(root / "upstream"))
    sys.path.insert(0, str(root / "scripts"))
    from hggt.models.hggt import HGGT
    from hggt.utils.mano_utils import load_mano_model
    from hggt.utils.pose_enc import pose_encoding_to_extri_intri
    from hggt.training.train_utils.projection import compute_mano_output
    from hggt_geometry import rectify_crop, crop_to_camera, project_native_to_full, rigid_translation_fit

    manifest_path = args.manifest or root / "data/inputs_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    samples = manifest["samples"] if isinstance(manifest, dict) else manifest
    if args.sample:
        samples = [s for s in samples if s["id"] in args.sample]
    if not samples:
        raise ValueError("No selected samples")
    started = time.time()
    device = torch.device(args.device)
    checkpoint = root / "weights/pytorch_model.bin"
    ckpt = torch.load(checkpoint, map_location="cpu", weights_only=False)
    state = ckpt["model"] if isinstance(ckpt, dict) and "model" in ckpt else ckpt
    qk = any("cross_attn_trunk" in k and "q_norm" in k for k in state)
    model = HGGT(img_size=518, patch_size=14, embed_dim=1024,
                 enable_camera=True, enable_point=False, enable_depth=False,
                 enable_mano=True, mano_qk_norm=qk)
    incompat = model.load_state_dict(state, strict=False)
    if incompat.missing_keys:
        raise RuntimeError(f"Checkpoint missing model keys: {incompat.missing_keys}")
    if incompat.unexpected_keys:
        raise RuntimeError(f"Checkpoint has unexpected keys: {incompat.unexpected_keys}")
    del ckpt, state
    model.eval().to(device)
    mano, faces = load_mano_model(str(args.mano), device)
    dtype = torch.bfloat16 if device.type == "cuda" else torch.float32
    commit = subprocess.check_output(["git", "-C", str(root / "upstream"), "rev-parse", "HEAD"], text=True).strip()
    provenance = {
        "method": "HGGT", "source_commit": commit,
        "checkpoint_file": checkpoint.name, "checkpoint_bytes": checkpoint.stat().st_size,
        "checkpoint_missing_keys": incompat.missing_keys,
        "checkpoint_unexpected_keys": incompat.unexpected_keys,
        "model_parameter_count": sum(p.numel() for p in model.parameters()),
        "torch_version": torch.__version__, "device": str(device),
        "gpu": torch.cuda.get_device_name(device) if device.type == "cuda" else "CPU",
        "precision": str(dtype), "views_per_timestamp": 1,
        "batch_size": args.batch_size, "crop_size": 518, "crop_bbox_expansion": args.crop_scale,
        "temporal_smoothing": False, "gt_hand_access": False,
        "crop": "Official eval virtual camera rotation using input camera calibration; predicted HaWoR detector boxes",
        "canonical_camera": "Official eval: single-view first camera is identity; raw predicted extrinsics also retained",
        "left_hand": "Mirror full image about camera principal point, right MANO, inverse geometry and reflection",
        "camera_adapter": "Rigid translation fitted to the model's own full-frame projected 21 joints and known K; pose/shape unchanged",
        "rr_pa_basis": "native MANO geometry rotated/reflected back to original camera, without intrinsic point deformation",
        "side_order": ["left", "right"],
        "joint_order": "OpenPose21: wrist, thumb, index, middle, ring, pinky",
        "unit": "metre", "manifest": str(manifest_path),
        "model_load_seconds": time.time() - started,
    }
    print(json.dumps({"event": "model_loaded", **provenance}, ensure_ascii=False), flush=True)
    out_root = root / "outputs" / args.output_name
    out_root.mkdir(parents=True, exist_ok=True)
    json_write(out_root / "provenance.json", provenance)
    for sample in samples:
        sid = sample["id"]
        out = out_root / sid
        if (out / "complete.json").exists() and args.max_frames == 0:
            print(json.dumps({"event": "skip_complete", "sample": sid}), flush=True)
            continue
        out.mkdir(parents=True, exist_ok=True)
        inp = np.load(sample["input_npz"], allow_pickle=False)
        frame_count = len(inp["frame_ids"])
        n = min(frame_count, args.max_frames) if args.max_frames else frame_count
        validity = inp["valid"][:n].copy().astype(bool)
        bboxes = inp["bbox"][:n]
        K = inp["K"][:n]
        image_paths = inp["image_paths"] if "image_paths" in inp.files else sample.get("image_paths")
        if image_paths is None:
            frame_dir = Path(sample["rgb_frames"])
            image_paths = sorted(frame_dir.glob("*.jpg")) + sorted(frame_dir.glob("*.png"))
        if len(image_paths) < n:
            raise ValueError(f"{sid}: only {len(image_paths)} image paths for {n} frames")
        shapes = {
            "verts_native": (778, 3), "joints_native": (21, 3),
            "verts_cam_native": (778, 3), "joints_cam_native": (21, 3),
            "verts_cam": (778, 3), "joints_cam": (21, 3),
            "mano_pose": (48,), "betas": (10,), "transl": (3,),
            "pose_enc": (9,), "extrinsics": (3, 4), "intrinsics": (3, 3),
            "crop_homography": (3, 3), "rectify_rotation": (3, 3), "crop_intrinsics": (3, 3),
            "joints2d_native": (21, 2), "joints2d_calibrated": (21, 2),
            "translation_delta": (3,), "translation_reprojection_rmse_px": (),
            "model_seconds": (),
        }
        results = {k: np.full((n, 2) + shp, np.nan, np.float32) for k, shp in shapes.items()}
        inferred = np.zeros((n, 2), bool)
        adapter_valid = np.zeros((n, 2), bool)
        tasks = [(t, h) for t in range(n) for h in range(2) if validity[t, h]]
        progress = {"sample": sid, "total_frames": n, "total_hand_frames": len(tasks)}
        if device.type == "cuda":
            torch.cuda.reset_peak_memory_stats(device)
        seq_start = time.time()
        cached_t, cached_rgb = None, None
        for offset in range(0, len(tasks), args.batch_size):
            group = tasks[offset:offset + args.batch_size]
            images, geo = [], []
            for t, h in group:
                if t != cached_t:
                    bgr = cv2.imread(str(image_paths[t]))
                    if bgr is None:
                        raise ValueError(f"Cannot read {image_paths[t]}")
                    cached_rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                    cached_t = t
                g = rectify_crop(cached_rgb, K[t], bboxes[t, h], is_right=(h == 1),
                                 image_size=518, bbox_scale=args.crop_scale)
                images.append(torch.from_numpy(g["image_rgb"]).permute(2, 0, 1).float() / 255.0)
                geo.append(g)
            tensor = torch.stack(images).unsqueeze(1).to(device)
            if device.type == "cuda": torch.cuda.synchronize(device)
            tick = time.perf_counter()
            with torch.inference_mode(), torch.autocast(device_type=device.type, dtype=dtype, enabled=(device.type == "cuda")):
                preds = model(tensor)
            with torch.inference_mode():
                params = preds["mano_params"]
                v, j = compute_mano_output(mano, hand_pose=params["hand_pose"].float(),
                                          shape=params["betas"].float(), transl=params["transl"].float(), is_right=True)
                ex, ki = pose_encoding_to_extri_intri(preds["pose_enc"].float(), (518, 518))
            if device.type == "cuda": torch.cuda.synchronize(device)
            elapsed = (time.perf_counter() - tick) / len(group)
            verts, joints, extr, intr = [x.detach().cpu().numpy() for x in (v, j, ex[:, 0], ki[:, 0])]
            arrays = {"mano_pose": params["hand_pose"], "betas": params["betas"],
                      "transl": params["transl"], "pose_enc": preds["pose_enc"][:, 0]}
            arrays = {k: x.detach().float().cpu().numpy() for k, x in arrays.items()}
            for b, (t, h) in enumerate(group):
                g = geo[b]
                if not np.isfinite(verts[b]).all():
                    raise FloatingPointError(f"Non-finite HGGT geometry {sid}:{t}:{h}")
                vc = crop_to_camera(verts[b], g)
                jc = crop_to_camera(joints[b], g)
                uv = project_native_to_full(joints[b], intr[b], g)
                adapted = rigid_translation_fit(jc, uv, K[t])
                delta = adapted["translation"]
                values = {
                    "verts_native": verts[b], "joints_native": joints[b],
                    "verts_cam_native": vc, "joints_cam_native": jc,
                    "verts_cam": vc + delta, "joints_cam": jc + delta,
                    "extrinsics": extr[b], "intrinsics": intr[b],
                    "crop_homography": g["H_full_to_crop"], "rectify_rotation": g["R_mirror_to_crop"],
                    "crop_intrinsics": g["K_crop"], "joints2d_native": uv,
                    "joints2d_calibrated": adapted["projected_uv"],
                    "translation_delta": delta,
                    "translation_reprojection_rmse_px": adapted["reprojection_rms_px"],
                    "model_seconds": elapsed,
                }
                values.update({k: x[b] for k, x in arrays.items()})
                for k, value in values.items(): results[k][t, h] = value
                inferred[t, h] = True
                adapter_valid[t, h] = adapted["success"]
                if t in {0, n // 2, n - 1}:
                    cv2.imwrite(str(out / f"crop_{t:04d}_{'left' if h == 0 else 'right'}.jpg"),
                                cv2.cvtColor(g["image_rgb"], cv2.COLOR_RGB2BGR))
            if offset == 0 or offset + len(group) == len(tasks) or (offset + len(group)) % 25 == 0:
                print(json.dumps({"event": "progress", **progress,
                                  "completed_hand_frames": int(inferred.sum()),
                                  "elapsed_seconds": time.time() - seq_start,
                                  "last_hand_seconds": elapsed}), flush=True)
        pred_path = out / "predictions.npz"
        np.savez_compressed(pred_path, **results, valid=inferred, adapter_valid=adapter_valid,
                            input_valid=validity, detected=inp["detected"][:n],
                            bbox=bboxes, K=K, frame_ids=inp["frame_ids"][:n],
                            timestamps_s=inp["timestamps_s"][:n],
                            side_order=np.array(["left", "right"]), faces=faces,
                            source_image_paths=np.array([str(p) for p in image_paths[:n]]))
        peak = torch.cuda.max_memory_allocated(device) if device.type == "cuda" else 0
        complete = {**progress, "inferred_hand_frames": int(inferred.sum()),
                    "adapter_valid_hand_frames": int(adapter_valid.sum()),
                    "wall_seconds": time.time() - seq_start,
                    "model_seconds_sum": float(np.nansum(results["model_seconds"])),
                    "peak_cuda_memory_allocated_bytes": peak,
                    "prediction_file": str(pred_path),
                    "is_smoke_subset": bool(args.max_frames),
                    "source_commit": commit, "finished_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        json_write(out / "complete.json", complete)
        print(json.dumps({"event": "sample_complete", **complete}), flush=True)
    print(json.dumps({"event": "all_complete", "total_seconds": time.time() - started}), flush=True)


if __name__ == "__main__":
    main()
