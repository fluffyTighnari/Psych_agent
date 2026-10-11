import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from api import (
    chat,
    state,
    trace,
    knowledge,
    memory,
    tool, model, graph,
    retrieval_debug
)
from config.model_config import BASE_DIR

app = FastAPI(title="心理RAG调试后端接口")

# 允许 web/ 静态前端（file:// 或其它端口）跨域调用后端接口
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
# 挂载所有路由分组
app.include_router(chat.router)
app.include_router(state.router)
app.include_router(trace.router)
app.include_router(knowledge.router)
app.include_router(memory.router)
app.include_router(tool.router)
app.include_router(model.router)
app.include_router(graph.router)
app.include_router(retrieval_debug.router)

# 挂载前端静态页面（路由优先匹配，未命中的请求回落到 web/；用绝对路径，任意工作目录启动均可访问）
app.mount("/", StaticFiles(directory=str(BASE_DIR / "web"), html=True), name="web")

if __name__ == "__main__":
    import uvicorn
    # reload 由环境变量控制：开发设 RELOAD=1，正常运行默认关闭，避免文件变动触发进程重启
    reload_enabled = os.environ.get("RELOAD", "0") == "1"
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=reload_enabled)
