# 验证结果与边界

记录日期：2026-10-31。指定两模型的账号与协议探针已通过，见 [configured-03/result.json](../examples/probe/configured-03/result.json)。该探针验证 Plus 工具调用及观察回传、Flash JSON 输出，不等于业务验收。

最终默认配置为全 Plus，保留 Flash＋Plus 对照入口。[final-single-v4](../examples/real/final-single-v4/summary.json) 已完成两轮 C01—C09：**20 次真实请求全部通过自动初筛**；18 个真实场景均完成，另有 2 个独立 Mock C10 上限场景。C05 每场景包含两次请求，因此请求数与场景数不能混用。

两份 AI 逐例审阅均认为核心答案、引用、状态和必要工具路径符合用例，但两轮 C03 决策摘要仍各有一处过强的全库缺失判断。用户已确认关键合成资料与规则、选择默认全 Plus，并对最终关键结果明确表示“认可核心结果，保留限制说明”。这不等于用户已逐条检查全部 Trace 或全部提示词/源码，实际参与记录见 [review-checkpoints.md](review-checkpoints.md)。

## 最终全 Plus 回归

最终批次源码哈希为 `82feef6eb9fe96f434e4c1e0fee45954b1b451c8de6b11970ad0c266910c7058`，P4 哈希为 `c87e18a6ddb50695305a7b9b86237b9250ea75bbd5fdf1965ced212268fdf74a`。20 次真实请求合计 89 次模型调用、49 次工具调用，未触发 P5，2 次 C07 使用程序安全错误渲染。Mock 不计入这些统计。

[第一轮 AI 审阅](../examples/real/final-single-v4/ai-review-repeat1.json) 与 [第二轮 AI 审阅](../examples/real/final-single-v4/ai-review-repeat2.json) 各审 10 次请求，分别核验 10 条引用，核心业务结果均符合本组用例。新 P4 下未再观察到由 scope=null 推断通用、虚构主制度或版本有效性的明确表述；仍有 **2/20 请求（两轮 C03）**将空检索扩大成确认知识库无资料。两条 answer 本身均限定为本次检索未找到，但辅助摘要仍不严谨，因此不能宣称完整语义零缺陷。

两轮 C07 的原始模型候选仍复述未读 30 天，由 safe_error_render 按实际 TOOL_TIMEOUT 删除业务数值后交付；两轮 C05 首问的原问题保留也依赖本地查询保护。最终安全结果不能描述成原始模型完全遵守提示词。已保存的 checks 和 AI 审阅文件在生成时保留 pending；后续用户对关键结果的认可单独记在参与记录，不篡改原始运行材料。

历史 [verified-01](../examples/model_comparison/verified-01/comparison.json) 为相同旧版提示词下的两配置受控对照，不能用其耗时宣称新版 split 同样更快；该版本的原始失败与离线重评继续保留，详见后文。

## 测试与复现

最新 [final-v4/pytest.txt](../examples/test-results/final-v4/pytest.txt) 保存 **152 项测试通过**；[JUnit](../examples/test-results/final-v4/pytest.xml) 与 [测试元数据](../examples/test-results/final-v4/summary.json) 保存完整命令、时间与退出码。测试使用本地工具、FakeClient/Mock 和 HTTP 替身，不发送真实模型请求，覆盖检索与语料变更、参数校验、引用来源、观察回传、模型路由、Flash 回退、调用预算、一次输出修复、历史、脱敏、评测隔离与轨迹校验。

[干净环境复现](../examples/test-results/revision-03/clean-environment.json) 记录临时虚拟环境的依赖安装、131 项测试及 README Mock CLI 示例均成功。[revision-03 的 131 项测试](../examples/test-results/revision-03/pytest.txt)、更早的 [93 项测试](../examples/test-results/pytest.txt)、[离线 single](../examples/mock/release-single/summary.json)、[离线 split](../examples/mock/release-split/summary.json) 保留为历史阶段证据，不与真实模型效果混算。

## 真实用例与审核入口

每条请求保存 input、output、trace、trace-summary、checks、runtime-checks、metadata 及 corpus_snapshot。Trace 包含模型请求、工具参数、真实返回、后续动作与简要依据，不要求模型内部思维过程。

下表以最终全 Plus 两轮记录作为审核入口，判定限于核心事实与执行要求。用户已认可关键结果并保留已知限制，未声称完整材料逐项人工验收。

| 用例 | 预期与实际结果 | 代表记录 |
|---|---|---|
| C01 明确答案 | 实际检索并读 D01，依据费用发生后 30 天内提交申请作答 | [single 第 1 轮](../examples/real/final-single-v4/repeat-1/C01/trace-summary.md) |
| C02 文档冲突 | 读 D01 的 30 天及 D02 的 15 天后成功补查；未找到范围/替代/优先级依据，列出双方并 needs_clarification | [single 第 2 轮](../examples/real/final-single-v4/repeat-2/C02/trace-summary.md) |
| C03 资料外 | 成功检索年终奖问题但未命中，最终说明资料不足，不编造月数 | [single 第 1 轮](../examples/real/final-single-v4/repeat-1/C03/output.json) |
| C04 相似改写 | “垫付、报账”问题读 D01，期限与 C01 一致 | [single 第 1 轮](../examples/real/final-single-v4/repeat-1/C04/output.json) |
| C05 上下文追问 | 标准版不支持 PDF；追问专业版时本轮重新读 D06，回答支持 PDF | [single 会话](../examples/real/final-single-v4/repeat-1/C05/conversation.json) |
| C06 临时工具失败 | 一次 TOOL_TIMEOUT 后选择重读，成功后才回答并引用 | [single 第 1 轮](../examples/real/final-single-v4/repeat-1/C06/trace-summary.md) |
| C07 持续工具失败 | 两次读取超时后 tool_error；最终无未读业务数值与引用，说明真实错误及未核实状态 | [single 第 2 轮](../examples/real/final-single-v4/repeat-2/C07/trace.jsonl) |
| C08 内容替换 | 同 D01 ID、同日期，正文 30 改为 20；本轮重读，答案与引用均变为 20 天 | [single 第 1 轮](../examples/real/final-single-v4/repeat-1/C08/output.json) |
| C09 冲突变一致 | D01/D02 均为 30 天，读一致内容后 answered，未沿用 C02 冲突状态 | [single 第 2 轮](../examples/real/final-single-v4/repeat-2/C09/trace-summary.md) |
| C10 执行上限 | 单独 Mock 达上限后 step_limit，不是模型能力测试 | [Mock 上限](../examples/real/final-single-v4/repeat-1/mock-only/C10/output.json) |

最终汇总有 7 种观察已进入后续请求的真实路径，见 [final-single-v4 汇总](../examples/real/final-single-v4/summary.json)。正常“检索→读取→回答”、冲突“读双方→成功补查→追问”、恢复“超时→重读成功→回答”体现不同观察后的动作变化。C06/C07 工具故障为明确注入的本地超时，模型响应是真实 API 结果；未测试生产检索服务故障率。

最终两轮 C05 均使用自身实际首轮回答组成追问历史，再在当前轮读取专业版原文。C01→C08 的数值/引用变化、C02→C09 的冲突追问转回答均在两轮通过，成对检查保存在 [summary.json 的 repetitions](../examples/real/final-single-v4/summary.json)。

## 自动检查、AI 审阅与用户验收

自动检查验证状态、关键值、所需读取/引用、补查时序、观察回传与预算。引用校验确认引文是本轮成功读取的连续原文，且 ID、版本及语料匹配；它不能证明引文语义支持所有结论。测试覆盖“真实引用＋错误结论”可能通过来源校验的边界。运行中的 Agent 不读取 cases/gold，测试预期仅由离线评测器使用。

历史 verified-01 的 single 第 2 轮 C02 已读双方，再成功搜索“费用报销规定 D01 与 费用报销FAQ D02 冲突解决依据”，原检查器正则漏掉“冲突解决依据”，产生 19/20 的假阴性。[Trace](../examples/model_comparison/verified-01/single/repeat-2/C02/trace.jsonl) 与 [AI 分析](../examples/model_comparison/verified-01/analysis.json) 保留证据。扩展合理同义表达后的 [离线复核](../examples/rechecks/verified-01/summary.json) 已完成：single 20/20、split 20/20，合计真实请求 40/40；另 4 个 Mock 请求单独计数。复核未请求模型、未修改原始材料，每条记录保存原文件哈希与变化检查项。这是评测口径修正，不是新增模型效果或用户验收。

C09 答案正确性允许任一充分证据集合，不强迫同义的两份资料都引用；若声称“两份一致”，仍需读到双方。检索指标继续保留两份标注的分母。此调整纠正过强评测要求，不豁免无依据权威判断。

历史 [single AI 审阅](../examples/model_comparison/verified-01/ai-review-single.json) 中，16 个请求含引用，20 条引用支持核心答案；20 个请求里仍有 6 个存在动作理由或摘要问题。[split AI 审阅](../examples/model_comparison/verified-01/ai-review-split.json) 的 20 个请求里，10 个存在未消除的范围、权威、检索穷尽性或历史来源问题。两份都是 AI 审阅，不是可选 P6 API 运行，更不是用户本人验收。

保留的问题包括：由 `scope=null` 推断“不限范围/通用/范围最广”；从标题推断 D01 是“主制度”；称文档“均为有效版本”；将一次含两条 Query 的空检索说成已确认整个知识库不存在资料。它们未改变 verified-01 的期限、PDF 支持性等核心答案，但超过证据边界。最终 v4 新增范围、权威和穷尽性约束，保留旧问题作为修订依据；最终残留 C03 缺陷见上文，不能宣称“语义零缺陷”。

## 模型配置与检索对照

以下为措辞修订前的历史受控对照，统计来自 [原始 comparison](../examples/model_comparison/verified-01/comparison.json) 与 [analysis](../examples/model_comparison/verified-01/analysis.json)，含实际失败、P5 修复及全部真实调用，不含 C10。

| 指标 | 全 Plus single | Flash＋Plus split |
|---|---:|---:|
| 真实请求 | 20 | 20 |
| 原始自动初筛 | 19/20（1 个假阴性） | 20/20 |
| 离线修正检查器后的自动初筛 | 20/20 | 20/20 |
| AI 核心事实/引用/状态/必要路径 | 20/20 | 20/20 |
| 有未消除语义问题的请求 | 6/20 | 10/20 |
| P3 结构有效 | 20/20 | 20/20 |
| P3 平均 / 中位耗时 | 2.190 / 2.110 秒 | 1.177 / 1.166 秒 |
| 端到端平均 / 中位耗时 | 12.554 / 12.003 秒 | 11.687 / 10.181 秒 |
| 模型调用（P3 / P4 / P5） | 89（20 / 68 / 1） | 90（20 / 68 / 2） |
| 工具调用 | 48 | 48 |
| 真实回退 / 模型请求错误 | 0 / 0 | 0 / 0 |
| 服务返回总 token | 171,287 | 171,295 |

历史对照的 20 对请求使用相同输入、语料、源代码和提示词；split C05 追问复用同轮 single 的真实历史以控制变量。因此该实验不能当作 split 独立完整会话链的验证，见 [analysis.json 的 controlled_inputs](../examples/model_comparison/verified-01/analysis.json)。

split 的 P3 平均减少约 46.3%，端到端平均仅减少约 6.9%（0.867 秒）；P4/P5 仍由 Plus 执行。实验先 single 后 split，未交错随机化，样本很小，网络与服务负载可能影响速度。不能承诺普遍加速，也不能由总 token 直接推断费用。

两次 split C05 追问的 Flash P3 均把历史助手“不支持 PDF”写入 `known_context.support_status=false` 并保留标准版标签，当前追问却是专业版。改写 Query 正确，Plus 重新读 D06 后答对，但 P3 来源边界有缺陷。single 本批次未见此问题。用户据此选择全部 Plus 默认，不代表 single 在所有场景必然更可靠。

固定资料、原问题、Top5 和标注，使用实际 P3 改写比较 [single 检索](../examples/model_comparison/verified-01/single/retrieval_comparison/comparison.json)、[split 检索](../examples/model_comparison/verified-01/split/retrieval_comparison/comparison.json)。每配置 14 条有标注请求（7 条×2 轮，C05 只含首问），原 Query 与双 Query 均为 **Hit@5 14/14、已标注证据覆盖 18/18**，未见提升。这不是全量标注召回率；无适用标注的请求不计分母。小语料与 Top5 有上限效应，不能宣称 Query 改写已提升企业检索效果。

首次有效查询保留原问题由本地工具保障，Trace 同时记录 requested_queries、effective_queries 及策略。不能把程序补全后的合规结果写成模型原始 tool_calls 全部逐字遵守要求。

## 实际失败与工程介入

| 问题 | 修改及边界 | 保留证据 |
|---|---|---|
| 初始故障配置字段与工具契约不符 | 统一 fault 接口并复验；不算模型失败 | [早期 Mock](../examples/mock/acceptance-v1/summary.json) |
| 非对象 JSON 工具参数、数组 history.role 抛类型异常 | 先验类型；非法尝试计预算并回传错误 | [回归测试](../examples/test-results/revision-03/pytest.txt) |
| 真实第 1 轮 C01/C08 零工具却声称搜索无资料；C02 未补查；C07 将读取失败当资料不足 | 按用户认可的“先检索，有证据就回答”改 P3/P4/P5，并校验声明状态的轨迹 | [第 1 轮](../examples/real/acceptance-single-01/summary.json)、[迭代记录](iterations/real-round1.md) |
| 第 2 轮 C02 三条 Query 被 INVALID_ARGUMENTS 拒绝，旧检查仍给通过 | 执行前拒绝不算查证，正常冲突验收要求成功补查 | [第 2 轮 C02](../examples/real/acceptance-single-02/C02/trace.jsonl) |
| 第 2 轮 C07 已选 tool_error，仍复述未读 30 天 | 模型已选 tool_error 且没有成功读取时，程序 safe_error_render 按实际错误生成文本，移除业务值与引用；不替模型做业务判断 | [第 2 轮 C07](../examples/real/acceptance-single-02/C07/output.json) |
| verified-01 两配置第 2 轮 C07 原候选仍有未读引用 | 来源校验拦截，触发唯一一次 P5，再做错误安全渲染；两配置各两次 C07 都有渲染事件 | [single C07](../examples/model_comparison/verified-01/single/repeat-2/C07/trace.jsonl)、[split C07](../examples/model_comparison/verified-01/split/repeat-2/C07/trace.jsonl) |
| split 第 2 轮 C03 候选 gaps 为空 | 输出校验要求未完成状态解释缺口，P5 修复 | [split C03](../examples/model_comparison/verified-01/split/repeat-2/C03/trace.jsonl) |

第 1 轮原始汇总为 5/10 场景通过，第 2 轮为 10/10；两分母均含 C10 Mock，且第 2 轮旧检查漏掉非法补查和未读摘要泄露，不能理解为当时已无缺陷。所有旧输入、候选、工具错误与输出保留，不用成功重跑覆盖失败。

轨迹校验只约束模型已声明的行为，不依靠 gold 推断冲突。实际查询超时可证明尝试过，不证明成功；正常 C02 验收要求 ok=true。P5 只能修正输出，不能补造工具；若未满足查证条件，修复后仍应 invalid_output 或明确未完成。

## 未完成与外推限制

最终全 Plus 回归及 verified-01 离线复核均已完成。用户已确认关键数据规则、默认模型和最终核心结果（含保留限制）；未声称逐条全部 Trace、提示词或源码已由用户人工检查。C03 辅助措辞、split P3 历史来源与检索无增益仍是已知限制，不用自动分数覆盖这些事实。

只有 8 份基础合成资料、9 类真实场景，开发和验收集公开且已用于调试，因此是回归验收，不能声称独立泛化、生产可靠性或统计显著性。P6 可选评审与 D09 可裁决冲突扩展未运行；向量检索、微调、强化学习、UI 与部署不在本次核心范围。

最终交付快照的[干净环境验证](../examples/test-results/final-v4/clean-environment.json)也已通过：从跟踪文件导出到临时目录，新建虚拟环境安装依赖，152项测试与README Mock CLI成功，0次真实API请求；未复制.env。其运行代码哈希与最终v4真实回归一致。
