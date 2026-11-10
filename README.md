# HGGT × HaWoR 单视角复现

[打开同步视频与指标展示](https://yichengdraw.github.io/hggt-hawor-singleview-20261110/)

2026-11-10，在 NVIDIA L40S 上实际运行官方 HGGT 单视图推理，并以共同标定重新运行 HaWoR。四条序列为 DexYCB 箱子、香蕉及 HOT3D-Aria 001976、003209，共446幅RGB图像、715个共同有效手帧。

| 指标（越低越好） | HGGT | HaWoR |
|---|---:|---:|
| 去腕 MPJPE | 19.048 mm | 15.075 mm |
| PA-MPJPE | 8.786 mm | 6.655 mm |
| 原生相机空间 MPJPE | 131.299 mm | 27.266 mm |
| 统一标定主图 MPJPE | 29.746 mm | 27.266 mm |
| 去腕加速度误差 | 8.275 m/s² | 1.763 m/s² |

HGGT主图额外使用**已知相机内参和模型自身二维投影的整体平移适配**，不读取GT、不改变形状或姿态。原生输出全部保留。主去腕和PA指标采用原生几何；绝对误差的两种口径分列显示。时间指标使用701个共同有效连续三帧组。

这四例里HaWoR总体更准确、时序更平稳；香蕉样例的去腕误差由HGGT取得更低值。此处为四条开发例子的实测结果，作者训练数据重叠未知。

## 文件

- [PROTOCOL.md](PROTOCOL.md)：完整输入、裁剪、坐标、关节定义与评价协议。
- [docs/downloads/metrics.json](docs/downloads/metrics.json)：完整分例、总体指标和评价分母。
- [docs/downloads/per_frame_metrics.csv](docs/downloads/per_frame_metrics.csv)：逐手、逐帧指标。
- [docs/downloads/predictions/](docs/downloads/predictions/)：两方法的统一相机空间NPZ，HGGT另保留原生参数及适配前几何。
- `scripts/`：实际使用的推理、几何适配、评价与可视化脚本。
- `docs/`：GitHub Pages静态展示，无前端外部依赖。

## 运行接口

输入清单含每条序列的 `id`、`input_npz`、`rgb_frames`；`input.npz` 使用 `bbox[T,2,4]`、`valid[T,2]`、`detected[T,2]`、`K[T,3,3]`、`frame_ids[T]`、`timestamps_s[T]`、`image_paths[T]`，手侧顺序为左、右。各模型读取相同RGB和检测框。

```bash
python scripts/run_hggt.py --root RUN_ROOT --mano MANO_MODEL_DIRECTORY
python scripts/data_eval/evaluate_comparison.py --root RUN_ROOT
python scripts/render_showcase.py --root RUN_ROOT
python scripts/build_showcase_manifest.py --root RUN_ROOT
```

HGGT源码置于 `RUN_ROOT/upstream`，权重置于 `RUN_ROOT/weights/pytorch_model.bin`。完整数据准备和HaWoR环境说明见 [scripts/data_eval/README.md](scripts/data_eval/README.md)。该文件记录本次运行资产位置；在其他机器上应改为自己的授权数据和模型路径。

官方代码：[HGGT](https://github.com/lym29/HGGT)、[HaWoR](https://github.com/ThunderVVV/HaWoR)。HGGT固定代码提交 `779929115643ebb88abd531c683af7e4ed892d99`，权重来源与SHA-256见 [checkpoint_provenance.json](docs/downloads/checkpoint_provenance.json)。本仓库提供实验适配代码和结果；模型权重、MANO授权资产及完整原始数据集保留其各自许可与下载渠道。
