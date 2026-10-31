# 合成知识与评测数据

所有制度、产品和规则均为虚构资料，仅用于第 3 题功能验证。当前数据与提示词清单版本为 `2026-10-31-v4`。用户已回复“保留这些数据与规则”，确认展示的D01/D02未知范围与优先级、D05/D06差异、年终奖不收录及关键提示规则；随后回复“认可核心结果，保留限制说明”。这不等于完整逐行审阅数据、提示词或源码，也不等于逐条人工审核20次请求，具体边界见 `manifest.json`。

`documents.json` 是 8 份基础资料，与 `variants/conflict.json` 内容一致。在线工具只应读取指定资料数组；不能加载带标准答案的用例文件。

| 快照 | 文档组成 | 与基础资料的区别 |
|---|---|---|
| `single_source` | D01、D03—D08 | 排除 D02，报销期限只有一个来源 |
| `conflict` | D01—D08 | D01 为 30 天、D02 为 15 天，范围和优先级都未知 |
| `changed_value` | D01、D03—D08 | 仅把 D01 的 30 改为 20，ID 和版本日期不变 |
| `consistent` | D01—D08 | 仅把 D02 的 15 改为 30 |
| `resolved` | D01—D09 | 额外加入明确裁决适用范围的公告 D09，不能用于基础冲突案例 |

每个文件独立保存完整快照。`manifest.json` 记录生成版本、原始方案哈希、文件哈希和审阅边界。文件哈希用于核对交付文件，不应假定与运行器对 JSON 正规化后计算的 `corpus_hash` 相同。

v2 修正 C09 的可接受证据条件，v3 登记真实失败驱动的 P3/P4/P5；v4 仅进一步修改 P4 的简要依据边界，针对已观察到的范围、权威、全库穷尽性及版本效力推断。这些修订均未改变合成制度事实；v4 的 P3/P5 沿用 v3。P1/P2/P6 保持原方案模板；当前用例与提示词文件哈希记录在 `manifest.json`。`validation.json` 保留首版静态检查历史，不能把其中“所有提示词与原稿一致”的检查结果当作当前 P3—P5 状态。

## 用例契约

`cases.json` 是 C01—C10 验收清单，`development_cases.json` 是 6 条开发样例，`optional_cases.json` 是可选裁决路径。均为 JSON 对象数组。

- `input` 只包含 `question` 与可选 `history`；每条历史是 `role`、`content`。
- `corpus_variant` 是 `variants/` 下不带 `.json` 的文件名。
- `expected_status`、`expected_claims`、`required_evidence`、`forbidden_claims`、`behavior_checks` 只用于离线检查。
- `required_evidence` 的每项为 `doc_id`、`chunk_id`、`quote`，原文必须存在于该用例指定快照。
- 可选 `acceptable_evidence_sets` 是替代证据组列表；每组由 `doc_id/chunk_id` 组成，取得并引用任一完整组可满足支持门槛。没有该字段时仍按 `required_evidence` 核对。C09 的 D01/D02 都明确写 30 天，所以任一已读来源可支持期限答案；`required_evidence` 仍保留两份资料用于覆盖率计算，不能把支持门槛和覆盖率分母混在一起。
- `expected_claims` 是便于初筛的关键词或短语列表；`forbidden_claims` 只是部分明显错误示例。字符串存在/缺失检查不能证明语义正确，尤其不能识别所有否定和条件错误。`behavior_checks` 保留人工评阅要求。
- `fault_injection` 在评测侧传入工具层：`tool`、`doc_id`、`times`（正整数或 `always`）；工具固定返回 `TOOL_TIMEOUT` 和 `retryable=true`，不放入在线问题或提示词。
- C10 的 `budget` 和 `mock_behavior` 仅配置确定性测试，不能用于真实模型效果评分。
- C05 的 `follow_up` 只有第二轮问题；普通验收拼接本配置首轮用户问题与**首轮实际模型输出**，再执行第二轮。single/split 模型对比统一使用 single 的首轮实际输出形成相同追问历史，以控制输入差异。`follow_up_expected` 仅作离线预期，不能伪装成对话历史。
- `review_status=draft_pending_user_review` 表示尚未收到用户逐条审阅意见，不影响先执行工程验证。

开发样例与验收样例共享知识事实，预期类别也已公开。结果应称功能/回归评测；不能据此宣称未见过问题上的泛化能力。任何依据验收失败做出的调整，都要保留修改及重跑记录。

C09 若声称“两份规定一致”，仍需核实双方；不得因只需一份充分证据就编造制度地位或版本优先级。首轮自动检查过严与首轮工具动作理由错误分别记录，旧结果不回写为通过。修订依据见 [真实首轮记录](../docs/iterations/real-round1.md)。

`examples/inputs/` 是可交给 CLI 的纯问题输入。相同问题可能需要不同的资料快照、故障参数和运行目录；单靠输入文件名不能决定答案。

v3 的 [single/split 双次真实比较](../examples/model_comparison/verified-01/comparison.json) 已完成；用户随后明确选择“默认全 Plus（推荐）”，split 仍保留可选。自动初筛不等于语义全部正确：[split AI 审阅](../examples/model_comparison/verified-01/ai-review-split.json) 在核心行为通过的请求中仍发现将 null 范围推为通用、由标题推断主制度、扩大检索穷尽性和 Flash 混入历史 assistant 功能结论等问题。用例文件的 draft_pending_user_review 保留逐条标注尚未完整人工审核的边界；展示的关键数据、规则与核心结果已有用户确认，单独记于manifest，不改写旧运行输入。

v4 只加强P4的依据措辞约束。[全Plus两次回归](../examples/real/final-single-v4/summary.json) 已完成：18个真实场景执行包含20次真实请求，另有2次Mock C10；汇总自动20/20场景初筛通过。20次记录中未观察到明确通用范围、主制度或版本均有效推断，但两轮C03仍扩大检索穷尽性，第二轮还把一次工具调用中的双Query说成两次检索。v3比较记录不回写，当前结果不能宣称全部语义缺陷已消除或泛化保证。
