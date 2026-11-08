# 心迹 / Psych Journal 品牌资产

母版：`assets/brand/source/xinji-logo-butterfly-2048.png`（方向 A「年轮新芽」+ 外圈左上蝴蝶）。

## 网页与桌面图标

全部对外资源在 `web/public/brand/`，构建时由 Vite 原样复制到 `web/dist/brand/`：

| 文件 | 用途 |
| --- | --- |
| `xinji-mark-transparent-32/64/128/512/1024.png` | 透明底纯图形标；侧栏使用 128 |
| `xinji-mark-on-white-1024.png` | 白底纯图形标 |
| `xinji-logo-full-white-2048.png` | 白底完整 lockup（图标在上、字标在下） |
| `xinji-logo-full-transparent-2048.png` | 透明底完整 lockup |
| `favicon.ico` | 16/32/48/64/128/256 多尺寸 |
| `favicon-32.png` / `favicon-192.png` / `favicon-512.png` | 浏览器与 PWA 图标 |
| `apple-touch-icon.png` | 180×180，iOS 主屏 |
| `app-icon-1024.png` | PWA / 后续桌面壳图标 |
| `site.webmanifest` | PWA 名称、主题色与图标清单 |

`web/legacy/brand/` 保留同一套副本，供 `web/dist` 不存在时 FastAPI 兜底到 legacy 页面使用。

## 前端落点

- `web/index.html`：favicon、apple-touch-icon、manifest、theme-color。
- `web/src/components/layout/AppRail.vue`：`.rail__seal` 改为 44×44 透明图形标，保留 `aria-hidden` 与空 `alt`。
- `web/legacy/index.html` / `web/legacy/style.css`：同步替换 `.brand-seal`，保留字标。

## 角色头像

三个对话角色统一使用透明圆盘 PNG，不再使用文字头像：

| 角色 | 源图（2048） | 网页用图（512） |
| --- | --- | --- |
| 我 | `assets/brand/source/avatars/user-2048.png` | `web/public/avatars/user.png` |
| 引导者 | `assets/brand/source/avatars/guide-2048.png` | `web/public/avatars/guide.png` |
| 建议者 | `assets/brand/source/avatars/advisor-2048.png` | `web/public/avatars/advisor.png` |

`web/legacy/avatars/` 保留同一套副本，供 `web/dist` 不存在时 FastAPI 兜底到 legacy 页面使用。三个角色均朝右，圆盘直径已归一化到画幅约 94%；「我」用暖玫瑰粉与珊瑚围巾作为主识别，头部占比略大。

前端落点：

- `web/src/components/chat/ChatMessage.vue`：`avatarChar` 已改为 `avatarSrc`，`<img class="msg__avatar">` 固定 34×34、圆形、`object-fit: cover`，保留名字标签与空 `alt` / `aria-hidden`。
- `web/legacy/app.js` / `web/legacy/style.css`：`addMessage()` 同步改为 `<img class="msg-avatar">`，删除三角色文字底色规则。

协议值不变：`speaker=advisor` 仍表示「建议者」，`speaker=guide` 表示「引导者」；`role=user/assistant` 仍由 LangChain/OpenAI 协议依赖。

## 构建与部署

```powershell
cd web
npm run build
```

Windows 下 Vite 内置 rimraf 删除字体目录会偶发 `ENOTEMPTY`，且项目路径可能经 C: 链接指向 D: 实际目录。构建脚本已改为：

- `npm run clean:dist`：用 PowerShell 清理 `dist`；
- `node scripts/build.mjs`：先 `chdir` 到 realpath，再启动 Vite。

Docker 侧 `.dockerignore` 已把 `dist` 限定为根目录 `/dist`，因此 `web/dist` 会进入镜像：

```powershell
docker compose build
docker compose up -d
```

## 验收

- `npm run build` 成功，`web/dist/brand/` 含全部图标。
- `http://127.0.0.1:8000/` 返回 200，首页含 favicon/manifest 链接，并加载 Vue 构建资源。
- `/brand/favicon.ico`、`apple-touch-icon.png`、`site.webmanifest`、`xinji-mark-transparent-128.png` 均返回 200 与正确 MIME。
- 浏览器内 `.rail__seal` 图片 44×44、`naturalWidth=128`、加载完成；截图见 `assets/brand/app-rail-preview.png`。
- 角色头像 `/avatars/user.png`、`guide.png`、`advisor.png` 均返回 200 `image/png`；浏览器内实测 `.msg__avatar` 为 34×34、`naturalWidth=512`、加载完成；截图见 `assets/brand/avatars-chat-message.png`。
