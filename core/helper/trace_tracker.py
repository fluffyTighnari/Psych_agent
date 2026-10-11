from dataclasses import dataclass, asdict
from typing import List, Dict, Any, Optional
from contextvars import ContextVar
import time

# 当前请求「本地 trace」：不经过 GLOBAL_TRACKER 的调用链（如检索调试流水线）
# 用 contextvars 注入后，整个请求内所有写 GLOBAL_TRACKER 的既有代码（reranker / loader /
# knowledge_cache ...）都会自动改写到该本地实例，从而不再污染 /trace/stream。
# contextvars 在 run_in_executor / 线程池中会随上下文复制，天然按请求（而非全局）隔离。
ACTIVE_TRACKER: ContextVar[Optional["TraceTracker"]] = ContextVar("active_trace_tracker", default=None)


def current_tracker() -> "TraceTracker":
    """返回当前应写入的 trace：请求本地实例优先，否则全局实例。"""
    local = ACTIVE_TRACKER.get()
    return local if local is not None else GLOBAL_TRACKER


def use_tracker(tracker: Optional["TraceTracker"]):
    """把 tracker 设为当前请求的 trace；返回 token，供 use_tracker_reset 还原。"""
    return ACTIVE_TRACKER.set(tracker)


def use_tracker_reset(token) -> None:
    """还原 use_tracker 之前的上下文。"""
    try:
        ACTIVE_TRACKER.reset(token)
    except (ValueError, LookupError):
        # token 已失效/跨上下文：退化为清空，保证不抛异常
        ACTIVE_TRACKER.set(None)


# 单条流程日志结构
@dataclass
class TraceItem:
    stage: str
    label: str
    content: Dict[str, Any]
    timestamp: float
    is_error: bool = False
    error_msg: Optional[str] = None

class TraceTracker:
    # 内存 trace 环形上限：防止长会话/长连接下无限增长
    MAX_TRACE = 500

    def __init__(self, enable_console_print: bool = False):
        self.current_trace: List[TraceItem] = []
        # 开关：终端main启动时设True；web服务设False
        self.enable_console_print = enable_console_print
        # 版本号：clear_trace 时自增，SSE 长连接据此重置游标
        self.version = 0

    def add_trace(self, stage: str, label: str, content: dict, is_error=False, error_msg=None):
        # 若当前请求已用 use_tracker 指定了本地 trace（调试请求），且本实例不是那个本地 trace，
        # 则把日志改写到本地 trace，避免污染全局日志流。
        active = ACTIVE_TRACKER.get()
        if active is not None and active is not self:
            active.add_trace(stage, label, content, is_error=is_error, error_msg=error_msg)
            return

        item = TraceItem(
            stage=stage,
            label=label,
            content=content,
            timestamp=time.time(),
            is_error=is_error,
            error_msg=error_msg
        )
        self.current_trace.append(item)

        # 环形截断，防止无限增长
        if len(self.current_trace) > self.MAX_TRACE:
            self.current_trace = self.current_trace[-self.MAX_TRACE:]

        # 开启控制台打印时，自动输出格式化日志（调试请求的本地 trace 默认关闭，避免刷屏）
        if self.enable_console_print:
            self._print_trace_item(item)

    def _print_trace_item(self, item: TraceItem):
        ts = time.strftime("%H:%M:%S", time.localtime(item.timestamp))
        prefix = f"[{ts}]【{item.stage}】{item.label}"
        try:
            # 打印仅作调试；stdout 编码不支持中文时不得抛异常拖垮服务
            if item.is_error:
                print(f"\033[31m{prefix} 异常：{item.error_msg}\033[0m")
            else:
                print(f"\033[32m{prefix}\033[0m")
                if item.content:
                    print(f"  详情：{item.content}\n")
        except UnicodeEncodeError:
            # 输出编码无法表示字符时降级：仅保证不崩溃，完整日志以 backend.log 为准
            pass
        except Exception:
            pass

    def clear_trace(self):
        self.current_trace = []
        self.version += 1

    def get_all_trace(self) -> List[dict]:
        return [asdict(item) for item in self.current_trace]

    def get_latest_trace(self) -> Optional[dict]:
        if not self.current_trace:
            return None
        return asdict(self.current_trace[-1])

    def to_snapshot(self) -> dict:
        """可序列化快照（含版本号），便于 SSE 端判断是否需要重置游标。"""
        return {"version": self.version, "logs": self.get_all_trace()}

# 全局唯一追踪器实例
# 默认关闭控制台直出（日志经 SSE /trace/stream 在网页查看，避免服务日志膨胀）；
# 终端调试需要时可在入口显式 GLOBAL_TRACKER.enable_console_print = True
GLOBAL_TRACKER = TraceTracker(False)