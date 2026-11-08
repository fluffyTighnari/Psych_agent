import { createRouter, createWebHashHistory, type RouteRecordRaw } from 'vue-router'

/**
 * 使用 hash 模式：后端用 StaticFiles 挂在 `/`，没有 SPA fallback 路由，
 * history 模式下刷新深链接会 404。hash 模式无需改动后端。
 */
const routes: RouteRecordRaw[] = [
  {
    path: '/',
    name: 'chat',
    component: () => import('./views/ChatView.vue'),
    meta: { title: '主对话', sub: '与你的心理咨询师进行一场安静的对话' },
  },
  {
    path: '/records',
    name: 'records',
    component: () => import('./views/RecordsView.vue'),
    meta: { title: '过往记录', sub: '检索你的知识文档与历史会话记忆' },
  },
  {
    path: '/write',
    name: 'write',
    component: () => import('./views/WriteView.vue'),
    meta: { title: '码字编辑', sub: '记录今日思绪，或做一次周复盘' },
  },
  {
    path: '/trace',
    name: 'trace',
    component: () => import('./views/TraceView.vue'),
    meta: { title: '实时流程日志', sub: '追踪每一次处理的阶段与结构化细节' },
  },
  {
    path: '/retrieval',
    name: 'retrieval',
    component: () => import('./views/RetrievalView.vue'),
    meta: { title: '检索优化调试', sub: '自由组合检索链路，对比每一阶段的召回效果' },
  },
  { path: '/:pathMatch(.*)*', redirect: '/' },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

router.afterEach((to) => {
  const title = (to.meta.title as string | undefined) ?? ''
  document.title = title ? `${title} · 心迹` : '心迹 · Psych Journal'
})

export default router
