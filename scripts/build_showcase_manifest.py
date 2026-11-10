#!/usr/bin/env python3
"""Build the public manifest from real rendered media and scored predictions."""
from __future__ import annotations

import argparse
import csv
import json
import math
import shutil
from pathlib import Path

import numpy as np


def write_json(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False))
    tmp.replace(path)


def metric_value(value):
    if isinstance(value, (float, int)):
        return value if math.isfinite(float(value)) else None
    return None


def num(value):
    return f"{value:.2f}" if isinstance(value, (float, int)) and math.isfinite(float(value)) else "N/A"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--site", type=Path)
    p.add_argument("--metrics", type=Path)
    args = p.parse_args()
    root = args.root.resolve()
    site = (args.site or root / "site").resolve()
    metrics_path = args.metrics or root / "reports/metrics.json"
    scored = json.loads(metrics_path.read_text())
    media = json.loads((site / "media_manifest.json").read_text())
    inputs = json.loads((root / "data/inputs_manifest.json").read_text())
    input_samples = inputs["samples"] if isinstance(inputs, dict) else inputs
    input_by_id = {s["id"]: s for s in input_samples}
    scores = {s["id"]: s for s in scored["samples"]}
    records = media["samples"]
    missing = [s["id"] for s in records if s["id"] not in scores]
    if missing:
        raise ValueError(f"Rendered samples have no scores: {missing}")
    report_dir = site / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(metrics_path, report_dir / "metrics.json")
    source_hggt = root / "outputs/hggt/provenance.json"
    if source_hggt.is_file():
        shutil.copyfile(source_hggt, report_dir / "hggt_provenance.json")
    source_hawor = root / "reports/data_inventory_hawor_provenance.json"
    if source_hawor.is_file():
        shutil.copyfile(source_hawor, report_dir / "hawor_provenance.json")
    summary_rows = []
    input_records = []
    for record in records:
        sid = record["id"]
        record["media"]["comparison"]["poster"] = f"media/{sid}/keyframe_000000.jpg"
        score = scores[sid]
        methods = score.get("methods", [])
        if {m.get("method") for m in methods} != {"HGGT", "HaWoR"}:
            raise ValueError(f"Missing model results for {sid}")
        record["metrics"] = []
        for method in methods:
            values = {key: metric_value(method.get(key)) for key in ["n", "n_absolute", "rr_mpjpe_mm", "pa_mpjpe_mm", "mpjpe_mm", "native_mpjpe_mm", "rr_acceleration_error_m_s2"]}
            coverage = metric_value(method.get("coverage"))
            values["coverage_percent"] = 100 * coverage if coverage is not None else None
            record["metrics"].append({"method": method["method"], "values": values})
            summary_rows.append({"sample": sid, "method": method["method"], **values,
                                 "annotation_eligible": method.get("annotation_eligible"),
                                 "prediction_available": method.get("prediction_available")})
        eligible = score.get("annotation_eligible")
        common = score.get("paired_hand_frames")
        record["metrics_note"] = f"共同有效手帧 {common} / 可评价标注手帧 {eligible}。根相对与对齐误差使用原生几何和统一关节标记；绝对误差中的 HGGT 使用标定平移适配。"
        record["links"].extend([
            {"label": "本序列完整评价 JSON", "href": f"reports/{sid}_metrics.json"},
            {"label": "原始帧与输入记录 CSV", "href": f"reports/{sid}_frames.csv"},
            {"label": "HGGT 预测 NPZ（原生与适配）", "href": f"downloads/predictions/{sid}_hggt.npz"},
            {"label": "HaWoR 预测 NPZ", "href": f"downloads/predictions/{sid}_hawor.npz"},
        ])
        write_json(report_dir / f"{sid}_metrics.json", {"protocol": scored.get("protocol", {}), "sample": score})
        inp = np.load(input_by_id[sid]["input_npz"], allow_pickle=False)
        fields = ["local_index", "source_frame_id", "timestamp_s", "left_detected", "right_detected", "left_input_valid", "right_input_valid", "fx", "fy", "cx", "cy"]
        with (report_dir / f"{sid}_frames.csv").open("w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            for i, (fid, timestamp) in enumerate(zip(inp["frame_ids"], inp["timestamps_s"])):
                K = inp["K"][i]
                writer.writerow({"local_index": i, "source_frame_id": int(fid), "timestamp_s": float(timestamp),
                                 "left_detected": bool(inp["detected"][i, 0]), "right_detected": bool(inp["detected"][i, 1]),
                                 "left_input_valid": bool(inp["valid"][i, 0]), "right_input_valid": bool(inp["valid"][i, 1]),
                                 "fx": float(K[0, 0]), "fy": float(K[1, 1]), "cx": float(K[0, 2]), "cy": float(K[1, 2])})
        input_records.append({"id": sid, "dataset": record["dataset"], "sequence": record["sequence"],
                              "camera": record["camera"], "frames": len(inp["frame_ids"]),
                              "side_order": ["left", "right"], "input_valid_hand_frames": int(inp["valid"].sum()),
                              "detected_hand_frames": int(inp["detected"].sum()),
                              "first_K": inp["K"][0].tolist(), "GT_used_for_RGB_hand_boxes": False})
    csv_fields = ["sample", "method", "n", "n_absolute", "coverage_percent", "rr_mpjpe_mm", "pa_mpjpe_mm", "mpjpe_mm", "native_mpjpe_mm", "rr_acceleration_error_m_s2", "annotation_eligible", "prediction_available"]
    with (report_dir / "summary.csv").open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=csv_fields)
        writer.writeheader()
        writer.writerows(summary_rows)
    write_json(report_dir / "inputs.json", {"samples": input_records})
    total_frames = sum(s["frame_count"] for s in records)
    total_common = sum(int(scores[s["id"]].get("paired_hand_frames", 0)) for s in records)
    total_eligible = sum(int(scores[s["id"]].get("annotation_eligible", 0)) for s in records)
    summary = [f"完成 {len(records)} 段、{total_frames} 帧视频。下面按原始 RGB、HGGT、HaWoR 的顺序同步回放，并保留关键帧和逐序列指标。"]
    aggregate = {x["method"]: x for x in scored.get("aggregate", [])}
    if "HGGT" in aggregate and "HaWoR" in aggregate:
        hg, hw = aggregate["HGGT"], aggregate["HaWoR"]
        if all(hg.get(key, -1) > hw.get(key, float("inf")) for key in ["rr_mpjpe_mm", "pa_mpjpe_mm", "rr_acceleration_error_m_s2"]):
            summary.insert(0, "这四例里，HaWoR 总体更准、时序更稳。")
        summary.append(f"在 {total_common} 个共同有效手帧上，根相对关节误差为 HGGT {num(hg.get('rr_mpjpe_mm'))} mm、HaWoR {num(hw.get('rr_mpjpe_mm'))} mm；对齐后误差为 {num(hg.get('pa_mpjpe_mm'))} / {num(hw.get('pa_mpjpe_mm'))} mm。")
        summary.append(f"HGGT 原生绝对关节误差为 {num(hg.get('native_mpjpe_mm'))} mm，仅平移适配后为 {num(hg.get('mpjpe_mm'))} mm；HaWoR 标定重跑为 {num(hw.get('mpjpe_mm'))} mm。两种 HGGT 输出在下表分列，主视频显示适配后的结果。")
        summary.append(f"去腕后的加速度误差为 HGGT {num(hg.get('rr_acceleration_error_m_s2'))}、HaWoR {num(hw.get('rr_acceleration_error_m_s2'))} m/s²；数值越小，重建的时序变化越接近真值。")
    summary.append(f"可评价标注共 {total_eligible} 个手帧；画面中的缺手与 HaWoR 时序补全均保留，覆盖率单独列出。")
    downloads = [
        {"label": "完整评价 JSON", "href": "reports/metrics.json"},
        {"label": "指标汇总 CSV", "href": "reports/summary.csv"},
        {"label": "比较方法与显示口径", "href": "METHOD.md"},
        {"label": "输入身份与标定", "href": "reports/inputs.json"},
        {"label": "权重来源与身份", "href": "downloads/checkpoint_provenance.json"},
        {"label": "几何变换核对", "href": "downloads/geometry_check.json"},
    ]
    if (report_dir / "hggt_provenance.json").is_file():
        downloads.append({"label": "HGGT 运行配置", "href": "reports/hggt_provenance.json"})
    if (report_dir / "hawor_provenance.json").is_file():
        downloads.append({"label": "HaWoR 来源与配置", "href": "reports/hawor_provenance.json"})
    if (site / "DATA_AND_EVALUATION.md").is_file():
        downloads.append({"label": "数据与评价细节", "href": "DATA_AND_EVALUATION.md"})
    manifest = {
        "schema_version": 1, "title": "HGGT × HaWoR · 单视角复现", "updated_at": "2026-11-10",
        "subtitle": "DexYCB 与 HOT3D-Aria：相同单相机视频下的手部重建比较。",
        "summary": summary,
        "protocol": [
            {"label": "输入", "value": "单相机 RGB；完全相同的图像、帧顺序和预测手框。"},
            {"label": "HGGT", "value": "每帧、每只手 1 个视图；官方权重；无额外时序平滑。"},
            {"label": "HaWoR", "value": "保留序列模型和时序补全；用同一相机标定重新推理。"},
            {"label": "评价", "value": "共同有效手帧、统一关节标记；GT 仅用于评分。"},
        ],
        "scope_notes": [
            "主视频使用 HGGT 的标定平移适配：保留原生手形与姿态，只用模型自己的二维投影和相机内参拟合平移。原生投影另行提供。",
            "HaWoR 使用同一标定的中位数标量焦距和主点；渲染保留各方法实际使用的内参。样例结果用于检查复现效果，完整实验口径见方法说明。",
            "网格覆盖图只处理手的自遮挡，未模拟物体或场景的遮挡；位于杯子后方的手面片也可能叠加在 RGB 上。",
        ],
        "metric_definitions": [
            {"key": "n", "label": "共同手帧", "unit": "", "decimals": 0, "description": "同一时刻的一只手计一个手帧；几何比较采用双方共同有效的手帧集合。"},
            {"key": "coverage_percent", "label": "覆盖率", "unit": "%", "decimals": 1, "description": "有有效预测的手帧占全部可评价标注手帧的比例；缺失预测单独计入覆盖率。"},
            {"key": "rr_mpjpe_mm", "label": "根相对误差", "unit": "mm", "description": "移除腕部平移后的平均关节误差，保留姿态、方向和尺度差异；使用原生几何。越低越好。"},
            {"key": "pa_mpjpe_mm", "label": "对齐后误差", "unit": "mm", "description": "每个手帧经相似变换对齐后计算的关节误差，进一步消除整体旋转和尺度差异。越低越好。"},
            {"key": "native_mpjpe_mm", "label": "原生绝对误差", "unit": "mm", "description": "原生几何转换回原相机后的绝对关节误差，保留模型自身预测的距离与尺度；HGGT 未使用平移适配。越低越好。"},
            {"key": "mpjpe_mm", "label": "主图绝对误差", "unit": "mm", "description": "主视频显示的相机空间绝对关节误差：HGGT 使用仅平移的标定适配，HaWoR 使用标定相机原生输出。越低越好。"},
            {"key": "rr_acceleration_error_m_s2", "label": "加速度误差", "unit": "m/s²", "description": "去腕后的关节加速度与真值之差，按真实时间戳计算，仅统计双方连续三帧有效的手；越低越好。"},
        ],
        "metrics_note": "误差越小越好。根相对与对齐后误差直接衡量原生手形；HGGT 的原生绝对误差与仅平移适配后的主图误差分列。HaWoR 两列均为标定重跑的原生输出。覆盖率的分母为全部可评价标注手帧；加速度误差单位为 m/s²。",
        "downloads": downloads,
        "sources": [
            {"label": "HGGT · 官方代码", "url": "https://github.com/lym29/HGGT", "note": "单视图推理通过官方多视图接口的 N=1 设置执行。"},
            {"label": "HGGT · 官方权重", "url": "https://huggingface.co/catmint123/HGGT"},
            {"label": "HaWoR · 官方代码", "url": "https://github.com/ThunderVVV/HaWoR"},
            {"label": "HOT3D · 数据与工具", "url": "https://github.com/facebookresearch/hot3d"},
            {"label": "DexYCB · 数据集", "url": "https://dex-ycb.github.io/"},
            {"label": "此前的 EgoHSI3R 复现页", "url": "https://egohsi3r-experiments-20261104.yichengdraw.chatgpt.site/", "note": "本页沿用其逐序列视频与关键帧布局。"},
        ],
        "samples": records,
    }
    write_json(site / "manifest.json", manifest)
    print(json.dumps({"event": "showcase_manifest_complete", "samples": len(records), "frames": total_frames,
                      "paired_hand_frames": total_common, "site": str(site)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
