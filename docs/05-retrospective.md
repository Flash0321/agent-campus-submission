# 实施复盘与未完成项

本文件由代码 Agent 根据真实 Trace、测试及 AI 审阅整理。用户已确认关键数据规则、认可“先检索，有证据就回答”并选择全部 Plus 默认；对最终关键结果明确表示“认可核心结果，保留限制说明”。不把这些意见扩写成用户已逐行审阅全部代码或逐条检查全部 Trace。实际参与状态见 [review-checkpoints.md](review-checkpoints.md)。

## 最难的问题：证据状态和模型判断

离线跑通不代表真实模型会正确取舍。首轮面对“报销期限多久”，模型先追问范围，零工具却声称搜索没有资料；持续读取超时时又把摘要 30 天写进答案。先修订提示词，让主题明确的问题先检索，再按观察决策；程序只保证可核验的执行条件，防止“没搜索却说没资料”“没读到原文却提交引用”。见 [首轮记录](../examples/real/acceptance-single-01/summary.json) 与 [迭代记录](iterations/real-round1.md)。

第二轮暴露了更细的问题：模型提出冲突补查，但三个 Query 超出参数上限，没有真正执行；旧评测将提出动作当成完成查证。修订后，执行前拒绝不计查证，正常 C02 要求读双方后有相关成功补查。轨迹校验只约束模型已经声明的冲突，不用测试答案替模型识别冲突；P5 可以改输出，不能伪造缺失工具。

仅靠提示词没有稳定阻止 C07 未读摘要泄露，因此加入 safe_error_render：模型已选择 tool_error 且没有成功读原文时，程序按实际错误生成结束文本。verified-01 两配置各两次 C07 均用到保护，两配置第 2 轮还曾生成未读引用，被校验拦截并触发 P5。最终安全结果来自模型决策、来源校验、一次修复与程序渲染，不能归功于原始模型从未出错。候选完整保留在 [single C07](../examples/model_comparison/verified-01/single/repeat-2/C07/trace.jsonl) 与 [split C07](../examples/model_comparison/verified-01/split/repeat-2/C07/trace.jsonl)。

## 评测也需要验证

verified-01 原自动结果 single 19/20、split 20/20。single 失败样例实际在读双方后成功搜索“冲突解决依据”，只是正则同义表达覆盖不足。[修正检查器后的离线重评](../examples/rechecks/verified-01/summary.json) 已完成：两者各 20/20，模型 API 调用为 0，原文件未改且保留哈希。不必为好分数反复请求模型。C09 也不应强迫两份同义资料全部引用：任一已读充分证据可支持结论，声称“两份一致”才必须读双方。

反过来，第二轮真实运行曾自动 10/10，仍有无效补查与未读摘要泄露。自动分数不是语义结论。[single AI 审阅](../examples/model_comparison/verified-01/ai-review-single.json) 与 [split AI 审阅](../examples/model_comparison/verified-01/ai-review-split.json) 均认为 20 次请求核心答案、引用、状态和必要路径符合用例，但分别有 6 次、10 次请求有未消除的范围、权威、检索穷尽性或历史来源问题。scope=null 只表示未知，不能推出范围最广；版本日期也不证明文件当前有效。这些问题未因期限正确而删除。

最终 [全 Plus 两轮回归](../examples/real/final-single-v4/summary.json) 已完成，20 次真实请求核心结果符合，自动初筛通过；另 2 个 Mock 上限场景不计真实能力。两份 [首轮 AI 审阅](../examples/real/final-single-v4/ai-review-repeat1.json)、[次轮 AI 审阅](../examples/real/final-single-v4/ai-review-repeat2.json) 未发现此前明确的范围通用、主制度或版本有效性推断，但两轮 C03 仍各有一处全库缺失表述，合计 2/20 请求。C07 原始候选仍靠程序移除未读值，不能说提示词已彻底解决。用户认可核心结果并选择保留这些限制；verified-01 速度只对应旧提示词，未重测新版 split。

## 技术取舍与学习

BM25、中文分词和双 Query 融合足以启动核心链路，重点投入证据与冲突处理。小语料 BM25 得分可能为负，不能用 score>0 判断有无结果，实际用有效词项交集区分零命中。每次新建语料及索引，正文参与哈希，使同 ID、同日期的 30→20 天也能改变读取、引用与答案。

检索提升必须实测。verified-01 每配置 14 条标注请求，原 Query 与双 Query 都是 Hit@5 14/14、已标注证据覆盖 18/18，未见提升，见 [检索对照](../examples/model_comparison/verified-01/single/retrieval_comparison/comparison.json)。小数据和 Top5 已接近覆盖上限。后续应增加同义跨度更大、干扰更多的独立样例，再决定是否加向量检索，不能直接声称双 Query 有增益。

Flash 的 P3 平均耗时从 2.190 秒降至 1.177 秒，端到端平均只从 12.554 秒降至 11.687 秒，约减少 6.9%。两次 split 追问还将历史助手事实写入 known_context；Plus 本轮重新读 D06 才避免传播成最终错误。JSON 结构全部合法不等于来源语义正确。用户选择全部 Plus 默认，并保留 split 后续修复比较。两轮顺序执行的小样本不能证明普遍加速或模型质量排名，见 [对照分析](../examples/model_comparison/verified-01/analysis.json)。

工程测试修复了非对象 JSON 参数、history.role 类型、故障契约等边界。最新已保存 [152 项测试](../examples/test-results/final-v4/pytest.txt)；更早的 [131 项测试及干净环境复现](../examples/test-results/revision-03/clean-environment.json) 保留为阶段记录。这些证明执行约束可回归，不替代真实模型效果；Mock 上限验证也不计入真实模型能力。

## 用时

首个实施记录为 **2026-10-31 10:39:49（Asia/Shanghai）**。[work-log.json](work-log.json) 中最初的 888.9 秒仅表示 10:54:37 的本地候选阶段，明确不含后续真实验证，不能当作完整耗时。verified-01 实际汇总时间为 11:19:18（single）和 11:23:12（split），之后仍在审阅和修订。最终 v4 汇总时间为 11:36:02，从首次实施记录至真实回归完成的墙钟约 56 分 13 秒（含等待），之后继续审阅、打包与发布。完整交付结束时间及分阶段耗时见最终工作记录，不将该阶段墙钟当成用户个人工时。

多任务并行，不能将子任务耗时相加作为用户本人投入。前期选题和另一规划 Agent 时间未提供；用户实际思考与审阅时长未计时，不编造个人工时。建议 180 分钟是考核预算，不是实际投入。

## 已交付边界与下一步

1. 最终全 Plus 两轮真实回归、AI 逐例审阅与 verified-01 离线复核已完成，原始失败均保留。C03 辅助摘要的穷尽性表述仍需后续改进，不能为消除已知缺陷而改写原运行输出。
2. 用户已认可关键数据规则、默认模型和最终核心结果，明确保留限制说明；未声称用户对全部提示词、源码及 Trace 逐项审查完成。后续若有新意见，只记录真实反馈。
3. split 的 P3 历史来源问题未修复，新措辞版本未再跑 split 对照；检索未见增益，缺更大且独立的困难数据集。优先加入来源标注、未知范围样例，再衡量改进。
4. P6 可选评审、D09 有明确裁决依据的冲突扩展未运行。向量检索、UI、部署、微调和强化学习未实现，亦非此次必须范围。
5. 已创建公开仓库 `Flash0321/agent-campus-submission`。完整项目发布、远端 commit SHA 与平台附件以 [submission.md](submission.md) 和最终工作记录为准；仓库创建本身不等于完整项目已发布。
