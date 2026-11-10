# 数据与 HaWoR 比较口径

本轮在查看 HGGT 输出前固定 4 条序列，共 446 个视频帧、746 个有标注的手帧。两个模型共享同一路 RGB、同一批解码 PNG、HaWoR 检测器给出的手框及相机标定。HaWoR 使用原生 16 帧时序模型与 infiller，HGGT 每次只处理同一时刻的一只手。

| id | 数据 | 相机 | 视频帧 | 检测到的左/右手帧 |
|---|---|---|---:|---:|
| dexycb_box | 20200928-subject-07 / 20200928_143606 | 836212060125 | 74 | 0 / 74 |
| dexycb_banana | 20200928-subject-07 / 20200928_145724 | 836212060125 | 72 | 0 / 72 |
| aria_1976 | HOT3D-Aria clip-001976 | RGB 214-1 | 150 | 150 / 150 |
| aria_3209 | HOT3D-Aria clip-003209 | RGB 214-1 | 150 | 119 / 150 |

## 数据接口

`data/inputs_manifest.json` 包含每例的 RGB 视频、缓存图像目录和 `input.npz` 路径。NPZ 字段为 `bbox(T,2,4)`、`valid(T,2)`、`detected(T,2)`、`score(T,2)`、`K(T,3,3)`、`frame_ids`、`timestamps_s`、`image_paths`、`image_size`，左右顺序固定 `left,right`。手框保存原始 xyxy，模型适配器使用固定 1.2 扩展倍数。

`data/evaluation_manifest.json` 和每例的 `evaluation_gt.npz` 仅供评分。DexYCB 的 K 字段来自官方标注缓存中的相机标定，模型只读取单独导出的 K，不读取手、物体或深度真值。Aria 的图像先经官方针孔校正，再顺时针旋转 90° 并缩放至 768×768；每帧 K 与这些像素严格对应。Aria GT 已保存 upright 相机到世界变换，评价取其逆得到相机坐标。相机轨迹始终留在评价文件。

Aria 3209 的左手第 20–50 帧共 31 帧无检测。HGGT 保留缺失；HaWoR 的原生 infiller 输出保留。主要指标使用两者共同有效的 715 个手帧，覆盖率以全部 746 个已标注手帧为分母。DexYCB 只在整个片段中检测到右手，展示隐藏 HaWoR infiller 无依据生成的左手。

## HaWoR 标定重跑

此前 4 条运行的 focal 分别为 587.7819、588.3139、400.4421、378.5926 px。本轮统一改用公开标定；DexYCB 的实际 fx/fy 为 616.64087/616.25818 px，Aria 两条约为 331.933/332.228 px。

HaWoR API 接受一个 scalar focal 和一个 principal point，因此每段取 `median((fx+fy)/2)` 及 cx/cy 中位数。DexYCB 两轴 focal 的近似误差小于 0.04%；Aria 标定在片段内的变化小于 0.001 px。每例 `predictions.npz` 保存实际使用的 `K_used`。

`run_hawor_calibrated.py` 调用既有 HaWoR checkpoint、原生模型推理、原生 chunk 分组、左右手姿态转换、infiller 与 MANO 解码。适配内容：

- 复用已审计的 RGB 解码帧与检测框；使用公开 K。
- 左图水平翻转时同步翻转 principal point；解码时用真实图宽还原 bbox，并恢复原主点。原代码用 `2*cx` 代替图宽，适用于居中主点；此兼容补丁使非居中标定也保持一致。
- 省略只供 SLAM 使用的手部 mask 栅格化和原 aitviewer 导出。相机模式推理与 infiller 不依赖这两个可视化产物。

HaWoR 来源为既有 Do as I Do 复现所使用的 vendored runtime，目录未保留 Git 元数据。`reports/data_inventory_hawor_provenance.json` 保存模型代码的 SHA-256、checkpoint 路径与文件大小；不猜测 upstream commit。新标定输出与旧结果分目录保留。

## 指标

主指标是 wrist-relative MPJPE 和每个手帧独立做旋转、平移、尺度对齐后的 PA-MPJPE，单位 mm。保留 16 个原生 MANO FK 骨关节，并统一 5 个指尖到对应数据集的定义：

| 数据集 | thumb / index / middle / ring / little 顶点编号 |
|---|---|
| DexYCB | 745, 317, 444, 556, 673 |
| HOT3D-Aria | 744, 320, 443, 554, 671 |

HGGT 自带的指尖为 745, 317, 445, 556, 673；HaWoR 自带定义与 Aria GT 一致。已独立数值核验 DexYCB GT 解码及 MANO 资产的 J_regressor 一致，故只需替换指尖，无须重新回归 posed mesh。各方法原生关节定义下的数值也保留在 JSON。

绝对相机坐标 MPJPE 单列：HGGT 使用它自己的 2D 投影与 K 求一个整体平移，手形和姿态保持不变；HaWoR 使用标定重跑的相机输出。HGGT 原始绝对误差另存 `native_mpjpe_mm`，不把几何适配结果写成原生模型输出。运动指标为去腕后的关节加速度误差：DexYCB 连续帧按标称 30 Hz 计时，Aria 使用原始纳秒时间戳；仅统计双方连续三帧均有效的位置。

运行评价：

```bash
python scripts/data_eval/evaluate_comparison.py --root /path/to/hggt-reproduction-20261110
```

输出 `reports/metrics.json`、逐帧 CSV 和每例 metric arrays。JSON 中每个指标都有共同有效手帧数、绝对评价手帧数或加速度三帧组数；`coverage` 是 0–1 的比例。

这 4 条是开发样例，作者训练集重叠尚未逐条核实；结果用于直接观察单目输入下的效果与误差，不代表完整测试集排名。本轮评价的是相机坐标手部重建，没有为 HGGT 添加世界轨迹估计。
