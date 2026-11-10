# HGGT / HaWoR 单视角复现展示

这是纯静态展示页，不依赖 npm、CDN 或外部字体。它延续用户提供的 EgoHSI3R 展示页：米白背景、逐序列白卡、对比视频、关键帧与原始记录链接。实际结果全部由 `manifest.json` 载入。

## 对接文件

- `index.html`：页面结构。
- `style.css`：桌面与手机布局。
- `app.js`：manifest 渲染、指标表、数据集筛选与播放器。
- `manifest.json`：真实实验数据；初始状态为空，不包含演示指标或伪造结果。
- `manifest.schema.json`：JSON Schema。

将实际媒体置于站点目录内，使用相对路径。发布 GitHub Pages 时可直接将本目录作为站点根；所有资源和链接均兼容仓库子路径。

## 数据字段

顶层：

| 字段 | 用途 |
| --- | --- |
| `schema_version` | 固定为 1。 |
| `title`, `subtitle`, `updated_at` | 页标题、副标题与更新时间。 |
| `summary` | 结论段落数组，仅放已经实际验证的结果。 |
| `protocol` | `[{label, value}]`，记录单相机、检测框、时序输入、坐标系、GT 用途等。 |
| `scope_notes` | 集中说明比较范围或必要限制。 |
| `metric_definitions` | `[{key, label, unit, description, decimals}]`，决定指标列及其解释。 |
| `metrics_note` | 总表下的评价范围说明。 |
| `downloads` | 顶部下载链接 `[{label, href}]`。 |
| `sources` | 官方资料 `[{label, url, note}]`。 |
| `samples` | 下列样例记录数组。 |

每个样例：

| 字段 | 用途 |
| --- | --- |
| `id` | 唯一英文/数字/下划线 ID，用于页面锚点。 |
| `title`, `short_title`, `dataset` | 对用户有意义的中文名称、导航短名、数据集。 |
| `sequence`, `camera` | 真实序列与相机身份。 |
| `frame_count`, `fps` | **导出回放视频**的帧数与帧率；播放器据此逐帧。 |
| `source_frame_start` | 连续原始帧的起始 ID，可省略。 |
| `source_frame_ids` | 非连续原始帧 ID 数组；优先于起始 ID。 |
| `video_frame_timestamps_s` | 仅 VFR 视频需要：每个视频帧的呈现时间，从零开始，长度必须等于 `frame_count`。不要填绝对采集时间。 |
| `description`, `notes` | 样例描述与必要解释。 |
| `status` | `complete` / `running` / `pending` / `unavailable`。 |
| `status_label` | 可选，用实际状态文本覆盖通用标签。 |
| `legend` | 颜色、坐标或投影方式说明，显示在播放器下面。 |
| `media` | 下文的视频资源。 |
| `metrics` | `[{method, values:{指标key:真实数值}}]`。所有 key 必须在顶层 `metric_definitions` 中定义。 |
| `metrics_note` | 此样例评价帧、有效性掩码、手侧或 GT 范围。 |
| `metrics_pending_message` | 没有指标时可说明实际原因。 |
| `links` | `[{label, href}]`，每序列 CSV、JSON、预测等下载。 |
| `keyframes` | `[{src, label, frame_index}]`，建议首/中/末三张真实关键帧。 |

### 视频资源

`media` 支持 `input`、`hggt`、`hawor`、`comparison` 四项。每项可以是相对路径字符串，或者 `{src, poster, label, width, height}`。

推荐导出同一个 `comparison.mp4`，包含原 RGB、HGGT、HaWoR 三栏。播放器优先选择 `media.comparison`，三个画面天然严格同帧。如果未提供拼接视频，则横向显示已有的独立视频，通过共享时间轴、逐帧按钮和播放时漂移校正同步。独立视频必须预先统一帧数、帧率、裁剪范围和帧映射。

播放器默认静音，不自动播放；一次仅运行一个样例，切换后台时暂停。支持 0.25× / 0.5× / 1× / 2×，回放帧编号从 1 开始，原始帧 ID 单独显示。焦点在播放器区域时，左右方向键逐帧、空格播放。

### 指标

列完全由 `metric_definitions` 决定，不强制指标名称。建议 `mpjpe_rr_mm`、`pa_mpjpe_mm`、`matched_frames`；如果实际评价脚本采用别的名称，直接用其原 key。缺失值使用 `null`，显示 `—`；不要使用零代替缺失结果。展示页不会自动将最小值宣称为胜出，因为是否同帧、同手、同坐标必须由实验流程确认。

## 检查与预览

语法检查：`node --check app.js`。

需通过 HTTP 服务预览，直接 `file://` 打开会受到浏览器读取 JSON 的限制。浏览器 QA 应使用获准的浏览器工具，优先在云端或 Ubuntu；不要在 Mac 启动重型 3D 调试。

发布前确认：manifest 实际样例数、每个媒体与下载路径存在、视频帧数/帧率一致、关键帧真实对应、指标单位和 GT 评价范围准确。页面不执行推理、拟合或指标重算。

## 版式来源

参考用户指定的 [EgoHSI3R 复现页](https://egohsi3r-experiments-20261104.yichengdraw.chatgpt.site/)；通过用户已有的 `egohsi3r_reproduction_20261104/index.html` 核对其实际结构。本页新增同步回放控件和指标汇总，不修改原站点。

## 可操作三维视图（2026-11-10 立体交互更新）

`viewer3d.js` 负责选择、手势与视频同步，`hand-renderer.js` 是无外部依赖的透视三维渲染器。默认使用 WebGL；若不可用，则使用像素级深度缓冲的软件三维后备。圆柱骨骼、球形关节具有方向光、高光与深度遮挡。屏幕空间轨迹球四元数让物体跟随拖动，没有旧版左右方向反转或俯仰极点锁定。

透明手壳由当前 21 关节位置和启发式厚度生成，仅是形状示意，不是 GT 真实表面、MANO 网格或方法预测网格，不用于评价。可关闭或调节不透明度。没有新增 MANO 顶点、拓扑或授权模型资产。骨骼显示半径同样是视觉参数，关节中心及源数据不变。多方法透明表面相交时，透明混合是可视化近似。

保留 GT / HGGT / HaWoR 独立显隐、原生 / 标定平移适配 HGGT、左右手、相机空间 / 腕部平移对齐。默认与重置均使用输入 RGB 相机方向（+X 向右、+Y 向下、无镜像），自动居中缩放并容纳整段运动，不声称与视频逐像素投影重合；「聚焦当前帧」与双击可放大当前姿态，「容纳整段」恢复完整观察范围。缩放不改变源几何。极端放大会产生相机近裁剪，适时使用重置。

查看器通过 `comparisonframe` 与原播放器共用帧索引；回放使用解码帧的 `mediaTime`。有样例 hash 时自动加载该例，否则加载第一例，其余按需载入，避免滚动时自动展开导致布局跳动。无效手与关节保留为空，HaWoR 时序补全明确标记。数据来源和许可见 `interactive3d/README.md`。

验证（仓库根目录）：

- `node --check docs/hand-renderer.js`
- `node --check docs/viewer3d.js`
- `node --check docs/app.js`
- `node tests/test_hand_renderer.cjs`
- `python scripts/validate_interactive_3d.py`

Node 测试覆盖拖动方向/逆操作/长期归一化、真实数据有限性与不变性、空值、透明壳开关、软件深度缓冲和 WebGL 提交数学。数据验证涵盖 446 帧和 31 个时序补全手帧、原始帧映射、单位、左右手、原生/适配平移关系及与既有指标的一致性。

浏览器测试夹具在 `tests/browser/`，从仓库根目录提供 HTTP 服务后打开 `tests/browser/qa.html`。夹具以 390px iframe 验证手机布局、实际页面的选择/帧控制和模拟指针/触摸处理。鼠标拖动另通过浏览器实际输入检查。模拟触摸不等同于物理手机测试。云端 QA 浏览器关闭 WebGL，因此在该浏览器验证的是软件后备；GPU 路径需在提供 WebGL 的浏览器检查。

### 场景中的 RGB 相机

「相机与视锥」开关默认开启：光心为当前帧相机坐标原点 `(0,0,0)` m，光轴沿 `+Z`。相机图标、三轴和视锥是三维几何，随外部观察角旋转并参与深度遮挡。保留默认相机方向；独立外部斜视概览始终展示相机与当前帧手的关系，「相机与手全景」将主视图切为外部斜视并容纳相机与整段手部。不会为了让图标进入画面而改变相机物理位置。

视锥使用 `interactive3d/cameras.json` 中对应帧的 K 和处理后 RGB 尺寸。Aria 内参保留微小逐帧变化，表示官方转换后的针孔 RGB，不是原始鱼眼。DexYCB 表示现有 K 针孔投影模型，未独立验证镜头零畸变。视锥 0.4 m 长度和机身尺寸只是显示参数，不代表真实机身、裁剪面、测量范围。无世界相机外参或运动轨迹，不做推测。

腕部平移对齐会分别平移每个方法/手，不能再对应一个共同相机原点，此模式隐藏相机与视锥并说明原因。HGGT 平移适配只移动预测手而不移动相机；原生 HGGT 使用自身的投影假设，不能用真实 K 视锥判断其原生 2D 投影吻合。
