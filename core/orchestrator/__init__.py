# -*- coding: utf-8 -*-
"""编排层：Planner -> Executor -> Evaluator 三段式骨架（+ Budget / Fallback）。

- Planner 收编原 _is_counseling 二分类，输出结构化多步 Plan；
- Executor 按 Plan 步骤驱动（会话初始化/记忆检索/Agent 调用/历史落库/引导链）；
- Evaluator 把 Agent 输出解析为结构化 ToolResult，并评估 success/failure；
- Budget 护栏超限 / direct 步骤异常 → Fallback 直接路由保底；
- 引导问答链编排位于 plans/guided_plan.py。
阶段 4 将放开 flexible 步骤的局部 ReAct 循环、按需检索门控与 CRAG 补救。
"""
from core.orchestrator.plan import (
    Step, Plan, ToolResult,
    ACT_GUIDED, ACT_ENSURE_SESSION, ACT_RUN_AGENT, ACT_PERSIST_HISTORY,
)
from core.orchestrator.evaluator import parse_tool_result, evaluate_status
from core.orchestrator.planner import (
    classify_and_plan, classify_counseling, plan_from_mode, plan_from_intent,
)
from core.orchestrator.executor import execute as execute_plan
from core.orchestrator.budget import Budget, BudgetExceeded
from core.orchestrator.fallback import run_direct_fallback
from core.orchestrator.plans import guided_reasoning

__all__ = [
    "Step", "Plan", "ToolResult",
    "ACT_GUIDED", "ACT_ENSURE_SESSION", "ACT_RUN_AGENT", "ACT_PERSIST_HISTORY",
    "parse_tool_result", "evaluate_status",
    "classify_and_plan", "classify_counseling", "plan_from_mode", "plan_from_intent",
    "execute_plan", "Budget", "BudgetExceeded", "run_direct_fallback",
    "guided_reasoning",
]
