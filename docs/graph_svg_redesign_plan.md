# 图谱视觉重设计：Canvas → SVG

> 版本：v1.0 · 2026-11-08
> 范围：`core/graph/renderer.ts` 整体替换为 SVG 渲染层；`GraphCanvas.vue` 挂载方式调整
> 不做：物理模拟（`physics.ts` 保持不变）、交互逻辑（`engine.ts` 的指针处理保持不变）

---

## 1. 为什么换 SVG

用户要求四项：**精致矢量细节、CSS hover/选中、暗色模式、任意倍率清晰**。
前三项是 Canvas 的结构性短板，不是画得好不好的问题：

| 需求 | Canvas 现状 | SVG 后 |
|---|---|---|
| CSS `:hover` / `:focus` | **不存在**。必须 `if (hoveredId === n.id)` 手写状态机 + 手动重绘 | `.node:hover .halo { opacity: 1 }` 原生生效 |
| 暗色模式 | 切换要 `readGraphTheme()` 重读 + 整块重绘；CSS 变量对它无效 | `[data-theme="dark"] { --entity-session: … }` 即可 |
| 任意倍率清晰 | 受 DPR 与 canvas 位图限制；缩放到 3x 时文字模糊 | 矢量，任何倍率都锐利 |
| 精致细节 | 靠 `ctx.arc` / `roundRect` 逐行拼，代码难维护 | `<defs>` 里定义 filter / gradient / pattern，声明式复用 |
| 无障碍 | 节点对屏幕阅读器完全不可见（只有 `aria-label` 汇总） | 每个 `<g role="button"><title>` 可被读屏 |

### 规模判断（决定可行性的关键数据）

实测当前图谱：**4 节点 / 3 连线**。代码里 Barnes-Hut 的启用阈值是 80，说明设计假设的上限也就百级。
SVG 在数百节点内完全够用；本项目实际长期运行规模预计 **10–40**，远低于风险线。

### 迁移风险控制

- **物理层不动**：`physics.ts`（force / quadtree / settle）是纯数学，与渲染无关
- **交互层不动**：`engine.ts` 的 pointer / wheel / 命中检测（`findNode` 基于坐标+半径）继续用
- 只替换：**如何把 SimNode[] 画到屏幕上**

---

## 2. 视觉设计

### 2.1 设计原则

当前的单调感来自三点：**纯色填充、单一描边、无层次**。
新方案不加装饰性噪音，而是用**同一套几何语言**把"材质感"做进去：

1. **每类节点一个形状 + 一个内部纹样**，形状区分类型，纹样暗示含义
2. **双层结构**：底色层（soft）+ 结构层（line）+ 高光层（highlight）
3. **状态即视觉**：default / hover / active / dimmed 四种状态用 CSS 类切换，全部有过渡

### 2.2 四种节点的几何语言

| 类型 | 形状 | 内部纹样 | 语义联想 |
|---|---|---|---|
| **会话 session** | 双环圆（外环 + 内实心） | 中心一个实心点 + 环绕呼吸环 | 中心、此刻、活的 |
| **记忆 memory** | 圆 | 内部三道弧线（像书页/年轮） | 记忆的层积 |
| **文档 document** | 圆角方 | 右上折角 + 两道横线（文本行） | 纸张 |
| **推理 reason** | 菱形 | 内嵌小菱形 + 中心点 | 推进一步 |

**为什么这样分**：
形状是给"扫一眼"的（圆=活的、方=资料、菱形=步骤），纹样是给"看仔细"的（带折角的是文档、带年轮的是记忆）。两者都不依赖颜色，色盲用户也能区分。

### 2.3 分层结构（每个节点的 4 层）

```
<g class="gnode gn--document">
  <circle class="gnode__halo" />     ← 光晕：hover/active 时显现
  <rect class="gnode__base" />       ← 底：soft 色填充
  <path class="gnode__mark" />       ← 纹样：折角、年轮、横线
  <rect class="gnode__ring" />       ← 描边：line 色
  <text class="gnode__label" />      ← 标签（反向缩放）
  <title>标题 + 类型 + 摘要</title>   ← 无障碍
</g>
```

**光晕层**是最关键的一层：它让 hover 有"点亮"的感觉，而不是单纯变色。

- default：`opacity: 0`
- hover：`opacity: 1`，半径放大 1.35x，用 `radialGradient` 做柔和衰减
- active（选中）：`opacity: 1` + 加一圈虚线旋转环（`stroke-dasharray` + CSS animation）

### 2.4 连线

| 关系 | 线型 | 说明 |
|---|---|---|
| session_bind_memory | 实线 | 主关系 |
| session_ref_doc | 长虚线 | 引用 |
| memory_ref_doc | 点线 | 次要引用 |
| memory_related_memory | 密点线 | 弱关联 |
| reason_next | 实线 + 箭头 | 推理递进 |
| session_bind_reason | 短虚线 | 进入推理链 |

**改进**：
- 加**方向箭头**（`marker-end`），关系有方向感
- hover 节点时，相关连线 `stroke-width` 从 1.2 → 2，其余降到 0.15 alpha
- 走线用 SVG `path` 的二次贝塞尔（复用现有偏转算法，只是从 ctx 换成 `d` 属性）

### 2.5 暗色调色板

Canvas 版暗色需要重算所有颜色；SVG 版只需覆盖 CSS 变量。

```css
[data-theme='dark'] {
  --surface-overlay:  #1c1917;   /* 图谱背景 */
  --border:           #3a3330;
  --text-primary:     #ebe3d5;

  /* 实体色在深底上需要提亮 + 降饱和，否则刺眼 */
  --entity-session:   #e0705a;
  --entity-memory:    #cfaa6a;
  --entity-document:  #6d9d97;
  --entity-reason:    #a98cc0;

  /* 底色层：深色下不能是"更亮"，要是"同色系更暗" */
  --entity-session-soft:  #3a2420;
  --entity-memory-soft:   #3a3020;
  --entity-document-soft: #1f3331;
  --entity-reason-soft:   #2c2438;
}
```

深色下的关键调整：**底与描边的对比要反过来**——浅色模式下底色浅、描边深；深色模式下底色比背景略亮、描边更亮，靠"微光"表现立体。

### 2.6 缩放时的文字处理

当前 Canvas 版：标签随 `ctx.scale` 线性放大，放大到 3x 时文字巨大。

SVG 版：给 `<text>` 应用反向缩放
```
labelScale = clamp(1 / viewScale, 0.6, 1.6)
```
字号在 0.6–1.6 倍之间浮动，缩放时保持可读但不失控。这是 SVG 才做得到的（可以独立变换每个元素）。

---

## 3. 实现结构

### 3.1 文件职责

```
core/graph/
├── physics.ts      【不改】力模型 / 四叉树 / settle
├── engine.ts       【小改】把 renderer 换为 svg-renderer；命中检测不变
├── theme.ts        【删】色值改由 CSS 变量直接驱动，不再 JS 读取
├── svg-renderer.ts 【新增】SimNode[] → SVG DOM 的增量更新
└── svg-defs.ts     【新增】<defs> 内容：渐变、滤镜、箭头、纹样 path
```

### 3.2 渲染策略：**增量更新，不重建 DOM**

这是 SVG 方案唯一需要小心的性能点。每帧 `innerHTML = ''` 会摧毁 CSS 过渡（元素被替换，过渡没有起点）。

```
setData(data):
  1. 按 id 做 diff
  2. 新增节点 → createElement + append
  3. 删除节点 → remove（带淡出动画后再移除）
  4. 已存在 → 只更新 transform 属性

每帧 tick:
  只改 <g class="gnode"> 的 transform="translate(x,y) scale(s)"
  → 几何不变，只移动，浏览器可 GPU 加速
```

**transform 用属性而非 CSS**：CSS transition 不介入位置更新（否则每帧插值会拖尾），位置是逐帧设置的绝对坐标。

### 3.3 状态切换走 CSS

| 状态 | 触发方式 | 视觉 |
|---|---|---|
| `.is-hovered` | JS 加类（同时设置 `state.hoveredId`） | 光晕显现、节点放大 1.08、标签强制显示 |
| `.is-active` | 点击选中 | 光晕 + 虚线旋转环 + 描边加粗 |
| `.is-dimmed` | 聚焦模式下非目标类型 | opacity 0.15 |
| `:focus-visible` | 键盘 Tab | 焦点环（`outline`） |

**为什么 hover 还要 JS 加类**：SVG 的 `:hover` 只在指针真的在元素上时生效，但物理引擎里节点在动——用 JS 的命中检测（已有）更准，且能与"邻接高亮"联动。CSS `:hover` 作为兜底（快速划过时也能响）。

### 3.4 性能护栏

- **不写 `<text>` 的每帧变更**：标签内容只在 `setData` 时更新
- **光晕用 CSS 不重绘**：`radialGradient` 定义在 `<defs>`，切换 opacity 不触发几何重排
- **>200 节点降级**：关闭光晕与纹样，只画底 + 描边 + 标签（保留功能）。低于该规模不考虑

---

## 4. 验证标准

| 项 | 标准 |
|---|---|
| CSS hover 生效 | 指针移入节点 → 光晕 opacity 0 → 1，**无需 JS 重绘** |
| 任意缩放清晰 | 缩放到 3x，节点路径边缘无锯齿（截图对比） |
| 暗色切换 | 给容器加 `data-theme="dark"` → 全部元素换色，无残留浅色 |
| 无障碍 | 每个节点是 `role="button"` + `<title>`，屏幕阅读器可遍历 |
| 性能 | 40 节点保持 55fps；静止仍自动停帧 |
| 视觉一致性 | 与全站纸感令牌协调，不出现"另一个设计系统" |

---

## 5. 待确认的取舍

1. **是否保留网格底纹**：当前有 26px 网格。SVG 版拟改为更淡的 `<pattern>`，或去掉换成极淡的噪点。倾向**保留但降到几乎不可见**（保留空间参照感）。
2. **箭头密度**：所有连线都加箭头会显乱。倾向**只在 hover/选中时显示箭头**，静态时纯线。
3. **光晕动画**：选中态的"虚线环旋转"是持续动画，与"静止停帧"原则冲突。倾向**选中时允许该动画**（此时用户正在关注，不是静止浏览）。
