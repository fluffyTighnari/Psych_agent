# 图谱节点：原图直接复用

三枚节点使用用户提供的 300×300 原始 SVG，**图形路径、渐变、描边、比例全部未改**。唯一的改动是根节点 `viewBox`：不再用整张 `0 0 300 300`（主体只占约 45%，放进节点会偏小）。本版在 90% 留边基础上，按用户口径只放大知识、引导两枚：**知识再放大约 10%，引导再放大约 5%，记忆保持 90%**。

## 当前参数

| 概念 | 节点 SVG | 512px PNG | 原 viewBox | 节点 viewBox | 主体占画布 |
|---|---|---|---|---|---|
| 知识 | `node-reuse-knowledge.svg` | `node-reuse-knowledge.png` | `0 0 300 300` | `72 102 156 156` | 65.2% 宽 / 98.6% 高 |
| 记忆 | `node-reuse-memory.svg` | `node-reuse-memory.png` | `0 0 300 300` | `89 91 122 122` | 85.5% 宽 / 89.8% 高 |
| 引导 | `node-reuse-guidance.svg` | `node-reuse-guidance.png` | `0 0 300 300` | `87 90 126 126` | 63.3% 宽 / 94.5% 高 |

- 知识：`172 / 156 ≈ 1.10`，相对 90% 版再放大约 **10%**。
- 引导：`132 / 126 ≈ 1.048`，相对 90% 版再放大约 **4.8%**，按 5% 取整。
- 记忆：沿用 90% 版参数，未改。

## 真实图谱实测（100% 视图）

- 页面 `http://127.0.0.1:8000/#/` 当前为 **1 个会话 + 3 篇文档**，没有记忆 / 推理节点；三篇文档节点已实际加载彩色知识图标。
- 文档节点：`2r = 36.8 px`，`image` 盒子 `36.8 × 36.8 px`；DOM 为 `gnode--document gnode--image`，`href="/brand/graph/node-reuse-knowledge.svg"`。
- 会话节点保持原样：`session-orbit.svg`，实测约 `47.8 × 41.8 px`。
- 接入后实测内容尺寸：
  - 知识约 `24.0 × 36.3 px`，上下仅约 **0.25 px** 余量，几乎贴满节点，但未裁切。
  - 引导约 `23.3 × 34.8 px`，上下约 **1.0 px** 余量。
  - 记忆约 `31.5 × 33.0 px`，左右约 **2.6 px**、上下约 **1.9 px** 余量。
- 真实截图：
  - `actual-graph-integrated.png`（575×739，整页）
  - `actual-graph-integrated-panel.png`（359×739，纯净图谱面板）

## 结论：是否过大

- 90% 版知识 / 引导偏轻，是因为原图本身窄高；知识在文档节点里横向只占约 24 px。
- 按用户要求再放大后，知识高度接近节点直径，**观感是饱满而不是溢出**；如果继续加大，边缘会开始被裁切。
- 引导只放大约 5%，仍保留约 1 px 上下余量，视觉重量比知识略轻，符合两枚原图的比例差异。
- `glyphs.ts` 的 `image.width/height` 固定为 **48** 设计单位（等于 `2r`），内容占比由 SVG `viewBox` 控制；不要把 PNG 按 48px CSS 直接塞进文档节点。

## 接入方式

- `web/src/core/graph/glyphs.ts`：`memoryGlyph()`、`documentGlyph()`、`reasonGlyph()` 均已增加 `image`，分别指向：
  - `/brand/graph/node-reuse-memory.svg`
  - `/brand/graph/node-reuse-knowledge.svg`
  - `/brand/graph/node-reuse-guidance.svg`
- `web/src/core/graph/svg-renderer.ts` 已有 `glyph.image` 分支：有 `image` 时只创建 `<image>`，跳过线稿 `parts/dots`，并加 `gnode--image` 类。
- `NodeGlyph.vue` 仍只渲染 `parts/dots`，但现在图谱图例已改为 **8px 纯色圆点**，不再使用线稿图标；圆点颜色取自对应节点图案主色：
  - 会话 `#F2766B`
  - 记忆 `#F59E0B`
  - 文档 / 知识 `#10B981`
  - 推理 / 引导 `#8B5CF6`
- 画布仍显示彩色整图，沿用 `session-orbit.svg` 的既有先例；图例与画布不再共用图标几何。
- 生产副本已同步到 `web/public/brand/graph/`，`npm run build` 已通过，容器已重建，三个 SVG 均返回 `200 image/svg+xml`。

## 校验

- 三份节点 SVG 与 `reuse-*.svg` 原文逐字符比对：除根 `viewBox` 外内容完全一致（`True`）。
- `web/public/brand/graph/node-reuse-*.svg` 与资产目录逐字符一致（`True`）。
- 三份 PNG 均为 512×512、四角 Alpha=0；体积分别约 133,746 / 102,532 / 52,533 bytes。
- 图例实测：四个圆点均为 `8 × 8px`、`border-radius: 50%`，计算色分别为 `rgb(242,118,107)` / `rgb(245,158,11)` / `rgb(16,185,129)` / `rgb(139,92,246)`，图例中已无 SVG 字形。
- `node-reuse-mockup.png` 为 1200×600 的 120px / 48px 两级节点试排，已更新为当前占比。
- 圆形底只是样张载体；节点 SVG 本身无背景、无投影、无文字。

## 注意

- 三枚原图的宽高比例不同：记忆相框最宽，知识羽毛和引导提灯偏窄高。按原比例放进同一个方形节点时，视觉重量不会完全相等；这是原图本身的比例，不是重画造成的。要等重视觉，只能调 `image` 的 `width/height` 或 viewBox 留边，不要改图形路径。
- 当前图谱没有记忆 / 推理节点，因此实机只能验收知识图标；记忆、引导的接入代码已就位，出现对应节点时会直接使用彩色整图。
- 上一版 `node-knowledge.svg` / `node-memory.svg` / `node-guidance.svg` 是简化重绘稿，不是本版；本版以 `node-reuse-*` 为准。
