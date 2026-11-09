# PsychAgent 概念节点图标

一组用于图谱节点的极简图标，统一以 48×48 设计坐标绘制，透明底，可直接作为 SVG 导入。

| 概念 | SVG | 512px PNG | 主色 |
|---|---|---|---|
| 记忆 | `concept-memory.svg` | `concept-memory.png` | 黄铜 `#B08A4C` + 锈红 `#C24A2E` |
| 知识 | `concept-knowledge.svg` | `concept-knowledge.png` | 深青 `#4E6D6A` + 锈红 `#C24A2E` |
| 引导 | `concept-guidance.svg` | `concept-guidance.png` | 黄铜 `#B08A4C` + 锈红 `#C24A2E` |

- 画布：`viewBox="0 0 48 48"`，主体控制在 7–42 的设计坐标内。
- 线宽：主体 1.4，贯穿线 1.9；在 120px 节点上约为 3.5–4.8px。
- 背景：无底色、无纸纹、无投影，PNG 四角 Alpha 为 0。
- 预览：`concept-icons-120-preview.png` 是按图谱节点 120px 实际尺度合成的对照图。
- 生产副本：已放入 `web/public/brand/graph/`，可在节点 `<image>` 中直接引用。
- 当前未修改 `web/src/core/graph/glyphs.ts`；若要把它们接入现有 `memory / document / reason` 字形，需要另行确认对应关系。
