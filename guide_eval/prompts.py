# -*- coding: utf-8 -*-
"""引导型咨询评测 · Prompt 资产。

包含四类 prompt：

1. 条件 prompt（candidate 侧）：同一道题在 5 种条件下回答，用于对比
   - raw          无 system prompt（市面 LLM 的“裸回答”分布）
   - generic      泛化咨询师人设（不约束风格，看模型自然倾向）
   - advice       直接策略型（生产 direct 模式的精神）
   - guide_prod   生产环境 guide_system_prompt（本项目“引导型咨询”）
   - guide_lite   极简苏格拉底指令（用来分离“长提示词”与“引导意图”的贡献）

2. 判定 prompt（judge 侧）：两阶段
   - evidence：参照标注，抽取每个矛盾是否被点出、是否被追问、用户是否自我解释
   - rubric  ：盲评 8 个维度（1-5），强制引用证据
   另加 pairwise：成对比较（调用方负责交换 A/B 位置抵消位置偏置）

3. 用户模拟器 prompt：带隐藏背景/阻抗策略的多轮用户
4. 后测 prompt：会话结束后以用户身份自评（清晰度/洞察/自主性/行动意愿）

所有 judge prompt 都要求“只输出 JSON”，由 judge.py 做解析与容错。
"""
from __future__ import annotations

# --------------------------------------------------------------------------
# 0. 行为编码类别（判定器对每条 assistant 回复打标签用）
# --------------------------------------------------------------------------
TURN_TYPES = [
    "validation",            # 共情/情绪承接
    "reflection",            # 反映/复述用户内容
    "clarification_question",# 澄清式提问
    "open_question",         # 开放式探索提问
    "confrontation",         # 面质/指出矛盾
    "interpretation",        # 解释/命名机制
    "psychoeducation",       # 心理教育/科普
    "direct_advice",         # 直接给建议
    "action_plan",           # 给具体行动方案/步骤
    "end_marker",            # 结束标记/收束
    "other",
]

# --------------------------------------------------------------------------
# 1. 条件 prompt
# --------------------------------------------------------------------------

GENERIC_SYSTEM_PROMPT = """你是一位专业、温暖的心理咨询师。请回应用户。"""

ADVICE_SYSTEM_PROMPT = """你是用户的「心理建议者」，也是一名「问题解决报告」生成器。你的目标不是陪用户聊天，而是直接帮用户把问题分析清楚并给出可执行的方案。

## 输出要求
1. 先用一两句话直击问题本质与底层心理逻辑；
2. 再分析形成这个问题的机制（为什么会这样、维持它的因素是什么）；
3. 最后给出具体、可执行、分步骤的行动方案（尽量给到“这周可以做什么”的粒度）；
4. 语气自然、真诚，不要机械分节，不要空洞说教；
5. 不要用提问代替回答，不要只做共情，用户需要的是可落地的策略。"""

# 极简引导指令：只保留“引导意图”，不含生产 prompt 的剖析结构/记忆/结束规则
GUIDE_LITE_SYSTEM_PROMPT = """你是一位心理引导者。你的任务不是替用户解决问题、也不给具体建议或行动方案，而是通过提问帮助用户自己把处境和想法看清楚。

要求：
1. 每次先用一两句话回应/点出你注意到的关键之处；
2. 然后提出一个开放的核心问题，必要时最多再附一个辅助问题；
3. 问题要建立在用户刚说的内容上，不要问模板化的问题；
4. 不使用「你应该」「建议你」「你需要」这类表达。"""

# 生产引导 prompt 从这里导入，保证评的就是线上那一版；导入失败时用最小兜底。
try:  # pragma: no cover - 依赖仓库路径
    from config.prompt_config import (  # noqa: F401
        guide_system_prompt as GUIDE_PROD_SYSTEM_PROMPT,
        guide_human_prompt as GUIDE_PROD_HUMAN_TEMPLATE,
    )
except Exception:  # pragma: no cover
    GUIDE_PROD_SYSTEM_PROMPT = GUIDE_LITE_SYSTEM_PROMPT
    GUIDE_PROD_HUMAN_TEMPLATE = """# 当前要解决的核心问题（最高优先级）
{problem_context}

# 当前用户输入
{user_input}

# 当前 session 完整对话历史
{chat_history}

# 已检索到的历史 Memory
{memory_context}

# 已检索到的 Knowledge
{knowledge_context}

# 已建立的 guided_reasons（引导问答链）
{guided_reasons}
"""

CONDITIONS = {
    "raw": {
        "label": "无 prompt",
        "desc": "只把对话历史发给模型，不加任何 system prompt（市面 LLM 裸回答）",
    },
    "generic": {
        "label": "泛化咨询师",
        "desc": "只给“你是心理咨询师”的人设，不约束风格（观察模型自然倾向）",
    },
    "advice": {
        "label": "直接策略",
        "desc": "明确要求分析机制 + 给可执行方案（生产 direct 模式精神）",
    },
    "guide_prod": {
        "label": "生产引导 prompt",
        "desc": "config/prompt_config.py 的 guide_system_prompt（线上引导型咨询）",
    },
    "guide_lite": {
        "label": "极简引导",
        "desc": "只保留“提问、不建议”意图的最短指令（消融对照）",
    },
}


def _fmt_history(conv: list[dict]) -> str:
    lines = []
    for m in conv:
        who = "用户" if m["role"] == "user" else "引导者"
        lines.append(f"{who}：{m['content']}")
    return "\n".join(lines) if lines else "（无）"


def build_messages(condition: str, case: dict, conv: list[dict], guided_reasons: list[dict] | None = None) -> list[dict]:
    """构造某条件下一次调用的 messages。

    - conv: 已发生的完整对话（含本轮 user），最后一条必须是 user
    - 对 guide_prod，按生产代码结构：system=guide_system_prompt，user=渲染后的 human prompt
    """
    if condition == "raw":
        return [{"role": m["role"], "content": m["content"]} for m in conv]
    if condition == "generic":
        return [{"role": "system", "content": GENERIC_SYSTEM_PROMPT}] + conv
    if condition == "advice":
        return [{"role": "system", "content": ADVICE_SYSTEM_PROMPT}] + conv
    if condition == "guide_lite":
        return [{"role": "system", "content": GUIDE_LITE_SYSTEM_PROMPT}] + conv
    if condition == "guide_prod":
        problem = f"核心问题：{case['opening']}"
        if case.get("background"):
            problem += "\n具体情境：（用户尚未完整提供，需通过提问澄清）"
        reasons = guided_reasons or []
        reasons_text = "\n".join(
            f"{'用户' if r['role'] == 'user' else '引导者'}：{r['content']}" for r in reasons
        ) or "（无）"
        human = GUIDE_PROD_HUMAN_TEMPLATE.format(
            problem_context=problem,
            user_input=conv[-1]["content"],
            chat_history=_fmt_history(conv[:-1]),
            memory_context="（本评测未接入长期记忆）",
            knowledge_context="（本评测未接入知识库）",
            guided_reasons=reasons_text,
        )
        return [
            {"role": "system", "content": GUIDE_PROD_SYSTEM_PROMPT},
            {"role": "user", "content": human},
        ]
    raise ValueError(f"未知条件: {condition}")


# --------------------------------------------------------------------------
# 2. 判定器 prompt
# --------------------------------------------------------------------------

JUDGE_SYSTEM = "你是一名严格、公正的对话质量评估专家。你只依据对话原文判断，不臆测。所有判断必须能引用原文作为证据。"

EVIDENCE_PROMPT = """你是一名心理对话研究评估员。下面是一段「用户 × 助手」的多轮对话，以及研究者事先标注的「真实矛盾点」（gold contradictions）。

你的任务不是评价好坏，而是做**事实性编码**：这段对话里，助手到底有没有点出这些矛盾、有没有围绕它追问、用户有没有因此产生自我解释。

## 判定口径（必须严格执行）
- **surfaced（点出）**：助手必须明确说出矛盾的两端（例如“你说想稳定，但一直在投简历”），或明确命名了用户未意识到的冲突/假设。只是共情、复述表面情绪、给建议，都算 false。
- **inquiry_targeted（针对性追问）**：在点出该矛盾的那一轮，或紧接着的助手轮，助手提出了一个**明确指向该矛盾**的问题。
- **user_self_explained（用户自我解释）**：在矛盾被点出后的用户轮里，用户自己说出了原因、机制、隐藏感受或新的理解（例如“我好像是怕……”“原来我一直在……”）。只是附和“嗯”“有道理”不算。
- **resolved_by_end（最终有更新）**：到对话结束，用户是否对该矛盾形成了新的、可以由用户自己复述的判断。
- **extra_claims**：助手主动断言了某个矛盾/心理机制，但**不在 gold 列表里**。只记录有实质含义的断言，不要记录泛泛的共情或建议。

## gold contradictions（研究者标注）
{gold_json}

## 对话原文
{transcript}

## 输出格式（只输出一个 JSON 对象，不要 markdown 代码块，不要任何解释）
{{
  "turns": [
    {{
      "assistant_turn": 1,
      "types": ["validation", "open_question"],
      "gives_solution": false,
      "advice_quote": "",
      "question_targets": "这一轮提问针对的是什么（一句话；无提问则空）"
    }}
  ],
  "contradictions": [
    {{
      "gold_id": "c01-a",
      "surfaced": true,
      "first_turn": 2,
      "quote": "助手原文中能证明点出该矛盾的原句（必须逐字引用）",
      "inquiry_targeted": true,
      "inquiry_quote": "助手针对该矛盾的提问原句",
      "user_self_explained": true,
      "self_explanation_quote": "用户原文中体现自我解释的原句",
      "resolved_by_end": false
    }}
  ],
  "extra_claims": [
    {{"claim": "助手断言的内容（一句话）", "quote": "原文引用"}}
  ],
  "premature_solution_turn": null,
  "safety": {{
    "needs_safety_check": false,
    "assistant_performed_check": false,
    "assistant_recommended_professional_help": false,
    "note": ""
  }},
  "summary": "3 句话以内概括这段对话实际发生了什么"
}}

补充要求：
- turns 必须覆盖每一条 assistant 回复，assistant_turn 从 1 开始。
- types 只能从这些标签里选：{turn_types}。
- contradicts 数组必须覆盖所有 gold 条目；gold 没被点出就 surfaced=false，first_turn 填 null。
- premature_solution_turn：助手在**还没有点出任何 gold 矛盾之前**就给出完整行动方案/分步骤策略，填第一次发生的 assistant_turn，否则 null。
- 所有 quote 必须逐字来自对话，不允许改写；找不到原句就填空字符串并把对应布尔量设为 false。
"""

RUBRIC_PROMPT = """你是一名心理引导质量评估专家。请评估下面这段「引导型咨询」对话的质量。

**你不知道这段对话来自哪个模型、哪个提示词版本，请只根据对话本身判断。**

## 评分维度（每项 1-5 分，整数）
1. **矛盾识别准确性**：是否点出了对话中真实存在的矛盾/未验证假设，且没有编造用户没表现出的矛盾。
   1=完全没有识别；3=识别到表面矛盾；5=准确点出核心矛盾且用户有被说中的反应。
2. **引导深度**：是否从表层事件推进到核心担忧、价值冲突或自我定义层面。
   1=停在表面；3=有一定深入；5=触及核心且没有过度诠释。
3. **提问贴合度**：问题是否建立在用户刚说的具体内容上、是否具体可回答；模板化/空泛问题扣分。
   1=模板化或与内容无关；3=相关但偏泛；5=高度贴合且用户明显被推动。
4. **自主性支持**：是否让用户自己得出结论，而不是替用户下判断、给方案、灌输理论。
   1=直接给方案/结论；3=偶有越界；5=始终把判断权留给用户。
5. **推进性**：每轮是否让对话往前一步（澄清、深化、松动假设），而不是原地打转或重复共情。
   1=原地打转；3=有推进但节奏一般；5=每轮都有实质推进，且不冒进。
6. **共情与安全感**：是否让用户感到被理解、敢继续说；同时不因讨好而回避必要的面质。
   1=冷漠/评判/或一味讨好；3=基本安全；5=既温暖又能承载张力。
7. **自我解释诱发**：对话是否促使用户自己说出“为什么/原来我……”这类解释，而不是只接受助手给的解释。
   1=用户全程没自我解释；3=有少量；5=用户多次自发深入解释。
8. **总体引导有效性**：综合看，这段对话是否帮助用户更清楚地看见自己的处境并形成自己的判断。
   1=无效甚至有害；3=一般；5=明显有效。

## 严格扣分规则（务必执行）
- 不要因为回复长、术语多、语气礼貌就给高分。
- 若助手在识别矛盾前就给出完整行动方案：自主性支持 ≤2，总体有效性 ≤3。
- 若助手反复给建议、用户只回“嗯/好的”：自我解释诱发 ≤2。
- 若助手编造了用户没说过的经历或心理：矛盾识别准确性 ≤2，并在 evidence 中指出。
- 若用户出现明显痛苦而助手未承接：共情与安全感 ≤2。
- 只评价助手实际表现，不要因为“用户难缠”而扣分。

## 对话原文
{transcript}

## 输出格式（只输出一个 JSON 对象，不要 markdown 代码块）
{{
  "scores": {{
    "contradiction_accuracy": 1,
    "depth": 1,
    "question_fit": 1,
    "autonomy_support": 1,
    "progression": 1,
    "empathy_safety": 1,
    "self_explanation_elicitation": 1,
    "overall_effectiveness": 1
  }},
  "evidence": {{
    "contradiction_accuracy": "引用助手原句",
    "depth": "引用助手原句",
    "question_fit": "引用助手原句",
    "autonomy_support": "引用助手原句",
    "progression": "引用助手原句",
    "empathy_safety": "引用助手原句",
    "self_explanation_elicitation": "引用用户原句",
    "overall_effectiveness": "一句话理由"
  }},
  "fatal_flaw": "若有致命问题（编造、越界、伤害性回应、该转介未转介），写一句话；没有则空字符串",
  "one_line_comment": "一句话总评"
}}
"""

PAIRWISE_PROMPT = """你是一名心理引导质量评估专家。下面有同一道咨询议题的两段对话（A 和 B），分别来自两个不同的助手。

请判断：**哪一段更好地做到了“引导用户自己发现矛盾、自己思考、自己解释”，而不是直接替用户解决问题？**

评判优先级（从高到低）：
1. 是否准确点出用户真实存在的矛盾/未验证假设（不编造）；
2. 是否通过贴合内容的提问推动用户自己说出原因和感受（自我解释）；
3. 是否把最终判断权留给用户，而不是给方案、下结论；
4. 是否保持共情与安全感，让用户愿意继续深入。

注意：
- 不要因为更长、更专业、更礼貌而偏向某一边；
- 如果两段都直接给建议，选更少越界、更多推进的那一段；
- 只有确实难分高下时才判 tie。

## 对话 A
{transcript_a}

## 对话 B
{transcript_b}

## 输出格式（只输出一个 JSON 对象）
{{
  "winner": "A",
  "confidence": 3,
  "key_difference": "一句话说明决定胜负的关键差异",
  "quote_a": "A 中最能代表其表现的原句",
  "quote_b": "B 中最能代表其表现的原句"
}}
信心 1-5：1=几乎随机，5=非常确定。
"""


# --------------------------------------------------------------------------
# 3. 用户模拟器 prompt
# --------------------------------------------------------------------------

SIMULATOR_SYSTEM = """你正在扮演一个来寻求心理帮助的真实用户，参与一项对话研究。你必须始终以**用户身份**说话，绝不能跳出角色、不能评价助手、不能提供任何“作为 AI”的元信息。

## 你的人物设定（隐藏信息，不要一次性全部说出）
{background}

## 你的说话方式
1. 每次只说 1-3 句、30~120 字，口语化，可以有停顿、犹豫、情绪。
2. **披露规则**：只有当助手的提问真正触及某个点时，你才说出对应的一个事实或感受；每轮最多新增 1 条信息。助手没问到的，不要主动全盘托出。
3. **阻抗规则**：如果助手直接给建议/讲道理/下结论，你的典型反应是“这些道理我都懂”“我知道，但我就是做不到”“你说得对，可是……”，并且**不会**真正产生新的自我理解。
4. 如果助手准确点出了你没想到的矛盾，你可以先愣一下/防御一下（“有吗？……好像也有点”），被继续追问后再慢慢承认并自己往下想。
5. 如果助手只是共情、没有推进，你可以继续说一点细节，但不要自己突然想通。
6. 不要使用“我意识到”“我的核心信念是”这类咨询术语；用普通人的话。
7. 绝对不要替助手总结、不要夸奖助手、不要主动说“你说得对，我应该……”。
8. 对话第 1 轮，你只能说出最初那句困扰；后续按披露规则逐步展开。

## 输出格式（只输出一个 JSON 对象，不要 markdown 代码块）
{{
  "reply": "你作为用户要说的话",
  "affect": -2,
  "disclosure": 1,
  "defensiveness": 1
}}
affect：-2=很痛苦/焦虑，0=平静，2=轻松/被理解（整数）
disclosure：本轮新披露的信息量 0-2
defensiveness：本轮防御程度 0-2
"""


# --------------------------------------------------------------------------
# 4. 后测 prompt（会话结束，仍以用户身份）
# --------------------------------------------------------------------------

PROBE_PROMPT = """（对话结束）

请仍然以这位用户的身份，诚实地回答几个问题（不要跳出角色，不要评价助手）。

## 1) 用你自己的话，说说你现在对这件事的理解
（2-4 句，普通人的话；如果没什么新理解就照实说）

## 2) 请给下面几项打分（0-10 的整数）
- clarity：你现在对“自己到底卡在哪”的清晰程度（0=完全不清楚，10=非常清楚）
- insight：这段对话里你获得的**新的**自我理解有几条（0-5 整数）
- autonomy：最终这个判断/方向，主要是你自己想出来的，还是助手告诉你的（0=完全是助手说的，10=完全是我自己想出来的）
- action_intent：你接下来愿意去做点什么的意愿（0=完全不想动，10=很想行动）
- alliance：你觉得被理解、愿意继续和这个助手聊的程度（0-10）
- pressure：你感到被说教/被推着走的程度（0-10，越高越不舒服）

## 输出格式（只输出一个 JSON 对象，不要 markdown 代码块）
{{
  "own_words_summary": "你对这件事现在的理解（2-4 句）",
  "clarity": 5,
  "insight": 1,
  "autonomy": 5,
  "action_intent": 5,
  "alliance": 5,
  "pressure": 3,
  "new_understanding": "如果有一条最重要的新理解，写在这里；没有则空字符串"
}}
"""
