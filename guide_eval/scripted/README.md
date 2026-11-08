# 固定脚本对话评测（简化流程）

目的：用**同一组 8 轮用户话术**喂给多个模型，先拿到可解释的硬指标，供人工盲评后再继续深入分析。
不做动态用户模拟器——这样跨模型完全可比、可复现、成本低；代价是测不到真实用户被引导后的动态变化，所以硬指标只作筛查，质量判断交给人工。

## 1. 用例与对话脚本

`script.json`：国企行政 5 年、想转设计、偷偷接私活、父母期待稳定、怕失败证明自己不行。
8 轮用户话术按“表层主诉 → 工作现状 → 隐藏行动（私活） → 家庭压力 → 自我矛盾 → 关键事实（没投简历但一直接私活） → 说出核心恐惧 → 直接要答案”逐步揭开，**所有模型收到的用户话术逐字相同**。

第 8 轮“你觉得我该怎么办？”是引导型的关键测试：此时给方案还是把判断权留给用户。

## 2. 模型与参数

| 模型 | 说明 |
|---|---|
| deepseek-v4.1-flash | OpenCode Go |
| glm-5.3-flash | OpenCode Go |
| kimi-k3 | OpenCode Go |
| qwen3.8-flash | OpenCode Go |
| longcat-2.0 | OpenCode Go |
| hy3 | OpenCode Go |
| mimo-v2.6-flash | OpenCode Go |

- 端点：`https://opencode.ai/zen/go/v1`，需 `x-opencode-session` header。
- 参数：temperature=0.3；max_tokens=2000（glm-5.3-flash、kimi-k3 因截断/超时重跑时用 4000）。
- **每个模型只跑 1 次**：输出有采样方差（glm-5.3-flash 重跑一次后“首破轮次”从 2 变 3），所以小于 1 轮 / 0.25 覆盖率的差异不要过度解读；正式结论建议每模型重复 3 次取均值。

## 3. 文件

```
scripted/
├── script.json              # 8 轮用户话术 + gold 矛盾 + 检测规则
├── run.py                   # 运行器（--reanalyze 可离线重算指标）
├── results/<model>.md       # 每个模型一个完整对话文件（人读）
├── results/<model>.json     # 同上（机器读，含逐轮标签）
├── review/M01..M07.md       # 匿名盲评副本（人工评估用这些）
├── blind_key.json           # 匿名编号 ↔ 模型（评分时不要看）
├── human_review.csv         # 人工评分表（填这个）
├── human_review_guide.md    # 评分说明
├── metrics.csv / .json      # 硬指标
└── report.md                # 硬指标报告
```

## 4. 硬指标定义（`report.md`）

| 指标 | 定义 |
|---|---|
| 首破轮次 | 首次命中 A（言行矛盾）/ B（失败恐惧）/ D（父母期待）的回复轮次；C（拖延缓冲）单独不算核心矛盾 |
| 第7轮前点破 | 是否在第 7 轮用户自己说出“怕失败=证明我不行”之前主动点破 |
| 组件覆盖 | A/B/C/D 四类矛盾要素命中比例（句级关键词匹配） |
| 问句轮占比 / 每轮问号 | 引导倾向与追问强度 |
| 建议轮占比 | 直接给建议/方案的轮次比例 |
| 过早给方案 | 首次点破核心矛盾之前是否已给步骤/方案 |
| 指令密度/千字 | “你应该/建议你/你必须”等指令性表达密度 |
| 结尾给方案 / 结尾仍在提问 | 第 8 轮用户直接要答案时的反应 |

**重要局限**：
- 关键词规则会**欠检出**（模型用别的说法表达同一洞察）和**过检出**（泛泛提到“怕失败”）；它是筛查工具，不是最终评分。
- “组件覆盖”只说明提到没提到，不说明准不准、有没有编造——必须人工评。

## 5. 人工盲评（下一步）

1. 打开 `human_review.csv`；
2. 按 `transcript_file` 阅读 `review/Mxx.md`（已匿名，不含模型名）；
3. 对 5 个维度打 1-5 分：矛盾发现准确性、引导深度、自主性支持、提问贴合度、总体引导有效性；
4. **不要打开** `blind_key.json`；
5. 填好后把 `human_review.csv` 交回。

评分标准见 `../RATING_GUIDE.md` 与 `human_review_guide.md`。

## 6. 收回人工评分后我会算

- 每个模型的 5 维均值 + 排名（附硬指标并列对照）；
- 硬指标 vs 人工评分的 Spearman 相关（检验哪些规则指标真的有效）；
- 若多人评：加权 kappa / ICC 评分者一致性；
- 根据分歧最大的样本，决定是否修订检测规则或进入更完整的多轮模拟评测。

## 7. 复跑

```bash
# 全量重跑（会覆盖 results/）
caffeinate -i python -m guide_eval.scripted.run --concurrency 3 --max-tokens 4000

# 只重跑某几个模型
python -m guide_eval.scripted.run --models kimi-k3,hy3 --concurrency 2 --max-tokens 4000

# 不调用模型，只用现有回复重算硬指标（改规则后用）
python -m guide_eval.scripted.run --reanalyze
```

> 机器休眠会挂起长任务；macOS 下用 `caffeinate -i` 包住命令。当前 7 个模型 × 8 轮在正常网络下约 4-10 分钟。
