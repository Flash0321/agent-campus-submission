# TZX0321 · 第 3 题：企业知识问答 Agent

本项目帮助员工根据合成制度和产品 FAQ 查找可靠答案。用户输入问题及可选对话历史，程序输出回答、文档 ID 与原文引用、资料缺口和任务状态。

实现采用本地 Python CLI、中文 BM25 检索及百炼北京地域 Chat API。模型通过原生 Function Calling 选择检索或读取工具，工具的实际结果回传给模型，再由模型决定补检索、查证、追问或结束。

**两个指定模型均已接通，已完成真实业务测试及两配置各 20 次请求的对照。用户已选择默认全 Plus，保留 Flash＋Plus。** 本人已认可关键结果并要求保留限制说明；结果、失败与边界以 [评估文档](docs/03-evaluation.md) 为准。自动检查、AI 语义审阅和用户验收分别记录，不把其中一种替代另一种。完整项目已发布到公开仓库 [Flash0321/agent-campus-submission](https://github.com/Flash0321/agent-campus-submission)；最终提交与附件核对方式见 [平台提交说明](docs/submission.md)。

当前已保存的实际验证如下；完整逐轮结果及统计口径见评估文档：

| 验证 | 实际结果 | 证据 |
|---|---|---|
| 可执行本地测试 | 最终 v4：152 项通过；干净环境依赖安装、测试和CLI均通过 | [pytest 输出](examples/test-results/final-v4/pytest.txt)、[干净环境验证](examples/test-results/final-v4/clean-environment.json) |
| 最终默认配置 v4 | 全 Plus 两轮20次真实请求自动初筛通过；AI审阅核心答案和引用符合，C03的决策摘要仍有过度概括 | [真实汇总](examples/real/final-single-v4/summary.json)、[首轮AI审阅](examples/real/final-single-v4/ai-review-repeat1.json)、[第二轮AI审阅](examples/real/final-single-v4/ai-review-repeat2.json) |
| 两配置离线套件 | C01—C10 各 10/10 自动初筛通过，属于 Mock | [single](examples/mock/revision-03-single/summary.json)、[split](examples/mock/revision-03-split/summary.json) |
| 检索对照 | 14 条标注请求（7条×2轮），原 Query/双 Query 命中均 14/14、标注证据覆盖均 18/18；未测得提升 | [真实 Query 对照](examples/model_comparison/verified-01/single/retrieval_comparison/comparison.json) |
| 模型接通 | Plus 工具调用及观察反馈、Flash 结构化预处理均通过 | [实际探针](examples/probe/configured-03/result.json) |
| 真实配置对照 v3 | 各 20 次请求；原自动初筛 single 19/20、split 20/20，single 有一处检查器同义词误判；AI 核心答案审阅各 20/20，但依据措辞存在问题 | [原始比较](examples/model_comparison/verified-01/comparison.json)、[分析与限制](examples/model_comparison/verified-01/analysis.json) |
| 原记录离线重评 | 修正同义查询检查器后40/40真实请求通过，0次新API调用，原结果不改 | [重评明细](examples/rechecks/verified-01/summary.json) |
| 实测速度与选择 | 均值 single 12.55 秒、split 11.69 秒；用户选择全 Plus，混合配置收益有限且出现历史事实混入上下文 | [本人参与记录](docs/04-ai-usage.md) |

## 评审入口

| 内容 | 入口 |
|---|---|
| 需求与验收映射 | [01-requirements.md](docs/01-requirements.md) |
| 技术方案、模型路由、预算和引用边界 | [02-solution.md](docs/02-solution.md) |
| 实际测试、失败和证据目录 | [03-evaluation.md](docs/03-evaluation.md) |
| AI 使用及本人实际参与 | [04-ai-usage.md](docs/04-ai-usage.md) |
| 实际用时、复盘与未完成部分 | [05-retrospective.md](docs/05-retrospective.md) |
| 需要用户审阅的数据、提示词及结果 | [review-checkpoints.md](docs/review-checkpoints.md) |
| 合成资料、快照与用例契约 | [data/README.md](data/README.md) |

## 环境与安装

本地使用 Python 3.12，依赖版本固定在 [requirements.txt](requirements.txt)。不需要 GPU、向量数据库或自建模型服务。以下命令在仓库根目录执行。

macOS / Linux：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Windows PowerShell：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

如果不激活环境，可直接用 `.venv/bin/python`；Windows 对应 `.venv\Scripts\python.exe`。安装后的实际运行结果见评估文档。

## 无密钥离线运行

```bash
python -m src.cli --mode mock --input examples/inputs/normal.json --output-dir examples/mock/demo-normal
python -m src.evaluate --mode mock --output-dir examples/mock/acceptance
python -m pytest -q
```

每次使用新的输出目录，例如第二次运行改成 `examples/mock/demo-normal-2` 或 `examples/mock/acceptance-2`。程序拒绝覆盖已有运行证据。CLI 未给 `--output-dir` 时自动使用带时间的目录。

Mock 客户端是明确标注的脚本化演示策略，只读取问题、历史和实际本地工具返回，不读取标准答案。它可以展示日志、异常及执行上限机制，但不能证明真实模型会自主选择这些动作。

## 配置与真实模型验证

首次从 [.env.example](.env.example) 创建本地 `.env`，已有配置请保留。文件中填写：

| 变量 | 含义 |
|---|---|
| `LLM_API_KEY` | 用户自己的百炼 API Key |
| `LLM_BASE_URL` | 同账号、同业务空间的北京地域兼容 Chat API 地址 |
| `LLM_MAIN_MODEL` | `qwen-plus-2025-12-01` |
| `LLM_FAST_MODEL` | `qwen-flash-2025-07-28` |
| `MODEL_PROFILE` | `single` 或 `split`；用户已选择默认 `single`（全 Plus） |
| `LLM_TIMEOUT_SECONDS` | 单次 HTTP 请求超时，默认 45 秒 |

支持北京业务空间专属地址 `https://<WorkspaceId>.cn-beijing.maas.aliyuncs.com/compatible-mode/v1`，以及配置样例中的北京旧域名。接口地址须与用户账号和业务空间匹配；账号是否可调用两个指定快照，必须用实际请求验证。[百炼接口说明](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions/)

`.env` 不提交 Git，程序不记录鉴权头或密钥。系统环境变量优先于 `.env`。没有凭证时，离线模式可运行；真实评测将相应项目记为未运行，不伪造模型记录。

先进行最小账号和模型接通检查，再运行真实场景：

```bash
python -m src.probe --output-dir examples/probe/run1
python -m src.cli --mode real --profile single --input examples/inputs/normal.json --output-dir examples/real/demo
python -m src.evaluate --mode real --profile single --output-dir examples/real/acceptance
```

上述命令需要本地凭证。已保存的实测结果见本页表格；新运行的结果须以新目录的实际输出为准。

模型分工：`single` 的 P3/P4/P5 全部用 Plus；`split` 的 P3 使用 Flash，P4/P5 使用 Plus。Flash 的 P3 失败、结构错误或改动受保护字段时，可在同一预算内回退到 Plus 一次。不会静默替换模型快照。

## 选择资料与运行边界

CLI 默认加载 `data/variants/single_source.json`。要运行冲突资料，显式指定快照：

```bash
python -m src.cli --mode mock --input examples/inputs/conflict.json --corpus data/variants/conflict.json --output-dir examples/mock/conflict-demo
```

| 参数 | 用途 |
|---|---|
| `--question` / `--input` | 直接问题或 JSON 文件，二选一 |
| `--corpus` | 指定合成文档快照 |
| `--profile single\|split` | 全 Plus 或 Flash＋Plus |
| `--retrieval-mode original\|dual` | 单 Query BM25 或最多两路 Query 融合 |
| `--max-model-calls` | 全阶段共享的模型请求上限，默认 8 |
| `--max-tool-calls` | 业务工具分发上限，默认 6 |
| `--fault-file` | 仅用于测试的工具故障 JSON；不进入在线问题 |

故障配置形状为 `{"tool":"read_document","doc_id":"D01","times":1}`，`times` 可为 `"always"`。工具返回超时观察，由模型决定后续动作。批量评测已为 C06/C07 配置相应故障，无须手动创建文件。

输入仅允许 `question` 和可选 `history`；历史消息仅允许 `user`、`assistant` 的文本。标准答案、用例 ID、故障配置和预期动作由评测侧保存，不能混入模型输入。

## 评测与对照

```bash
python -m src.evaluate --mode mock --compare-retrieval --output-dir examples/mock/retrieval-demo
python -m src.evaluate --mode real --compare-models --compare-retrieval --repeat 2 --output-dir examples/model_comparison/run1
# 只复核现有记录，不调用模型；输出目录必须是新目录
python -m src.recheck --input-dir examples/model_comparison/verified-01 --output-dir examples/rechecks/my-review
```

`--case C02 --case C06` 可选择部分用例；`--repeat 2` 可重复运行。模型对照保持资料、问题、提示词、预算与检索设置相同，比较 P3、端到端耗时、自动检查、回退及 token 用量。Mock 耗时不用于评价 Flash/Plus 速度。原始比较生成时尚未选择，文件保留 `selected_profile=null`；用户后续选型记录单独保存在文档，不改写历史结果。

C01—C09 覆盖六项题目验收及两种文档替换。C05 保存首轮实际回答，再将该回答拼入后续对话。C10 是确定性的 Mock 执行上限测试，真实套件中单独放在 `mock-only/` 下，不计入真实模型证据。

检索对照使用实际运行保存的 P3 Query 与语料快照，在相同 Top5 下比较原 Query 和双 Query 的 Hit@5、已标注证据覆盖；不预设双 Query 一定更好。引用支持性与冲突裁决仍需人工对照原文，自动通过不等于完成业务验收。P6 离线辅助模型评审当前未运行。

## 输出、Trace 与状态

每次运行保存 `input.json`、`output.json`、`trace.jsonl`、`trace-summary.md`、`corpus_snapshot.json`、`metadata.json` 和 `checks.json`。易读摘要由实际事件生成。批量评测另外保留 `runtime-checks.json`、`summary.json` 与 `mutation-comparisons.json`；多轮用例保存 `conversation.json`。

代表性真实记录：[正常路径 C01](examples/real/final-single-v4/repeat-1/C01/trace-summary.md)、[冲突查证 C02](examples/real/final-single-v4/repeat-1/C02/trace-summary.md)、[工具恢复 C06](examples/real/final-single-v4/repeat-1/C06/trace-summary.md)、[持续失败 C07](examples/real/final-single-v4/repeat-1/C07/trace-summary.md)、[文档替换对比](examples/real/final-single-v4/repeat-1/mutation-comparisons.json)。工具本身为本地函数，故障由评测注入；选择后续动作的是真实模型。

输出包含 `answer`、`citations`、`gaps`、`status`、`reason_code`、`follow_up_question`、`decision_summary`。引用包含文档 ID、版本日期、片段 ID 和连续原文摘录。Trace 记录实际请求模型与响应模型、工具参数、原始观察、简要依据、用量、耗时和剩余预算，不记录内部思维过程。

| 状态 | 含义 |
|---|---|
| `answered` | 当前证据支持核心回答 |
| `needs_clarification` | 缺少关键适用信息或存在未解决冲突，需要确认 |
| `insufficient_evidence` | 工具正常工作，但资料无法支持回答 |
| `tool_error` | 必要工具或模型服务失败，任务未完成 |
| `step_limit` | 达到统一调用边界，任务未完成 |
| `invalid_output` | 结构或引用校验未通过，有限修复后仍无法交付 |

CLI 对前三类状态退出码为 0，对 `tool_error`、`step_limit`、`invalid_output` 为 2。批量评测按用例预期判断，C10 正确触发上限可以通过自动检查；套件未运行项目返回 2，自动失败返回 1，自动检查通过返回 0。

## 已知限制

资料只有 8 份基础合成文档和一个可选公告，不能据此推断真实企业文档规模上的效果。开发与验收样例共享知识事实，结果属于功能/回归评测。引用原文存在不代表全部生成文本语义正确：v3 真实审阅发现未知范围、文件权威性和搜索覆盖的过度推断，已记录并定向修订提示词。持续工具失败的部分原始候选复述了未读数字，由引用校验与程序安全渲染拦截，不能把最终安全结果全部归功于模型。本人已认可展示的核心结果及限制说明，未声称逐条审阅全部Trace。最终v4仍在C03的decision_summary中出现“确认知识库无资料”的过度概括，两轮主答案均准确限定为本次未找到。P6 辅助模型评分、大规模独立测试和生产部署未做。

原始要求与方案逐字保存在 [docs/source-plan](docs/source-plan/README.md)。其中的旧阶段状态、Windows 路径及未包含的工业项目链接属于历史归档，当前实现与结果以本仓库现行文档为准。
