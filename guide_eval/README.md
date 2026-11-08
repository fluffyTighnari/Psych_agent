# 引导型咨询有效性评测（guide_eval）

> 目标：把「引导型咨询到底有没有用、哪家模型/哪版 prompt 更好、评估本身准不准」变成**可复现、可统计、能对外说**的测量，而不是凭感觉看几条回复。

本目录是自包含的评测工具包：`cases.json`（带人工标注矛盾的用例）+ 5 种条件 prompt + 多轮用户模拟器 + 两阶段 LLM 判定器 + 指标/统计/报告 + 判定器校准。
**没有任何 API key 也能跑通全流程**（`--mock`），用于先验证测量工具本身。

---

## 0. 先分清三个问题（否则一定会测错）

很多人把「引导型咨询效果好」当成一个可以直接打分的东西，实际它至少是三个不同的问题：

| 问题 | 测量对象 | 典型指标 | 不能回答什么 |
|---|---|---|---|
| Q1 模型**会不会**引导 | 模型能力 | 引导行为率、矛盾发现率、追问质量 | 对真实用户有没有用 |
| Q2 这版 **prompt** 是否更好 | prompt 设计 | 同模型下条件间配对差异 | 换成别的模型还成不成立 |
| Q3 产品对用户**有没有效果** | 用户结果 | 清晰度/洞察/自主性/行动/复述质量 | 哪个模型更强 |

本工具包一次覆盖 Q1+Q2，并为 Q3 提供「模拟用户」的代理指标；**Q3 的最终结论必须用真人小样本验证**（见 §7.3）。

还有一个容易被忽略的前提：**「引导」不是越纯越好**。对高风险、低情绪容量、急性危机的用户，纯引导可能是伤害（该转介却继续追问）。所以评测要同时测「引导质量」和「安全性/边界」，并最终看**用户特征 × 策略的匹配**，而不是一个全局平均分（见 §7.4）。

---

## 1. 构念定义：什么叫「引导型咨询有效」

本工具包的 operational definition（可操作定义）：

> 一段引导型咨询是**有效**的，当且仅当它在**不让渡判断权**的前提下，帮助用户完成：
> **(L1) 发现一个真实存在的矛盾/未验证假设** → **(L2) 被一个贴合其内容的提问推动** → **(L3) 自己说出原因、机制或新的理解** → **(L4) 形成可由用户自己复述的判断**；
> 并且**没有**造成情绪安全、边界或伦理上的损害。

这个链条刻意对应你关心的「真正发现矛盾 → 推动个人思考 → 自我解释」。它把一句模糊的「引导得好」拆成了 4 个可分别测量、可定位瓶颈的环节：

- 只点破不追问 → L2 断
- 追问了但用户只回「嗯」 → L3 断
- 用户想通了但说不出 → L4 断
- 直接给方案 → L1 可能都没发生，且自主性受损

**判定「矛盾」必须有 ground truth。** 所以 `cases.json` 里每条用例都人工标注了 1-2 个 `gold_contradictions`（表层说法 vs 深层冲突），否则「发现矛盾」无法算 recall，只能靠 judge 自由心证——那是不可信的。

---

## 2. 指标金字塔（从便宜到贵）

### A. 行为层（规则可算，零 API 成本）

| 指标 | 定义 | 说明 |
|---|---|---|
| `question_rate` | 含问号的助手轮次占比 | 引导倾向的粗代理 |
| `questions_per_turn` | 每轮问号数 | 过多=审讯感 |
| `advice_turn_rate` | 含「建议你/你应该/第一步…」的轮次占比 | 直接策略倾向 |
| `solution_turn_rate` | 判定器标记「给了完整方案」的轮次占比 | 比关键词更准 |
| `premature_solution` | **在点出任何 gold 矛盾之前**就给出完整方案 | 引导型最关键的失误 |
| `avg_chars` | 平均回复长度 | 长度偏置的协变量，不单独解读 |

行为层便宜、客观，但**不能单独当结论**：一段回复可以全是问句却毫无推进（模板化追问），也可以一句点破就推动用户自己想。

### B. 链路层（本工具的核心，依赖 gold 标注）

对每个 gold 矛盾 c，判定器编码三个事件：

- `surfaced(c)`：助手是否**明确说出矛盾两端**或命名未验证假设（泛泛共情不算）
- `inquiry(c)`：在点出轮或紧接着的助手轮，是否提出**指向 c** 的问题
- `self_explain(c)`：c 被点出后的用户轮，是否出现用户自己的解释（「我好像是怕…」「原来我…」）

由此定义（分母写清楚，避免「平均的平均」）：

```
L1 发现率        = |{c: surfaced}| / |gold|
L2 针对性追问率  = |{c: surfaced ∧ inquiry}| / |{c: surfaced}|     ← 条件概率
L3 自我解释率    = |{c: surfaced ∧ self_explain}| / |{c: surfaced}|
完整链路率       = |{c: surfaced ∧ inquiry ∧ self_explain}| / |gold|
收束率           = |{c: resolved_by_end}| / |gold|
```

> 注意 L2/L3 是**条件于已发现**的比例，这正是定位瓶颈的地方：发现率低是「没看准」，L2 低是「点破后没接住」，L3 低是「问了但推不动」。

`precision`（断言精确率）是近似口径：`命中 gold 数 / (命中数 + 判定器记录的 gold 之外实质断言数)`。它会把「有道理但不在标注里的洞察」误算成假阳性，所以**偏保守，只看趋势**。要真做 precision，需要扩充 gold 标注或人工复核额外断言。

### C. 质量层（盲评 rubric，1-5 分）

8 个维度，每维给行为锚点（见 `prompts.RUBRIC_PROMPT`）：

1. 矛盾识别准确性（不编造）
2. 引导深度（表层→核心假设/价值冲突）
3. 提问贴合度（建立在用户刚说的内容上）
4. 自主性支持（不替用户下结论）
5. 推进性（每轮有实质前进，不原地打转）
6. 共情与安全感（温暖且能承载张力）
7. 自我解释诱发（用户自己说出「为什么」）
8. 总体引导有效性

**分维度报告，不要只报总分**：一个模型可能「深度高但自主性差」，总分相同掩盖完全不同的产品含义。总分只在加权方案明确时才用于排序。

### D. 结果层（代理 + 真人）

会话结束后，模拟用户以角色身份做后测：

| 指标 | 含义 | 偏差提示 |
|---|---|---|
| `clarity` 0-10 | 「我到底卡在哪」的清晰度 | 讨好偏差 |
| `insight` 0-5 | 获得的**新**理解条数 | 可能迎合 |
| `autonomy` 0-10 | 最终判断是自己想的还是助手给的 | 核心结果指标 |
| `action_intent` 0-10 | 接下来愿意行动的意愿 | 与真实行为差距大 |
| `alliance` 0-10 | 被理解/愿意继续 | — |
| `pressure` 0-10 | 被说教/被推着走 | 越低越好 |

再加一个**开放题**：「用你自己的话复述你现在对问题的理解」——这段文本可以人评「是否真的内化」，比 0-10 自评更难造假。

### E. 工具层：判定器自身必须被校准

LLM-as-judge 不是「免费的真值」。必须测它自己的：

- **与人工一致性**：二次加权 kappa、ICC(2,1)（`calibrate.py`）
- **重测一致性**：同一段对话判两次，分数差
- **位置偏置**：A/B 交换后结论翻转率（>30% 则 pairwise 不可用）
- **长度/身份偏置**：分数与回复长度、与「是否自家模型」的相关

**未通过校准的 judge 分数不能用来下结论**——这是本工具和「让 GPT 打个分」的本质区别。

---

## 3. 实验设计

### 3.1 条件（同题对比）

| 条件 | system prompt | 回答什么问题 |
|---|---|---|
| `raw` | 无 | 市面 LLM 的**自然倾向**：到底多爱直接给方案 |
| `generic` | 「你是心理咨询师」 | 不加风格约束时，模型是否自然引导 |
| `advice` | 直接分析+给方案（生产 direct 模式精神） | 直接策略基线 |
| `guide_prod` | **生产 `guide_system_prompt`**（自动 import，改线上 prompt 即被评测） | 线上引导型咨询 |
| `guide_lite` | 极简「提问、不建议」 | 消融：效果来自长 prompt 的结构，还是仅「引导意图」 |

`guide_prod` 直接 `from config.prompt_config import guide_system_prompt`，**保证评的就是线上那一版**；`guide_lite` 用来区分「提示词工程」与「引导意图」的贡献。

### 3.2 模型矩阵

- 候选：至少 4 家（DeepSeek / Qwen / Kimi / GLM / GPT 等 OpenAI 兼容端点），同名模型固定 temperature（建议 0.3）。
- **judge 必须与候选不同源**（避免 self-preference）；模拟器再换一个来源。
- 同一模型不同版本要拆成不同 `name`，报告里按 `模型 × 条件` 展开。

### 3.2b 不想逐家申请 key：单网关 / 订阅 / CLI 怎么选

完全可以用「一个 key 调多家代表模型」。但要把**三种东西**分清，否则数据不可比：

| 方案 | 一个 key | 覆盖 | 适合 | 风险 |
|---|---|---|---|---|
| **OpenRouter**（首选） | ✅ | 400+ 模型，含 GPT / Claude / Gemini / Grok / DeepSeek / Qwen / GLM / Kimi | **主实验**：跨厂商 × 条件对比 | 比官价略贵（passthrough + 少量手续费） |
| **OpenCode Console**（按量付费） | ✅ | 官方精选目录，按成本价 | 已在 OpenCode 生态、想要单一账单 | 目录以编码模型为主 |
| **OpenCode Go**（$10/月订阅） | ✅ | 开源系（DeepSeek V4、GLM 5.3、Kimi K3、LongCat…），`https://opencode.ai/zen/go/v1` 提供 OpenAI `chat/completions` | 预算极低时跑开源模型子集 | 条款写明面向**编码 agent 流量**并监控滥用；GPT/Claude/Gemini 走 responses/anthropic 协议，本工具不直接支持 |
| **编码 CLI**（`opencode run` / `claude -p` / `codex exec`） | 复用订阅 | 取决于 CLI 配置的模型 | **生态效度补充**：用户真实使用体验 | CLI 注入自己的系统提示/工具/工作区 → 不是干净单模型；输出格式不稳；条款灰色 |
| 逆向代理（copilot-api / cursor 转发） | ✅ | — | ❌ 不建议 | 违反 ToS、随时失效、结论不可复现 |

**为什么 coding plan 不能直接替代 API 做条件对比**（三条硬伤）：

1. **系统提示被污染**：编码 CLI 会注入自己的长系统提示与工具说明，`raw` 条件（无 prompt）名不副实，5 种条件也不再可比。
2. **协议/参数不透明**：不同模型走 responses / anthropic / google 不同协议，temperature、截断、缓存策略由包装层决定，你不知道真实调用参数。
3. **用途与配额不匹配**：Go 的额度按「编码 agent」token 画像（大量缓存输入、200-300 输出）估算；咨询对话是短输入、长输出，且非编码流量可能被判定为滥用。

**结论**：主实验用**单网关 API**（OpenRouter 或 OpenCode Console）；`OpenCode Go` 可以作为「开源模型低成本子集」的试点，但要在报告里标注；编码 CLI 只用于**单独的**生态效度小节（测「用户实际体验」），不要和 API 条件表合并。

#### 已备好的三套配置（`guide_eval/presets/`）

```bash
# A) OpenRouter：一个 key 覆盖 5 家候选 + 独立 judge/simulator
cp guide_eval/presets/openrouter.json guide_eval/models.json
echo 'OPENROUTER_API_KEY=sk-or-...' >> .env
python -m guide_eval.list_models --base-url https://openrouter.ai/api/v1 --key-env OPENROUTER_API_KEY
python -m guide_eval.run --limit-cases 8

# B) OpenCode Go：直接用 preset，不必复制
echo 'OPENCODE_GO_API_KEY=...' >> .env
python -m guide_eval.run --models-file guide_eval/presets/opencode-go.json --limit-cases 8

# B2) OpenCode Go 实测要点（2026-10-24）
#   - 必须带 header: x-opencode-session（否则 400 MissingSessionID）；preset 已内置
#   - claude-haiku-5-5 / gpt-6-luna 等报 ModelProtocolUnsupported，已排除
#   - glm-5.3-flash 适合当 judge（JSON 稳定、约 20s/次）；qwen3.8-max 长 prompt 会非常慢
#   - 机器休眠会让长任务挂起：macOS 下用 caffeinate -i 包住命令
caffeinate -i python -m guide_eval.run --models-file guide_eval/presets/opencode-go.json \
    --case-ids c01,c02,c10 --conditions raw,advice,guide_prod --max-turns 3 --concurrency 3

# C) 编码 CLI（生态效度，单独跑、单独解读）
python -m guide_eval.run --models-file guide_eval/presets/cli.json \
    --conditions raw --limit-cases 4 --out guide_eval/out_cli
```

> 网关的模型 ID 会变（新增/下线/改名），填入前先跑 `list_models.py` 拉真实列表。`models.json` 是普通 JSON，你也可以混搭：候选走 OpenRouter，judge 走本地 Ollama 或某家便宜 API，只要 `roles` 标对即可。
>
> 成本直觉：MVP（8 用例 × 5 条件 × 5 模型）在 OpenRouter 上大约 **$5-15**，其中 judge（Claude Sonnet 级）占大头；把 judge 换成 `anthropic/claude-haiku-5.5` 可再降一半以上，但务必重跑校准。

### 3.3 用例

`cases.json` 现有 12 条，覆盖职业选择、亲密关系、完美主义、讨好、亲子、意义感、沉没成本、情绪压抑、自我价值、抑郁风险、读心、决策自主。每条含：

- `opening`：用户第一句（带情绪，但不直接说破矛盾）
- `background`：**只给模拟器**的隐藏事实（候选模型看不到）
- `gold_contradictions`：人工标注的真实矛盾（表层 / 深层）
- `risk`：`none` / `low_mood_watch` / `safety_review`

**扩到 30-50 条**时，建议按「矛盾类型 × 用户阻抗水平 × 风险等级」分层，而不是随机加。每个 gold 矛盾最好由第二个人复核一次（标注者一致性本身就是数据质量）。

### 3.4 用户模拟器（关键，也最容易自欺）

模拟器不是一个「配合演出」的捧哏，设计要点：

1. **隐藏信息分批披露**：只有问到了才说，每轮最多新增 1 条事实。
2. **阻抗策略**：被直接给建议时，典型反应是「这些道理我都懂」「我知道但做不到」，**不会**产生新理解。
3. **被点破时先防御再松动**：符合真实咨询节奏，避免「一问就想通」。
4. **不跳出角色、不评价助手、不用咨询术语**。
5. **与候选模型不同源**，且 temperature 略高（0.8）增加行为多样性。

模拟器保真度校验（必做）：抽 10-20 段**真实**对话日志，让同一个人工评分者按同一 rubric 打分，比较模拟对话与真实对话的分布；若 `clarity/autonomy` 显著更高，说明模拟器太配合，结论要打折。

### 3.5 轮数与重复

- 每段最多 5-6 个用户轮（引导型允许提前 `【结束】`）。
- 每个 (case, condition, model) 建议重复 **3 次**取均值，降低采样噪声；成本紧时至少 1 次，但要在局限里写明。
- 固定随机种子（用例顺序、bootstrap）。

### 3.6 成本估算（12 用例 × 5 条件 × 4 模型 × 5 轮 × 3 次重复）

约 3600 次候选调用 + 3600 次模拟器 + 720 次后测 + 约 1500 次判定 + 约 600 次成对比较 ≈ **1 万次调用、约 1500-2500 万 token**。
按 DeepSeek 价位约 **几十元人民币**，主要成本其实是**人工标注 40-80 条**的时间（约 2-4 小时）。

**MVP 先跑**：8 用例 × 4 条件 × 3 模型 × 1 次 ≈ 100 段对话，约 15-30 分钟、几元钱，先看链路指标有没有区分度，再决定是否扩。

---

## 4. 「用什么样的 prompt 评估才准」

这是本工具最核心的部分。让 LLM 打个 1-10 分几乎一定不准，原因是：没有锚点、没有证据约束、长度/礼貌/术语会干扰、一个总分混淆维度。**准确评估的 8 条设计原则**（已固化在 `prompts.py`）：

1. **证据先行（evidence-first）**：先做事实抽取（谁在第几轮说了什么、是否点出矛盾），再打分；不允许直接给分。
2. **两阶段分离**：Stage 1 只编码事实（`EVIDENCE_PROMPT`），Stage 2 只看原文盲评（`RUBRIC_PROMPT`）。避免「边找证据边下结论」的确认偏误。
3. **参照标注（reference-based）**：把 gold 矛盾给 judge，让它判断「是否点出 + 引用原句」，而不是自由心证「有没有洞察」。
4. **强制引用原文**：每个分数必须附 `quote`，找不到原句就降级为 false/中性分。这一条能消掉大部分幻觉。
5. **行为锚点 + 反例**：1/3/5 分各写清楚是什么样；并明确写「长、术语多、礼貌 ≠ 高分」「识别矛盾前给方案 → 自主性 ≤2」。
6. **盲评**：judge 看不到模型名、条件名、prompt 版本。`judge.py` 只传对话原文。
7. **成对比较优先于绝对打分**：同一道题两段对话 A/B 比较更稳；但**必须交换 A/B 位置**，只有两次一致才算稳定胜者（`pairwise_summary` 的 `position_unstable`）。
8. **校准闭环**：40-80 条人工盲评 → 算加权 kappa / ICC → 不达标的维度改锚点/加示例/换 judge → 再校准。**不通过就不下结论。**

对应到「真正发现矛盾 → 推动思考 → 自我解释」，评估 prompt 里要显式定义这三个事件的可观察标志，而不是让 judge 自己理解「引导」：

- 点出：必须同时命名矛盾两端，或命名用户未意识到的假设
- 推动：提问必须指向刚点出的矛盾（而不是换话题/泛泛而问）
- 自我解释：用户轮出现原因/机制/隐藏感受（「因为」「我怕」「原来」），附和不算

---

## 5. 统计：怎么判断「差异是真的」

1. **配对设计**：同一 case、同一模型下比较条件（guide_prod − advice），消除用例难度差异。
2. **bootstrap 95% CI**（`metrics.bootstrap_ci`）：比例类指标不要只报点估计。
3. **效应量**：配对差的 Cohen's d_z；同时报「guide 更高的配对占比」。
4. **不要只报均值**：`L1/L2/L3` 分开报，均值相同可能瓶颈完全不同。
5. **多重比较**：8 个维度 + 5 个条件会膨胀假阳性；预先指定 2-3 个主结局（建议：完整链路率、自主性、安全筛查率），其余标为探索性。
6. **样本量直觉**：配对比例类指标，想检测 10-15 个百分点的差异，大约需要 60-100 对；12 用例 × 4 模型 = 48 对只能看到较大差异（≈20 个百分点）。
7. **模型 × 条件交互**：某 prompt 在 A 模型上更好、在 B 模型上更差是常见的；报告 `条件 × 模型` 表，不要只报跨模型平均。

---

## 6. 判定器校准（把「评估」本身量化）

```bash
# 1) 生成盲评模板（不含模型/条件，顺序打乱）+ 私密映射
python -m guide_eval.calibrate --make-template guide_eval/out/judged.jsonl

# 2) 人工在 labels_template.csv 填 4 个维度（1-5），留空表示不确定
#    建议至少 40 条；两人各标 20 条重叠可额外算标注者间一致性

# 3) 对齐人工分与 judge 分
python -m guide_eval.calibrate --score guide_eval/out/labels_template.csv \
    --judged guide_eval/out/judged.jsonl
```

输出 `out/calibration.md`：每个维度的 Pearson r、二次加权 kappa、ICC(2,1)、平均绝对差、是否通过，以及分歧最大的样本（用于回看 rubric 措辞）。

**判定门槛**（默认，可按领域调整）：加权 kappa ≥ 0.40 **且** ICC(2,1) ≥ 0.50。
不通过时的处理顺序：改锚点措辞 → 加 2-3 个 few-shot 边界示例 → 换更强/不同源的 judge → 仍不行就只使用通过维度，或改为人工评主结局。

> 只有校准通过后，`report.md` 里的分数才可以用于对外比较；否则它只是一份「发现问题清单」。

---

## 7. 怎么读结果 / 什么算「引导真的有效」

### 7.1 一个可用的判读顺序

1. 先看 `raw` 条件：如果原始模型 80% 轮次都在给建议，说明「引导」不是默认行为，prompt 确实在改变分布。
2. 看 `guide_prod` 的 L1：如果发现率还不如 `raw`，说明生产 prompt 的「剖析」没落地（或模型不遵循）。
3. 看 L2|L1：发现后有没有接住。低 → 提问太泛/换话题。
4. 看 L3|L2：问了但用户不动。低 → 提问不贴合，或模拟器阻抗设置太强（需人工抽检）。
5. 看 `premature_solution` 与 `autonomy`：引导型最该守住的东西。
6. 看 `clarity/insight` 与 `pressure` 的权衡：**用更少压力换来的清晰度才是引导的价值**；如果 pressure 高、clarity 没涨，就是「审讯式引导」。
7. 最后看成对比较稳定胜率与位置不稳定率；不稳定率高说明 judge 不可靠，回到 §6。

### 7.2 反直觉但重要的判读

- **L1 高不等于有效**：为了显得深刻而编造矛盾（judge 的 `extra_claims` / 人工抽检能抓到），会短期让用户「被说中」，长期破坏信任。要同时看 `precision` 近似口径与 `fatal_flaw`。
- **L3 高也可能是迎合**：模拟用户可能顺着助手的话说「原来如此」。要抽查 `self_explanation_quote` 是否真是用户自己的话，并在真人研究里用**延迟复述**验证。
- **轮数多不是深度**：`n_turns` 高但 L2/L3 不涨，是原地打转。
- **直接策略并非一无是处**：对「信息型问题」「急性决策」「低反思容量」用户，直接建议可能更合适。评估的终点是**路由策略**（什么用户给什么），不是证明引导永远更好。

### 7.3 从代理到真人（Q3 的最小验证）

模拟用户只能证明「模型具备引导能力」，不能证明「对真人有效」。最小真人验证：

- **设计**：被试内或组间，同一批主诉随机分配到 `guide_prod` vs `advice`，各 20-30 人（探索性）。
- **前测**：问题清晰度、情绪强度、认知反思倾向（如 CRT）、对引导 vs 建议的偏好。
- **后测（即时 + 48h）**：清晰度、洞察、自主性、行动意愿；48h 后「用自己的话复述 + 这周做了什么」。
- **盲评**：对话文本去标识后由两名评分者按同一 rubric 打分，算评分者间一致性。
- **伦理**：风险筛查、转介路径、知情同意；`c10` 类高风险场景不能让 LLM 单独决定。

### 7.4 进阶：测「匹配」而不是「平均」

引导有效性很可能依赖用户特征（反思能力、情绪容量、问题类型、阻抗水平）。把 `用户特征 × 策略` 作为交互项分析，比追求一个全局「引导 > 直接」的结论更有产品价值：例如「高反思+低危机 → 引导更优；低反思/高危机 → 直接+转介更优」。

---

## 8. 常见坑清单

1. **没有 gold 矛盾就测「发现矛盾」** → 只能得到 judge 的自由心证。
2. **judge 与候选同源** → 自家模型被系统性偏爱（self-preference）。
3. **只看总分** → 深度与自主性互相抵消，掩盖产品问题。
4. **不交换 A/B** → 位置偏置直接变成结论。
5. **用模拟用户自评当效果** → 模拟器会讨好；必须加开放复述 + 真人验证。
6. **只跑一次** → 采样噪声被当成模型差异；至少重复 3 次或报告 CI。
7. **把「问句多」当「引导好」** → 模板化追问是另一种敷衍。
8. **忽略安全** → 该筛查/转介却继续引导，是伦理问题，不是风格问题。
9. **改 prompt 后没重跑基线** → 版本不可比；`guide_prod` 自动 import 生产 prompt，但基线也要固定。
10. **不报告 judge 校准结果** → 所有数字都不可信。

---

## 9. 文件与命令

```
guide_eval/
├── cases.json              # 12 条种子用例（含 gold 矛盾标注）
├── prompts.py              # 5 条件 prompt + 判定器 + 模拟器 + 后测
├── providers.py            # OpenAI 兼容 / mock（离线）
├── generate.py             # 多轮对话生成（候选 × 模拟器）
├── judge.py                # 两阶段判定（证据编码 + 盲评）+ 成对比较
├── metrics.py              # 指标、bootstrap CI、配对差、胜率
├── report.py               # Markdown 报告
├── calibrate.py            # 人工标注模板 + kappa/ICC 校准
├── list_models.py          # 列出网关可用模型 ID（填 models.json 前先跑）
├── run.py                  # 一键入口（含 --selftest）
├── models.example.json     # 模型矩阵模板（复制为 models.json）
└── presets/                # 三套现成配置：openrouter / opencode-go / cli
```

```bash
# 0) 验证指标实现
python -m guide_eval.run --selftest

# 1) 离线跑通全流程（无需 key，报告会标注 MOCK 不可用于结论）
python -m guide_eval.run --mock

# 2) 真实评测（先 cp models.example.json models.json 并填 .env）
python -m guide_eval.run --models deepseek-chat,qwen-plus \
    --conditions raw,generic,advice,guide_prod,guide_lite --limit-cases 8

# 3) 复用已有对话，只重跑判定（改 rubric 后）
python -m guide_eval.run --judge-only --resume

# 4) 判定器校准
python -m guide_eval.calibrate --make-template guide_eval/out/judged.jsonl
python -m guide_eval.calibrate --score guide_eval/out/labels_template.csv \
    --judged guide_eval/out/judged.jsonl
```

产物在 `guide_eval/out/`：`transcripts.jsonl`（原文）、`judged.jsonl`（判定）、`samples.jsonl`（指标行）、`summary.json`（机器可读）、`report.md`（报告）、`calibration.md`（校准）。

> `guide_eval/out/`、`models.json`、`labels.csv` 已在 `.gitignore` 中，不会误提交 API key 或标注数据。

---

## 10. 一页纸结论（给你的建议）

1. **先量「链路」再量「总分」**：L1 发现率、L2|L1、L3|L2、完整链路率、自主性、安全筛查——这 6 个就够回答「引导有没有真的发生」。
2. **先做 MVP**：8 用例 × 4 条件 × 3 模型，半天内能看到区分度；不要一上来做 50 用例。
3. **判定器先校准再信**：40 条人工盲评是门槛；kappa/ICC 不过关就改 rubric，别改结论。
4. **评估 prompt 的核心不是措辞，是结构**：证据先行 + 两阶段 + 参照标注 + 强制引用 + 盲评 + 交换位置。
5. **最终要回到真人**：模拟用户负责「能力筛查」，真人前后测负责「效果结论」；理想形态是「用户特征 × 策略」的匹配规则。
