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
