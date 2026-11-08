import { createApp } from 'vue'
import { createPinia } from 'pinia'

import './styles/tokens.css'
import './styles/base.css'
import './styles/utilities.css'
import './styles/components.css'
import './styles/graph.css'

import App from './App.vue'
import router from './router'
import iconSprite from './assets/icons.svg?raw'
import { initFonts } from './core/fonts'
import { useSessionStore } from './stores/session'
import { useModelsStore } from './stores/models'

/** sprite 只需注入一次，<use href="#i-xxx"> 全站复用 */
function injectIconSprite() {
  const holder = document.createElement('div')
  holder.setAttribute('aria-hidden', 'true')
  holder.style.cssText = 'position:absolute;width:0;height:0;overflow:hidden'
  holder.innerHTML = iconSprite
  document.body.appendChild(holder)
}

injectIconSprite()

const app = createApp(App)
const pinia = createPinia()
app.use(pinia)
app.use(router)
app.mount('#app')

/*
 * 首屏数据并行加载。失败不阻塞 UI —— 各视图自己渲染错误态并提供重试，
 * 这比整页白屏或一个全局遮罩要好。
 */
const session = useSessionStore(pinia)
const models = useModelsStore(pinia)
void Promise.allSettled([session.load(), models.load()])

/* 字体不阻塞挂载；Canvas 组件绘制前自行 await fontsReady() */
void initFonts()
