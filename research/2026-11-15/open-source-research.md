# 简面智能体开源项目调研

调研日期：2026-11-15（Asia/Singapore）

本文件记录公开资料、仓库 README、许可证和当前项目源码的分析，没有移植上游应用代码，也未运行上游产品或做框架性能比较。表中 commit 来自成功读取的 Git 引用或仓库元数据，表示本次观测到的版本。较多 README 通过默认分支快照取回，不能据此保证它与另行观测的 commit 字节一致；具体文件的 URL、时间和 SHA-256 记录在资料清单中。没有成功通过 CDN 取回的文件，不计入已核实材料。

## 1. 结论

没有一个上游项目适合直接作为简面的底座：

- LangGraph、PydanticAI 和 OpenAI Agents SDK 解决的是智能体运行时，不包含简面已有的字段模型、A4 打印和中文简历事实保护。
- Reactive Resume、OpenResume、Resume Matcher 和 JobPilot 的产品能力更接近，但它们有各自的账号、数据库、模板或桌面技术栈，迁移成本大于复用现有简面内核。
- Docling、PDF.js、MarkItDown 适合作为解析适配器或本地库，而不是完整业务模块。
- Dify 和 Coze Studio 能验证“模型、知识库、插件、工作流、发布”的产品范式，但它们是重量级平台；Dify 还使用带额外条件的 Apache 2.0 修改许可，不能默认等同于普通 Apache 2.0。

推荐：借鉴接口和交互思想，自己的领域模型与安全边界保持独立；首版只接入 PDF.js 和一个服务端解析适配器，模型编排选 LangGraph，结构化对象使用 Pydantic。

## 2. 智能体框架

| 项目 | 调研依据 | 能借鉴什么 | 不直接采用的原因 | 许可证／状态 |
| --- | --- | --- | --- | --- |
| LangGraph | [README](https://github.com/langchain-ai/langgraph/blob/main/README.md)，源码资料中 commit `08a2016953789a4f579b4d36bd1967941ec62012` | 有状态图、可恢复执行、human-in-the-loop、短期／长期记忆、节点级可观察性 | 它只提供运行时；简历字段、提案事务和版面约束必须自己实现 | MIT；活跃 |
| PydanticAI | [README](https://github.com/pydantic/pydantic-ai/blob/main/README.md)，commit `f93bcff0c72caa0d5b0e2ead8b550d9674c8c9c4` | 结构化输出、工具参数校验、模型适配与 fallback、评测 | 更适合作为类型安全 agent SDK；本项目需要显式子图暂停和版面回路，首版避免同时引入两套运行时 | MIT；活跃 |
| OpenAI Agents SDK | [README](https://github.com/openai/openai-agents-python/blob/main/README.md)，commit `64fbde5d02b42ae5f9db668eb0184cdb3fc9d775` | 工具、handoff、guardrail、session、human-in-the-loop、tracing；官方明确支持多供应商 | 可以作为替代；本次优先显式状态图。仍需亲测 DeepSeek 兼容能力，并配置 tracing 隐私；不因“OpenAI”名称排除它 | MIT；活跃 |
| Agno | [README](https://github.com/agno-agi/agno/blob/main/README.md)，commit `7c3b729667e66282f0d845adbd507ee07242c5eb` | AgentOS 的 API、认证、审批、记忆、知识、durable execution 产品化视角 | 平台范围远超课程项目；不需要把通用 agent 平台搬进简面 | Apache-2.0；活跃 |
| Dify | [README](https://github.com/langgenius/dify/blob/main/README.md)，commit `61c8c3b2fed86b77da2ac9486e673852b7cea648`；[license](https://github.com/langgenius/dify/blob/main/LICENSE) | 可视化 workflow、插件、知识库、模型管理、发布 API | 运行与定制栈重；许可含多租户和前端品牌的附加条件，直接二开会引入产品和合规负担 | 修改版 Apache-2.0；活跃 |
| Coze Studio | [README](https://github.com/coze-dev/coze-studio/blob/main/README.md)，commit `fefb05ff27be1da939612fbf9faf5db62583b8ae` | 无代码／低代码 workflow、插件、知识库、模型服务、API／SDK；README 也明确提醒 Python 执行节点和 SSRF 风险 | Go + React + 微服务 DDD，部署最小要求高；其安全警告说明公开部署不能只靠平台默认值 | README 标示 Apache-2.0；许可证文件需按发布版本复核 |

### 选择含义

LangGraph 的状态图适合把 `parse → map → verify → propose → await_user → apply` 表达成可观测节点；它不会自动保护数据，所以 `ToolRegistry`、Pydantic Schema、事实检查和提案事务必须位于自己的领域层。Pydantic 的输出类型和参数校验应作为配套编程方式，而不是把校验责任交给模型。

Dify／Coze 的可视化工作流是产品灵感，不是首期技术依赖。简面先把固定工具步骤、事件和等待点做稳定，未来可以在同一 `ToolRegistry` 上加只读的流程可视化；不能因为“像扣子”就引入任意 Python 代码节点、插件下载或 shell 权限。

## 3. 简历产品与求职工具

| 项目 | 实际能力 | 对简面的启发 | 复用边界 |
| --- | --- | --- | --- |
| [Reactive Resume](https://github.com/AmruthPillai/Reactive-Resume) | MIT；编辑、实时 PDF、自动保存、最多 200 个 undo 步骤、版本、模板、AI Assistant 提案、岗位匹配、导入 PDF／Word／JSON、API／MCP、自托管 | “提议编辑 → 单项接受／拒绝”比整份替换更适合简历；版本和布局检查应该是编辑器一等概念 | 不搬 React／Hono／PostgreSQL／Better Auth；保留它的产品交互作为对照，自己的 `ChangeProposal` 只实现需要的最小集合 |
| [OpenResume](https://github.com/xitanggg/open-resume) | README 宣称本地浏览器运行、实时 PDF、PDF 导入和解析；TypeScript + React + Redux Toolkit + PDF.js + react-pdf；[LICENSE](https://github.com/xitanggg/open-resume/blob/main/LICENSE) 为 AGPL-3.0 文本 | 证明本地优先与 PDF 导入可以成为明确产品卖点；PDF.js 适合浏览器端第一步解析 | AGPL 会改变简面 MIT 发布与网络服务义务；只借鉴交互，不拷贝代码，依赖许可证必须单独登记 |
| [JobPilot](https://github.com/jlifeng/JobPilot) | Apache-2.0；Tauri 2 + React + TypeScript；本地 SQLite、WebDAV、OS Keyring；工具调用的精确 `replaceResumeText`；PDF／Markdown／JSON／图片导入；AI skill 包、面试和脱敏导出 | 精确文本 patch、技能能力包、密钥与正文分离、导出脱敏值得吸收；“局部应用”是本项目安全重点 | 不采用桌面 Tauri 作为当前 Web 平台底座；只实现浏览器本地的提案、脱敏导出和受控 prompt skill，不执行第三方 JS skill |
| [Resume Matcher](https://github.com/srbhr/Resume-Matcher) | Apache-2.0；FastAPI + Next.js + SQLite；master resume → JD tailoring；本地模型／多供应商；不让模型添加素材；ATS 分数和 PDF 解析为普通代码；面试准备与队列 | “真实素材约束”“ATS／PDF 反向读取”和非模型评分可以强化简面；队列说明重试和成本边界 | 它的模板、应用队列和后端结构可作对照；不直接复制，且不能把 ATS 分数包装成招聘预测 |
| [JD-Scout](https://github.com/AlanYy-42/JD-Scout) | MIT；LangGraph 四节点 workflow；Pydantic 结构化输出；Chroma RAG；简历证据引用；SSE 节点进度；失败重试和局限说明 | 岗位匹配结果必须带简历证据；进度按节点；明确上游不稳定与网站限制 | 只借鉴数据流和“Do NOT invent”约束；简面仍需自己的事实库和提案事务 |
| [AI Career Copilot](https://github.com/Programmergyt/ai-career-copilot) | README 描述 LangGraph + FastAPI + Vue；JD 分析、候选人抽取、缺口分析、HTML 渲染、面试；Redis 会话与 MySQL 持久化 | 说明对话、渲染和岗位分析可以合成一条工作流；调试面板应展示中间结构而非隐藏 | README 明确 Compose 依赖外部 MySQL／Redis，部署比简面复杂；本次未取得许可证，不作为可直接复用代码的来源 |

Reactive Resume 的 README 是本次最有价值的产品对照：它将 assistant 提案、版本、布局检查和数据管理放在编辑器旁边。简面不必复制它的完整 SaaS，而应在现有 `CFG + render + localStorage` 上抽取同样的“可审阅修改”交互。

## 4. 文档解析与版面

| 项目 | 依据与能力 | 简面中的定位 |
| --- | --- | --- |
| PDF.js | [README](https://github.com/mozilla/pdf.js/blob/master/README.md)，commit `d60bc7426aa0968d5b95ff8ca3a76dbc6ce23a3a`；Apache-2.0 | 浏览器 Worker 中读取文字块、页码和坐标；首选用于文本 PDF，减少上传正文 |
| Docling | [README](https://github.com/docling-project/docling/blob/main/README.md)，commit `440492ac0d0e14952b32dda28fede7495611c899`；MIT；支持 PDF／DOCX、版面、阅读顺序、表格、OCR、离线执行 | 服务端或本地隔离的复杂版面适配器；模型权重许可证另行核查；不把其 Markdown 输出直接当八类模块 |
| MarkItDown | [README](https://github.com/microsoft/markitdown/blob/main/README.md)，commit `ed178952a6672abdfd35b5f9e76a80b6cefc086e`；MIT；强调转成给 LLM 消费的 Markdown，并明确 untrusted input、I/O 权限与 URL 限制 | 轻量 DOCX／PDF 文本规范化备选；不作为人类高保真排版解析器；必须限制本地路径、URI、网络和插件 |
| react-pdf／Forme（上游产品中出现） | 只作为 Reactive Resume／OpenResume README 宣称的渲染技术记录 | 当前简面已有浏览器打印和 CSS 测量，首期不换渲染栈；先补真实版面反馈和分页回归 |

解析流程必须保留来源页、文字块和置信标记。Docling 能提供结构化文档表示不等于能正确判断“这一行是实习公司”；字段映射和人工校正仍是业务代码。扫描 PDF 的 OCR、模型权重和第三方云服务都有独立许可证、成本和留存条件。

## 5. 许可证与供应链清单

| 组件／仓库 | 已读取许可证结论 | 简面建议 |
| --- | --- | --- |
| 当前简面 | MIT，版权主体为凌润林；本地仓库 `LICENSE` | 保持 MIT；新增依赖逐个登记 |
| LangGraph、PydanticAI、OpenAI Agents、Reactive Resume、JD-Scout、Docling、MarkItDown | MIT | 可作为候选依赖或参考；保留版权、锁定版本并确认传递依赖 |
| Agno、Resume Matcher、PDF.js | Apache-2.0 | 保留适用的 LICENSE／NOTICE、锁定版本并确认传递依赖 |
| JobPilot | Apache-2.0，README 还说明包含 JadeAI 衍生工作并提供 NOTICE | 不能只看主项目许可证；若复制代码，必须阅读上游 NOTICE 和衍生条款 |
| OpenResume | AGPL-3.0 文本 | 不直接拷贝代码到当前 MIT 项目；如未来独立服务或链接使用，先做许可证审查 |
| Dify | 修改版 Apache-2.0，增加多租户和前端 LOGO／版权限制 | 不作为简面底座；不把“Apache-2.0”简化成无附加条件 |
| Coze Studio | README 标示 Apache-2.0；本次读取的默认分支未找到根 `LICENSE` 文件 | 使用前必须取指定 tag 的完整许可和依赖清单，不以 badge 作为充分依据 |
| OCR／embedding／VLM 权重 | Docling README 明确要求查原始包的模型许可证 | 单独建立模型权重台账，不能因为 Python 包是 MIT 就假定权重也是 MIT |

本调研没有将任何上游源码复制到应用目录。`research/2026-11-15` 下的脚本和资料只用于研究记录；正式实现前应以锁文件、指定 tag／commit 和实际运行路径重新审计许可证与漏洞。

## 6. 来源索引

- 项目说明材料抽取：`research/2026-11-15/简面智能体项目说明书.txt`、`简面智能体模块功能规格说明书 v0.1.txt`、`简面智能体项目策划书.txt`、`简面智能体·两周实施计划与分工表.txt`。
- 现有代码：`简面_简历编辑智能体/原简面平台/jianmian/index.html`、`functions/api/chat.js`、`wrangler.toml`、`README.md`、`LICENSE`。
- 官方资料缓存：`research/2026-11-15/branch_sources`、`official`、`verified`、`upstream`；每个已保存文件旁有 metadata 或采集记录，包含获取时间、URL 和 SHA-256（部分 upstream 项目因 API 限流只保存了 GitHub metadata）。失败的 `git_sources` 目录只留作采集错误记录，不是成功克隆的源码证据。
- LangGraph 官方 README 于本次调研中另存为 `research/2026-11-15/langgraph_readme.md`；LangGraph 官方概览页另存为 `langgraph_overview.html`。

## 7. 资料局限

GitHub API 在批量请求中触发匿名 rate limit；默认分支原始文件服务对部分仓库超时。因此上述报告只把实际读到的 README／LICENSE 内容作为具体证据，把无法取回的项目限于仓库元数据或公开搜索摘要，不把未核实的功能和许可证写成确定事实。版本、许可证、模型能力和供应商价格在真正接入前必须重新核对。
