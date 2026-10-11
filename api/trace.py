from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse
import asyncio
import json

from api.common import resp, CODE_OK, catch_exception
from core.helper.trace_tracker import GLOBAL_TRACKER

router = APIRouter(prefix="/trace", tags=["开发调试-流程日志"])

@router.get("/all")
@catch_exception
def get_all_trace_logs():
    """获取本轮全部流程日志（页面初始化一次性加载）"""
    logs = GLOBAL_TRACKER.get_all_trace()
    # 附带 version：前端据此判断后端是否已开启新一轮日志（clear_trace），避免旧条目占位导致显示不全
    return resp(CODE_OK, "获取全流程日志成功", data={"version": GLOBAL_TRACKER.version, "logs": logs})

@router.get("/latest")
@catch_exception
def get_latest_single_trace():
    """获取最新一条流程日志（前端轮询用）"""
    latest = GLOBAL_TRACKER.get_latest_trace()
    return resp(CODE_OK, "获取最新日志", data=latest)

@router.get("/stream")
def stream_trace_real_time():
    """SSE长连接，实时推送新增流程日志（携带 version，便于前端在换轮次时重置视图）"""
    async def generator():
        last_index = 0
        last_version = GLOBAL_TRACKER.version
        while True:
            version = GLOBAL_TRACKER.version
            all_logs = GLOBAL_TRACKER.get_all_trace()
            # clear_trace 后游标归零，避免 last_index 失配导致该连接永久断更
            if version != last_version:
                last_index = 0
                last_version = version
            if len(all_logs) > last_index:
                new_items = all_logs[last_index:]
                last_index = len(all_logs)
                yield {
                    "data": json.dumps({"version": version, "logs": new_items}, ensure_ascii=False)
                }
            await asyncio.sleep(0.4)
    return EventSourceResponse(generator())