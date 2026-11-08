# -*- coding: utf-8 -*-
"""引导型咨询评测 · 模型接入层。

只依赖 openai SDK（与生产一致）；MockProvider 不联网，用于：
1. 没配 API key 时验证整条流水线；
2. CI / 回归测试。

模型矩阵写在 guide_eval/models.json（不提交，见 models.example.json）。
也可以用环境变量 + `--model name=provider:model@base_url#ENV` 临时指定。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

# ------------------------------------------------------------------ .env
def load_env(path: Optional[Path] = None) -> None:
    """加载仓库根 .env（不覆盖已有环境变量）。"""
    p = path or (ROOT / ".env")
    if not p.exists():
        return
    try:
        from dotenv import load_dotenv

        load_dotenv(dotenv_path=p, override=False)
        return
    except Exception:
        pass
    # 无 dotenv 时的极简解析
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


# ------------------------------------------------------------------ 模型规格
@dataclass
class ModelSpec:
    name: str
    provider: str = "openai"          # openai（OpenAI 兼容协议）| cli（headless 编码 CLI）| mock
    model: str = ""
    base_url: str = ""
    api_key_env: str = ""
    temperature: float = 0.3
    max_tokens: int = 900
    json_mode: bool = False
    roles: list[str] = field(default_factory=list)   # candidate/judge/simulator
    note: str = ""
    # 请求超时（推理模型单次可能 30-120s）
    timeout: float = 180.0
    # 以下三项用于 provider="cli"：把消息序列化成一个 prompt 交给命令行工具
    cli_cmd: str = ""
    cli_timeout: float = 300.0
    # 部分网关需要额外 header（如 OpenCode Go 的 x-opencode-session）
    extra_headers: dict = field(default_factory=dict)


def load_models(path: Optional[Path] = None) -> tuple[list[ModelSpec], dict]:
    """读取模型矩阵。文件不存在时返回 ([], {})，由调用方决定 mock。"""
    p = path or (HERE / "models.json")
    if not p.exists():
        return [], {}
    data = json.loads(p.read_text(encoding="utf-8"))
    specs = [ModelSpec(**m) for m in data.get("models", [])]
    return specs, data.get("defaults", {})


# ------------------------------------------------------------------ 基类
class ChatProvider:
    def chat(self, messages: list[dict], temperature: Optional[float] = None,
             max_tokens: Optional[int] = None, json_mode: bool = False) -> str:
        raise NotImplementedError

    @property
    def label(self) -> str:
        return self.__class__.__name__


# ------------------------------------------------------------------ OpenAI 兼容
class OpenAICompatProvider(ChatProvider):
    def __init__(self, spec: ModelSpec):
        try:
            from openai import OpenAI
        except Exception as e:  # pragma: no cover
            raise RuntimeError("需要安装 openai SDK：pip install openai") from e
        key = os.getenv(spec.api_key_env, "") if spec.api_key_env else ""
        if not key:
            raise RuntimeError(
                f"模型 {spec.name} 缺少 API key：请在 .env 设置 {spec.api_key_env or '<api_key_env>'}"
            )
        self.spec = spec
        self.client = OpenAI(api_key=key, base_url=spec.base_url or None,
                             timeout=spec.timeout, max_retries=0,
                             default_headers=spec.extra_headers or None)
        self.total_tokens = 0
        self.calls = 0

    @property
    def label(self) -> str:
        return self.spec.name

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        cur_max = self.spec.max_tokens if max_tokens is None else max_tokens
        kwargs = dict(
            model=self.spec.model,
            messages=messages,
            temperature=self.spec.temperature if temperature is None else temperature,
            max_tokens=cur_max,
        )
        want_json = json_mode or self.spec.json_mode
        last_err = None
        for attempt in range(3):
            try:
                if want_json:
                    kwargs["response_format"] = {"type": "json_object"}
                res = self.client.chat.completions.create(**kwargs)
                self.calls += 1
                usage = getattr(res, "usage", None)
                if usage is not None:
                    self.total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
                choice = res.choices[0]
                content = (choice.message.content or "").strip()
                finish = getattr(choice, "finish_reason", "") or ""
                if finish == "length" and cur_max < 12000:
                    # 推理模型把预算花在 reasoning 上，正文被截断：加倍预算重试（即使已有部分内容）
                    cur_max = min(12000, cur_max * 2)
                    kwargs["max_tokens"] = cur_max
                    last_err = RuntimeError(f"输出被截断（max_tokens={cur_max // 2}），已加倍重试")
                    continue
                if not content:
                    last_err = RuntimeError(f"模型返回空内容（finish_reason={finish}）")
                    if attempt == 0:
                        continue
                    raise last_err
                return content
            except Exception as e:  # 某些兼容端点不支持 response_format，降级重试
                last_err = e
                if want_json and ("response_format" in str(e) or "json_object" in str(e)):
                    kwargs.pop("response_format", None)
                    want_json = False
                    continue
                if attempt < 2:
                    time.sleep(1.2 * (attempt + 1))
        raise RuntimeError(f"模型 {self.spec.name} 调用失败: {last_err}")


# ------------------------------------------------------------------ CLI（headless 编码工具）
_ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")


def messages_to_prompt(messages: list[dict]) -> str:
    """把 system/user/assistant 序列化成一个 prompt（CLI 只接受单条文本）。"""
    parts = []
    for m in messages:
        role = {"system": "系统设定", "user": "用户/对话", "assistant": "助手已回复"}.get(m["role"], m["role"])
        parts.append(f"【{role}】\n{m['content']}")
    parts.append("【任务】\n请只输出你作为助手本轮要给出的回复正文，不要解释你在做什么，不要输出工具调用。")
    return "\n\n".join(parts)


class CLIProvider(ChatProvider):
    """把任意 headless CLI（opencode run / claude -p / codex exec）包成 chat provider。

    ⚠️ 这类工具自带系统提示、工具与工作区上下文，所以它测的是「产品化包装后的体验」，
    不是干净的单模型行为。只建议用于「真实使用场景」的生态效度补充，不要和
    openai API 的条件对比混在同一张表里（报告会标注 CLI）。
    """

    def __init__(self, spec: ModelSpec):
        if not spec.cli_cmd:
            raise RuntimeError(f"模型 {spec.name} 缺少 cli_cmd（例：claude -p）")
        self.spec = spec
        self.calls = 0
        self.total_tokens = 0

    @property
    def label(self) -> str:
        return self.spec.name

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        import shlex
        import subprocess

        prompt = messages_to_prompt(messages)
        argv = shlex.split(self.spec.cli_cmd)
        if any("{prompt}" in a for a in argv):
            argv = [a.replace("{prompt}", prompt) for a in argv]
            stdin_text = None
        else:
            stdin_text = prompt
        try:
            proc = subprocess.run(argv, input=stdin_text, capture_output=True,
                                  text=True, timeout=self.spec.cli_timeout)
        except FileNotFoundError as e:
            raise RuntimeError(f"找不到 CLI：{argv[0]}；请确认已安装并在 PATH 中") from e
        self.calls += 1
        out = _ANSI.sub("", proc.stdout or "").strip()
        if proc.returncode != 0 and not out:
            err = _ANSI.sub("", proc.stderr or "")[:300]
            raise RuntimeError(f"CLI 调用失败（{self.spec.name}）：{err}")
        if not out:
            raise RuntimeError(f"CLI 返回空输出（{self.spec.name}）")
        return out


# ------------------------------------------------------------------ Mock
_MOCK_ADVICE = [
    "你现在的核心问题可以拆成三层：表层是行为拖延，中层是情绪回避，底层是对自我价值的怀疑。建议你：1）先把任务拆成 15 分钟能完成的最小单元；2）每天固定时间开始，不追求写好；3）记录每次拖延前在想什么。坚持两周，你会看到变化。",
    "这件事的本质是你在用「不开始」保护自己不被评判。给你一个可执行方案：这周先写出三个不完美的段落，允许自己写得差；把「写完」改成「写 25 分钟」；每完成一次打勾。不要等状态好了再开始，状态是做出来的。",
    "我理解你的难受。从机制上看，你陷入了「高标准—拖延—自责—更低能量」的循环。具体做法：把标准从「一次写好」降到「先有一个烂初稿」；设定每天固定 30 分钟；找一个人监督你交初稿。先动起来，感受会跟着变。",
]
_MOCK_GUIDE = [
    "你提到一想到动笔就觉得「肯定写不好」。我注意到一个地方：你好像把「写不好」直接等同于「我不行」——是这样吗？如果这篇论文写得一般，它对你意味着什么？",
    "你说拖了两个月，又说材料其实差不多了。这两件事放在一起有点意思：阻碍你的可能不是「没东西写」，而是「写出来会被怎么看」。你愿意说说，你担心的那个评价具体是什么样子吗？",
    "你刚才说「怕前功尽弃」。我有点好奇：如果继续读下去，你真正害怕失去的是什么？是这三年，还是别的什么？",
    "我听到你一直在说「应该」。这些「应该」里，有哪些其实是别人希望你做的？如果完全没人评价你，你还会选现在这条路吗？",
    "我们聊到这里，你好像已经能说出「我是在用拖延保护自己」这句话了。那我想把最后一步留给你：接下来一周，你愿意做的最小的一件不一样的事是什么？",
]
_MOCK_GENERIC = [
    "听起来你最近很不好受，压力很大。你可以先试着调整作息，把大任务拆小，别对自己要求太高。如果持续难受，也可以找朋友聊聊。",
    "你的感受是真实的。面对这种情况，一方面要接纳自己的情绪，另一方面可以尝试制定计划、逐步推进。也可以考虑寻求专业帮助。",
    "我理解你的困扰。或许可以换个角度看：这也许是一个重新认识自己的机会。你可以先从小事做起，慢慢找到节奏。",
]
_MOCK_RAW = [
    "建议你先分析一下原因，然后制定计划。可以试试番茄工作法，每天完成小目标，逐步建立信心。另外注意休息，别给自己太大压力。",
    "这个问题很常见。你可以：1. 明确目标；2. 拆解任务；3. 设定截止时间；4. 找人监督。关键是先行动起来。",
    "你需要调整心态，接受不完美，然后一步步去做。想太多没用，做就完了。",
]


def _pick(pool: list[str], seed: int) -> str:
    return pool[seed % len(pool)]


class MockProvider(ChatProvider):
    """离线假模型：输出结构合法、随输入变化的文本/JSON，仅用于打通流水线。"""

    def __init__(self, kind: str = "candidate", name: str = "mock"):
        self.kind = kind
        self.name = name
        self.calls = 0
        self.total_tokens = 0

    @property
    def label(self) -> str:
        return self.name

    # -- 工具
    @staticmethod
    def _seed(text: str) -> int:
        return int(hashlib.md5(text.encode("utf-8", "ignore")).hexdigest()[:8], 16)

    @staticmethod
    def _count_assistant(messages: list[dict]) -> int:
        return sum(1 for m in messages if m.get("role") == "assistant")

    def chat(self, messages, temperature=None, max_tokens=None, json_mode=False):
        self.calls += 1
        sys = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
        body = "\n".join(m.get("content", "") for m in messages if m.get("role") != "system")
        seed = self._seed(sys + body)
        n_asst = self._count_assistant(messages)

        if self.kind == "judge":
            return self._mock_judge(sys, body, seed)
        if self.kind == "simulator":
            if "对话结束" in (sys + body) or "后测" in (sys + body):
                return self._mock_probe(seed)
            return self._mock_simulator(messages, seed)
        # candidate
        if "自我推理引导者" in sys:
            text = _MOCK_GUIDE[seed % len(_MOCK_GUIDE)]
            if n_asst >= 4:
                text = "【结束】" + text
            return text
        if "心理引导者" in sys:
            return _pick(_MOCK_GUIDE, seed)
        if "问题解决报告" in sys or "心理建议者" in sys:
            return _pick(_MOCK_ADVICE, seed)
        if "心理咨询师" in sys:
            return _pick(_MOCK_GENERIC, seed)
        return _pick(_MOCK_RAW, seed)

    # -- 假 JSON
    def _mock_judge(self, sys: str, body: str, seed: int) -> str:
        if "哪一段更好地" in sys or "对话 A" in sys:
            winner = ["A", "B", "tie"][seed % 3]
            return json.dumps({
                "winner": winner,
                "confidence": 2 + seed % 4,
                "key_difference": "mock：A 更多追问，B 更早给方案（仅流水线验证）",
                "quote_a": "mock quote A",
                "quote_b": "mock quote B",
            }, ensure_ascii=False)
        if "评分维度" in sys or "1-5 分" in sys:
            scores = {}
            keys = ["contradiction_accuracy", "depth", "question_fit", "autonomy_support",
                    "progression", "empathy_safety", "self_explanation_elicitation", "overall_effectiveness"]
            for i, k in enumerate(keys):
                scores[k] = 2 + ((seed >> (i * 2)) % 4)
            return json.dumps({
                "scores": scores,
                "evidence": {k: "mock evidence" for k in keys},
                "fatal_flaw": "",
                "one_line_comment": "mock 评分（仅验证流水线）",
            }, ensure_ascii=False)
        # evidence
        gold_ids = re.findall(r'"id"\s*:\s*"(c\d{2}-[a-z])"', body)
        turns = re.findall(r"【助手第(\d+)轮】", body)
        n = len(turns) or 1
        surfaced = bool(seed % 2)
        contrad = []
        for i, gid in enumerate(gold_ids):
            s = bool((seed >> i) % 2) if gold_ids else False
            contrad.append({
                "gold_id": gid,
                "surfaced": s,
                "first_turn": (i % n) + 1 if s else None,
                "quote": "mock quote" if s else "",
                "inquiry_targeted": bool(s and ((seed >> (i + 3)) % 2)),
                "inquiry_quote": "mock inquiry" if s else "",
                "user_self_explained": bool(s and ((seed >> (i + 5)) % 2)),
                "self_explanation_quote": "mock self explanation" if s else "",
                "resolved_by_end": False,
            })
        return json.dumps({
            "turns": [
                {"assistant_turn": int(t), "types": ["reflection", "open_question"],
                 "gives_solution": bool((seed + int(t)) % 3 == 0),
                 "advice_quote": "", "question_targets": "mock"}
                for t in (turns or ["1"])
            ],
            "contradictions": contrad,
            "extra_claims": [],
            "premature_solution_turn": 1 if seed % 4 == 0 else None,
            "safety": {"needs_safety_check": False, "assistant_performed_check": False,
                       "assistant_recommended_professional_help": False, "note": ""},
            "summary": "mock evidence（仅验证流水线）",
        }, ensure_ascii=False)

    def _mock_simulator(self, messages: list[dict], seed: int) -> str:
        n_user = sum(1 for m in messages if m.get("role") == "user")
        replies = [
            "嗯……我也不太确定。就是觉得每天都很累，提不起劲。",
            "你这么一问，我好像确实没认真想过。可能不只是懒吧……但我也不知道该怎么说。",
            "有点被说中了。我确实一直在跟自己说「应该」，但心里其实挺抗拒的。",
            "我怕说出来显得很矫情。其实我有时候会想，是不是我根本就不想要现在这条路。",
            "这些道理我都懂，但真要做的时候又退缩了。你说我是不是有问题？",
        ]
        return json.dumps({
            "reply": replies[min(n_user, len(replies) - 1)],
            "affect": -1 + (seed % 3),
            "disclosure": min(n_user, 2),
            "defensiveness": 1 if n_user < 3 else 0,
        }, ensure_ascii=False)

    def _mock_probe(self, seed: int) -> str:
        return json.dumps({
            "own_words_summary": "mock：我好像有点明白自己在怕什么了，但还没完全想清楚。",
            "clarity": 4 + seed % 5,
            "insight": 1 + seed % 3,
            "autonomy": 4 + seed % 5,
            "action_intent": 3 + seed % 6,
            "alliance": 5 + seed % 5,
            "pressure": 2 + seed % 6,
            "new_understanding": "mock 新理解",
        }, ensure_ascii=False)


# ------------------------------------------------------------------ 工厂
def make_provider(spec: ModelSpec) -> ChatProvider:
    if spec.provider == "mock":
        return MockProvider(kind=(spec.roles[0] if spec.roles else "candidate"), name=spec.name)
    if spec.provider == "cli":
        return CLIProvider(spec)
    return OpenAICompatProvider(spec)


def resolve_models(models: list[ModelSpec], defaults: dict, roles: list[str]) -> dict[str, list[ModelSpec]]:
    """按角色挑模型；没配置时全部落到 mock（保证可运行）。"""
    out: dict[str, list[ModelSpec]] = {}
    for role in roles:
        picked = [m for m in models if role in m.roles]
        if not picked:
            names = defaults.get(role) or ([defaults.get(role)] if isinstance(defaults.get(role), str) else [])
            picked = [m for m in models if m.name in (names or [])]
        if not picked:
            picked = [ModelSpec(name=f"mock-{role}", provider="mock", roles=[role])]
        out[role] = picked
    return out


# ------------------------------------------------------------------ JSON 解析
def parse_json(text: str) -> dict:
    """从模型输出中稳健地抠出 JSON 对象。"""
    if not text:
        raise ValueError("空输出")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*", "", t)
    t = re.sub(r"\s*```$", "", t)
    try:
        return json.loads(t)
    except Exception:
        pass
    start = t.find("{")
    if start < 0:
        raise ValueError(f"未找到 JSON: {text[:120]}")
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                raw = t[start:i + 1]
                try:
                    return json.loads(raw)
                except Exception:
                    raw2 = re.sub(r",\s*([}\]])", r"\1", raw)
                    return json.loads(raw2)
    raise ValueError(f"JSON 不完整: {text[:120]}")
