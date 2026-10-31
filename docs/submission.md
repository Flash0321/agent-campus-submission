# 笔试平台交付

题号：3. 企业知识问答 Agent。展示名：TZX0321。公开仓库：[Flash0321/agent-campus-submission](https://github.com/Flash0321/agent-campus-submission)。用户明确授权后，于2026-10-31在Edge中以Flash0321创建公开仓库；创建前确认名称可用，没有覆盖其他项目。用户已认可展示的核心测试结果，要求保留限制说明。

## 最终版本标识

完整代码与运行证据已发布，远端与本地Git tree哈希核对一致。最终提交以远端 main 对应的完整 commit SHA 为准。SHA 与可粘贴文字保存在仓库外的 `delivery/提交说明.txt`，避免将提交自己的SHA写入同一个提交导致循环变动。ZIP由该提交的跟踪文件制作；本地、远端和ZIP内容须核对一致后才报告交付完成。Trace中的源码/提示词哈希标识各次运行实际使用版本，早期失败记录和旧模型比较不改写为最终版本。

## 答题框内容

仓库外提交说明包含以下实测信息：

- 本地Python CLI，中文BM25＋Query改写，原生Function Calling循环；提供search_documents/read_document，模型依据真实工具观察决定补查、读取、追问或结束。
- 默认全Plus（qwen-plus-2025-12-01）；保留Flash（qwen-flash-2025-07-28）＋Plus配置。均通过百炼北京地域API调用，没有自建模型、微调或强化学习。
- 最终默认配置两轮覆盖C01—C09，18个真实场景、20次真实用户请求通过自动初筛；每轮C05含两次请求。C10两次为单独标注的Mock上限验证。
- 152项可执行测试通过；保留正常、冲突、资料外、改写、追问、故障和文档变更的实际输入、输出与Trace。
- 修订前的模型比较各20次真实请求：single均值12.55秒，split11.69秒；依据完整质量审阅选择全Plus。检索对照未测得增益。
- 限制：微型合成数据、同域回归；C03决策摘要仍有检索穷尽性夸大，主答案正确限定为本次未找到；故障安全输出部分依赖程序保护；split历史来源问题尚在。
- AI协作与本人实际贡献见docs/04-ai-usage.md，实际用时见docs/work-log.json，不把AI执行算成本人手写或本人独立实测。

评审入口为README、docs/03-evaluation.md和examples/real/final-single-v4。所有依赖、配置示例、源代码、测试和五份规定文档均在同一仓库。

## 平台附件

用户提供截图显示：文本框可填写说明或思路；最多选择6个文件，单个不超过100MB，格式不限，文字和文件均可提交。没有证据显示其他字数或格式限制。

交付一个项目ZIP即可，不需凑满6个。压缩包顶层为`agent-campus-submission/`；保留README、src、tests、data、examples、docs、依赖和.env.example；排除.env、.git、虚拟环境与缓存。ZIP和校验清单保存在仓库外delivery目录。

打包后核对文件清单、大小和SHA-256，并从解压目录运行README入口。实际向笔试平台填写、上传或点击最终提交尚未执行。
