import asyncio
import json

from fastapi import APIRouter
from sse_starlette.sse import EventSourceResponse

from api.common import resp, CODE_OK, ChatRequest, catch_exception
from core.agent import agent_service_entry
from core.helper.trace_tracker import GLOBAL_TRACKER

router = APIRouter(prefix="/chat", tags=["主对话"])


@router.post("")
@catch_exception
def chat_normal(req: ChatRequest):
    """普通一次性对话接口，完整返回结果"""
    result = agent_service_entry(req.user_input, req.situation, req.role, req.mode)
    return resp(CODE_OK, "对话处理完成", data=result)


@router.post("/stream")
def chat_stream(req: ChatRequest):
    """SSE流式对话：推送流程阶段 + 逐字回答"""
    # 请求开始前清空 trace（而非生成器内），避免并发请求在生成器里互相清空
    GLOBAL_TRACKER.clear_trace()

    async def stream_generator():
        try:
            # 将同步阻塞的 agent_service_entry 放到线程池执行，避免阻塞事件循环
            loop = asyncio.get_running_loop()
            full_result = await loop.run_in_executor(None, agent_service_entry, req.user_input, req.situation, req.role, req.mode)
        except Exception as e:
            # 兜底：LLM/检索异常时推送明确 error 事件，前端可展示而非断流
            GLOBAL_TRACKER.add_trace(
                stage="chat_stream",
                label="对话处理失败（SSE兜底）",
                content={"error": str(e), "input": (req.user_input or "")[:80]},
                is_error=True,
                error_msg=str(e)
            )
            yield {"data": json.dumps({"type": "error", "message": f"服务暂时不可用：{e}"}, ensure_ascii=False)}
            yield {"data": json.dumps({"type": "finish"}, ensure_ascii=False)}
            return
        # 推送消息身份与结束标记，供前端渲染引导者/建议者
        yield {"data": json.dumps({
            "type": "meta",
            "intent_type": full_result.get("intent_type", ""),
            "ended": full_result.get("ended", False),
        }, ensure_ascii=False)}
        # 推送全流程日志
        all_trace = GLOBAL_TRACKER.get_all_trace()
        yield {"data": json.dumps({"type": "trace_all", "logs": all_trace}, ensure_ascii=False)}
        # 逐字推送回答
        full_ans = full_result.get("reply", "")
        chunk_size = 8
        for i in range(0, len(full_ans), chunk_size):
            chunk = full_ans[i:i + chunk_size]
            yield {"data": json.dumps({"type": "reply_chunk", "content": chunk}, ensure_ascii=False)}
        # 结束标记
        yield {"data": json.dumps({"type": "finish"}, ensure_ascii=False)}

    return EventSourceResponse(stream_generator())