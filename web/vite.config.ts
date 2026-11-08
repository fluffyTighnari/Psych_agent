import { fileURLToPath, URL } from 'node:url'
import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 后端未改动的全部路由前缀：开发期直接代理到本地 FastAPI，避免 CORS。
const BACKEND = 'http://127.0.0.1:8000'
const API_PREFIXES = [
  '/chat', '/session', '/tool', '/ollama', '/knowledge', '/memory',
  '/graph', '/trace', '/retrieval',
]

export default defineConfig({
  plugins: [vue()],
  /*
   * 资源基础路径。
   * P6 起新版已作为默认界面挂在根路径，因此默认值为 `/`。
   * 若需要临时并行部署到子路径，构建时传 VITE_BASE=/next/。
   */
  base: process.env.VITE_BASE ?? '/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PREFIXES.map((p) => [p, { target: BACKEND, changeOrigin: true }]),
    ),
  },
  build: {
    // 产物直接落在 web/dist，后端只需把静态目录指过来
    outDir: 'dist',
    // Windows 下 Vite 内置 rimraf 删除字体目录会偶发 ENOTEMPTY；
    // 由 npm run clean:dist 在构建前清理，这里关闭自动清空。
    emptyOutDir: false,
    rollupOptions: {
      output: {
        // 图谱引擎 / 编辑器各自独立分包，避免首屏体积膨胀
        manualChunks(id) {
          if (id.includes('node_modules')) {
            if (id.includes('@codemirror') || id.includes('@lezer')) return 'editor'
            return 'vendor'
          }
          return undefined
        },
        assetFileNames: (asset) => {
          const name = asset.names?.[0] ?? ''
          // 字体文件带内容哈希，长期缓存
          if (/\.(woff2?|ttf|otf)$/i.test(name)) {
            return 'assets/fonts/[name]-[hash][extname]'
          }
          return 'assets/[name]-[hash][extname]'
        },
      },
    },
    chunkSizeWarningLimit: 700,
  },
})
