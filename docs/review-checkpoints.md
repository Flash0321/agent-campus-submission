# 本人审阅节点与实际意见

日期：2026-10-31。下列内容是已实现版本的可审阅材料。自动检查和 AI 语义审阅不替代本人意见；没有收到意见的节点保留待审阅。

## 已收到的本人意见

| 节点 | 实际回复 | 落实方式 |
|---|---|---|
| 最初数据与提示词审阅 | “稍后审阅，当前保持待确认” | 初期保留待确认 |
| 关键数据与规则审阅 | “保留这些数据与规则” | 确认下表展示的关键数据及证据约束，不声称逐行审过全部代码或模板 |
| 未搜索就追问的真实失败 | “认可这一修正：先检索，有证据就回答” | P3 不编造必填背景；P4 主题明确先搜索；运行时检查检索事实 |
| 最终关键结果审阅 | “认可核心结果，保留限制说明” | 正常、冲突、持续故障、数值替换与冲突消除的展示结果已认可，C03摘要限制保留；不声称人工逐条审核全部Trace |
| 模型取舍 | “默认全 Plus（推荐）” | 默认 single；保留 split；原始比较记录不改写 |
| 仓库归属 | “使用现有账号：Flash0321/agent-campus-submission，项目展示名写 TZX0321” | 已确认后续公开发布安排 |

本人配置了本地 API。以上仅说明实际参与，不归因于本人编写了 AI 实现的代码、数据或测试。

## 关键数据与规则：已确认；完整逐行审核未声称完成

| 合成材料 | 原文/边界 | 期望行为 |
|---|---|---|
| D01，2026-09-01 | 员工报销应在费用发生后30天内提交申请。 | 单来源且无冲突线索时按此原文回答 |
| D02，2026-10-01 | 员工报销应在费用发生后15天内提交申请。 | 与 D01 冲突时读双方、补查依据；无法消解则并列并追问 |
| D01/D02 范围及优先级 | scope=null、priority=null | 未知不是通用；日期较新不自动优先 |
| D05 标准版 | 支持 CSV，不支持 PDF | 保留产品版次和否定 |
| D06 专业版 | 支持 CSV 和 PDF | 上下文追问重新读取专业版原文 |
| 年终奖规则 | 未收录 | 只能说明本次搜索没有支持资料，不能编造月数 |
| C09 一致规则 | D02 由15改30天 | 任一已读支持来源足够回答30天；声称双方一致则应核实双方 |

完整入口：[基础文档](../data/documents.json)、[验收用例](../data/cases.json)、[快照及数据边界](../data/README.md)。资料完全合成，不代表真实公司制度。D09 裁决公告仅在可选快照中存在。

P1/P2/P6 保留规划稿；P3/P4/P5 已根据真实失败修改，并非全文未改。关键约束是先查再答、保留数字/否定/版次、历史助手结论不是证据、冲突须查证、故障与资料不足分开、所有调用统一计数。完整模板：[P3](../src/prompts/P3.txt)、[P4](../src/prompts/P4.txt)、[P5](../src/prompts/P5.txt)。修订原因见 [迭代记录](iterations/real-round1.md)。

## 真实关键结果：本人已认可核心结果并保留限制

以下均来自最终 v4 全 Plus 第一轮真实记录；并非预先填写的期望答案。每个目录附输入、输出、原文快照和完整 Trace。

| 场景 | 实际结果 | 记录 |
|---|---|---|
| 正常 C01 | “员工报销应在费用发生后30天内提交申请。”，引用 D01，answered | [输出](../examples/real/final-single-v4/repeat-1/C01/output.json)、[动作摘要](../examples/real/final-single-v4/repeat-1/C01/trace-summary.md) |
| 冲突 C02 | 并列 D01=30天、D02=15天，补查未找到裁决依据，needs_clarification | [输出](../examples/real/final-single-v4/repeat-1/C02/output.json)、[动作摘要](../examples/real/final-single-v4/repeat-1/C02/trace-summary.md) |
| 资料外 C03 | 本次检索未发现年终奖规则，insufficient_evidence | [输出](../examples/real/final-single-v4/repeat-1/C03/output.json) |
| 上下文 C05 | 首问标准版不支持 PDF，追问专业版后重新读取 D06 并回答支持 | [实际会话](../examples/real/final-single-v4/repeat-1/C05/conversation.json) |
| 暂时故障 C06 | 观察超时后由模型重试，再读取原文作答 | [动作摘要](../examples/real/final-single-v4/repeat-1/C06/trace-summary.md) |
| 持续故障 C07 | tool_error，无法核实；最终不展示未读取数值 | [输出](../examples/real/final-single-v4/repeat-1/C07/output.json)、[包含程序安全渲染的 Trace](../examples/real/final-single-v4/repeat-1/C07/trace-summary.md) |
| 内容替换 C08 | 同 ID/日期的原文改20天后，实际回答和引用改20天 | [输出](../examples/real/final-single-v4/repeat-1/C08/output.json) |
| 冲突消除 C09 | 两份改为一致后，由追问改为 answered | [输出](../examples/real/final-single-v4/repeat-1/C09/output.json) |

v3 结果有明确限制：部分工具 reason 或 decision_summary 把未知范围说成通用，或把制度标题当成权威依据。核心答案有依据不意味着全部字段无误。P4 已针对这些发现收紧措辞，最终默认配置两轮回归20次真实请求自动通过；AI审阅仍发现C03的decision_summary把本次未检出扩大成全库无资料，第二轮还把一次双Query请求说成两次检索。主answer准确限定为本次检索未找到，残留问题如实列入限制。故障场景的安全呈现部分来自程序校验/渲染，不能记为模型自己全部改正。历史记录完整保留。

## 模型选择的依据与边界

两配置同条件各20次真实请求（C01—C09两次，C05含追问），原始自动检查 single19/20、split20/20。single唯一失败为检查器未识别成功查询“冲突解决依据”，由离线重评处理，不能删除原始失败。AI审阅认为核心答案与引用均符合；全文语义仍有上述缺陷。

平均端到端：single12.55秒、split11.69秒，差约6.91%；平均P3：2.19秒、1.18秒。样本小且顺序运行，不能断言稳定加速。完整复核发现 split 的两次 C05 追问都把历史助手事实写入 known_context，后续 Plus 仍重新读取资料而回答正确。提问本人选择时已发现其中一次，完整报告保留两次。本人选择默认全 Plus；无模型微调或强化学习。

[原始比较](../examples/model_comparison/verified-01/comparison.json)、[完整分析](../examples/model_comparison/verified-01/analysis.json)、[single AI审阅](../examples/model_comparison/verified-01/ai-review-single.json)、[split AI审阅](../examples/model_comparison/verified-01/ai-review-split.json)。原文件生成时 selected_profile=null，后续本人选择记在本文件和 AI 使用说明中。

## 提交状态

本地代码、测试与证据已可审阅。本人已确认保留所展示的关键合成数据与规则；本人已回复“认可核心结果，保留限制说明”，此确认不等于逐条审阅全部20次请求。公开发布已获授权；发布材料和平台附件要求见 [submission.md](submission.md)。平台最终提交尚未执行。
