# -*- coding: utf-8 -*-
"""编排层数据结构：计划步骤 / 整体计划 / 工具结构化结果。"""
from dataclasses import dataclass, field
from typing import List, Optional, Set


# ---------------- Step action 枚举（字符串常量，便于序列化与测试） ----------------

# 引导咨询：走 guided_reasoning 链（含【结束】后报告）
ACT_GUIDED = "run_guided"
# 心理咨询：新会话初始化 + 相似记忆检索（仅新会话首次触发）
ACT_ENSURE_SESSION = "ensure_session"
# 调用路由 AgentExecutor（LLM 自主工具调用，ReAct 内层）
ACT_RUN_AGENT = "run_agent"
# 心理咨询回复落库：写 full_chat_history（仅输出确认为心理咨询回复时）
ACT_PERSIST_HISTORY = "persist_history"


@dataclass
class Step:
    """单个执行步骤。

    阶段 3-B：步骤由 Planner 依据会话模式 + 小模型分类确定性生成（单分支多步）；
    阶段 4 起部分步骤将标记为 flexible，允许 Executor 局部 ReAct 循环。
    """
    action: str
    tool_hints: List[str] = field(default_factory=list)
    reason: str = ""


@dataclass
class Plan:
    """一次请求的执行计划。Planner 产出、Executor 顺序执行。"""
    steps: List[Step] = field(default_factory=list)

    @property
    def primary(self) -> Optional[Step]:
        return self.steps[0] if self.steps else None

    def actions(self) -> List[str]:
        return [s.action for s in self.steps]


@dataclass
class ToolResult:
    """工具/编排的结构化结果：替代散落在 agent.py 的字符串哨兵解析。"""
    tool_name: str            # psychological_consult / guided_reason / meta_filter / ... / other
    reply: str               # 给用户的纯净文本（已剥掉哨兵前缀）
    raw_output: str          # 原始输出（含拼接还原，供前端调试/落库）
    referenced_doc_ids: Set[str] = field(default_factory=set)
    error: str = ""
