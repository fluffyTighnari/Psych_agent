# -*- coding: utf-8 -*-
"""Budget：编排预算护栏。

阶段 3-B 先立结构（默认值宽松，确定性步骤链远低于上限）；
阶段 4 局部 ReAct 循环开启后，超限将触发 Fallback 回退保底链路。
"""
from dataclasses import dataclass


class BudgetExceeded(RuntimeError):
    """预算超限：由 Executor 捕获并走 Fallback。"""


@dataclass
class Budget:
    max_steps: int = 12          # 单次请求最大工具/编排步骤数
    max_llm_calls: int = 8      # 单次请求最大 LLM 调用次数（分类 + ReAct + 补救）
    steps_used: int = 0
    llm_calls_used: int = 0

    def can_take_step(self) -> bool:
        return self.steps_used < self.max_steps

    def record_step(self) -> None:
        if not self.can_take_step():
            raise BudgetExceeded(f"已达最大步骤数 {self.max_steps}")
        self.steps_used += 1

    def record_llm_call(self, n: int = 1) -> None:
        self.llm_calls_used += n
        if self.llm_calls_used > self.max_llm_calls:
            raise BudgetExceeded(f"已达最大 LLM 调用次数 {self.max_llm_calls}")
