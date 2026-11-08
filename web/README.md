# 心迹 · 前端（Vue 3 + TypeScript）

设计文档：[`../docs/frontend_rebuild_design.md`](../docs/frontend_rebuild_design.md)

## 开发

```bash
cd web
npm install
npm run dev          # http://localhost:5173，接口自动代理到 :8000
```

开发时后端需先启动（仓库根目录 `python main.py`）。Vite 已配置代理：
`/chat` `/session` `/tool` `/ollama` `/knowledge` `/memory` `/graph` `/trace` `/retrieval`。

> dev server 下 `base` 仍是 `/next/`，直接访问根路径即可（Vite 会正确处理）。

## 构建

```bash
cd web
npm run build        # 先 vue-tsc 类型检查，再 vite build
npm run typecheck    # 只做类型检查
npm run build:fast   # 跳过类型检查
```

产物输出到 `web/dist/`（已 gitignore），后端 `main.py` 会在存在时挂载到 `/next/`。

切换到根挂载（P6 收尾时）：

```bash
VITE_BASE=/ npm run build
# 然后修改 main.py，把根 mount 指向 web/dist
```

## 目录约定

```
src/
├── styles/        tokens → base → utilities → components（严格分层，只引用 role 层令牌）
├── core/          无框架依赖的纯逻辑（api / stream / graph / domain / utils）
├── stores/        Pinia，视图状态
├── components/    ui（无业务语义原子） / layout / chat / graph / writer / records / retrieval
└── views/         五个路由视图
```

硬性规则（详见设计文档 §3.1 / §6.2）：

- `components/` 不做网络请求；`core/` 不 import Vue（Canvas 挂载胶水除外）。
- 所有可展开区域用 `AppDisclosure`，所有面板用 `AppPanel`，所有按钮用 `AppButton`。
- 禁止 `el.style.display`，用 `v-if` 或 `.is-hidden`。
- 禁止裸色值，只能引用 `tokens.css` 里的 role 变量。
- 图标只能从 `assets/icons.svg` 经 `AppIcon` 引用，禁止用 `▸ ✕ ✓` 等字形符号。

## 验证脚本

```bash
node scripts/check-contrast.cjs    # 对比度核算（应全部 PASS）
node scripts/verify-p0.cjs         # 浏览器冒烟：渲染/字体/图标/路由/焦点（需后端在 :8010）
node scripts/verify-focus.cjs      # 焦点环可见性
```

`verify-*.cjs` 里的后端地址是 `http://127.0.0.1:8010`，按需改端口。

## 字体

全部自托管，不依赖 Google Fonts（本地优先、离线可用）。

- 拉丁：`@fontsource/fraunces`、`@fontsource/jetbrains-mono`
- 中文：`@fontsource-variable/noto-serif-sc`、`@fontsource-variable/noto-sans-sc`

CJK 用可变字体 + unicode-range 分片，浏览器按页面实际用到的字按需下载。
`fonts.css` 是独立 CSS 入口（200+ 条 `@font-face` 不能进主 bundle），
由 `src/core/fonts.ts` 动态引入；Canvas 绘制前需 `await fontsReady()`。
