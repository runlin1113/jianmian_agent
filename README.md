# 简面 · 简历编辑智能体（课程 Demo）

把「自然语言 → 可编辑简历」做成一条**可控、可审计、可回退**的链路：
AI 只产出**提案**，是否写入由你确认；数字与日期这类硬事实，AI 就算想改也改不动。

- 后端：FastAPI 模块化单体 + 自研有界状态图（附 LangGraph 同构适配器）
- 前端：原生 DOM 的 14 个 ES 模块（零构建、零 npm），A4 真实分页与打印；对话是主页，工作台只管编辑
- 模型：默认离线确定性适配器（无需 Key），可一键切 DeepSeek
- 测试：79 个用例，`pytest` 全绿（含 1 条端到端主链路用例 TC-001）

---

## 1. 现在能做什么

| 能力 | 入口 | 你能看到的行为 |
|---|---|---|
| 对话生成初稿 | 主页对话框 | 说一段素材 → 生成 3~8 个模块提案；素材缺信息时**先问**，不编造数字 |
| 局部改写 | 「把选课系统的详情写得更专业」 | 按标题/序号定位到唯一模块；只改表达，`300 名学生` 原样保留 |
| 逐项采纳 | 提案卡片 | 每项可勾选，服务端按选中项**整批原子应用**；失败整批不写 |
| 导入旧简历 | 对话框「＋ 导入旧简历」 | PDF/DOCX → 拆成模块候选（带把握度与来源块）→ 你勾选后才合并 |
| 压到一页 | 「帮我压缩到一页」 | 浏览器真实排版后回传页数/溢出像素 → 服务端据此再压缩或让你选 |
| 岗位调研 | 左栏「调研」 | 三档证据结论（已有证据/部分相关/暂无证据）+ 样本来源 + 明确免责声明 |
| 模拟面试 | 左栏「面试」 | 按主题逐轮追问（每题最多 2 次追问），结束给可引用原句的复盘 |
| 记忆 | 左栏「档案」 | 候选 → 确认 → 可更正 → 可遗忘（三种删除语义分别解释） |
| 本地优先 | 始终 | 简历主数据只在浏览器 localStorage；服务端**没有**简历库，只有 run 工作副本 |

预览是**真的 A4**（794×1123px，96dpi），不是等比截图：见 `apps/web/js/preview.js` 的分页算法。

### 界面取向：对话是主页，工作台只管编辑

界面分三层，各管一件事，不互相兼职：

| 层 | 位置 | 只负责 |
|---|---|---|
| 任务与历史 | 最左固定栏 | 面试 / 调研 / 工作台 / 档案四个入口、对话历史、个人设置 |
| 对话 | 主页 | 说一句话 → 看提案 → 逐项采纳 → 得到一份简历 |
| 工作台 | 「工作台」 | 改排版、改字段、调主题；不做面试、不做档案、不做岗位分析 |

主页**只有一句话、一个输入框、一个箭头**。没有插画、没有光斑、没有扫描线——
「简约」不是把装饰调淡，而是不放装饰。输入框右侧的发送键是一个描边圆形箭头，
不用蓝色实心块：那一点蓝留给真正需要被看见的地方（焦点环、选中态）。

一句话说完之后，助手出提案；采纳完，对话里落一张**简历卡**（段数 / 页数 / 版本号），
点它进工作台。工作台右侧面板底部是「让智能体修改」——原设计里那块 AI 润色，
现在直接把这句话带回对话，改完再回到提案里逐项确认。这条环线可以走任意多轮：

```
对话 → 提案 → 采纳 → 简历卡 → 工作台（手改 / 让智能体改）→ 回到对话 → …
```

颜色上把两套色**刻意分开**：`--brand` 是界面自己的蓝（固定），`--accent` 是简历主题色
（换主题只影响文档，不会把整个界面染成另一种颜色）。

动效克制：按钮只保留 hover 提色与 active 微缩，输入框聚焦给一圈极淡的品牌色光晕；
`prefers-reduced-motion` 下全部关闭。

---

## 2. 快速开始

```bash
python -m pip install -r requirements.txt
python run.py                 # → http://127.0.0.1:8000/
```

打开后就是**主页**：中间一句「好的简历，只用一面」，下面一个输入框。
说一句话（哪怕只是「你好」），三秒内就能拿到一份可编辑的简历结构；
左边四个入口分别去面试、调研、工作台、档案，下面是这次的对话历史。

演示参数（都不会覆盖你已有的本地简历）：

- `?demo=1` 载入示例简历并进对话页
- `?demo=1&nav=workspace` 直接进工作台（带示例简历）
- `?demo=1&auto=1` 自动跑一次改写，直接看到提案卡片
- `?q=我是大三…&go=1` 预填一句话并自动提交

切真实模型（可选）：

```bash
# Windows PowerShell
$env:JIANMIAN_MODEL_PROVIDER="deepseek"; $env:JIANMIAN_OWNER_KEY="sk-..." ; python run.py
```

也可以完全用自己的 Key：界面右下角勾选「用我的 Key」，Key 只经请求头传输、只在内存里，
不写 localStorage、不进日志、不进事件流。

### 三种部署档，同一份代码

| 档位 | 关键环境变量 | 说明 |
|---|---|---|
| 本地隐私档（默认） | `JIANMIAN_MODEL_PROVIDER=mock` | 不联网、零成本；解析与排版全本地 |
| 课程演示档 | `JIANMIAN_OWNER_KEY=sk-...` | 站长 Key + 有界内存 + 种子岗位库；带每日 token 预算 |
| 公开多人档 | `JIANMIAN_REQUIRE_BUDGET=1` + 共享 TTL 存储 | **需要**换掉内存实现并补 run 所有权/租约/CAS，见 `docs/decisions/0003` |

常用变量：`JIANMIAN_RATE_PER_MIN`、`JIANMIAN_DAILY_TOKENS`、`JIANMIAN_RUN_TTL`、
`JIANMIAN_MAX_TOOL_CALLS`、`JIANMIAN_WEB_SEARCH`。全部集中在 `jianmian/config.py`。

---

## 3. 目录与分层

```
jianmian/
  domain/        规则只有一份：模块注册表、文档与命令、事实守卫、提案、迁移、岗位、面试、记忆
  ports/         端口：ModelProvider / ParserAdapter / SearchProvider / BudgetStore / RunStore
  adapters/      DeepSeek、离线 mock、pdf/docx 解析、本地岗位库、有界内存存储、预算
  workflows/     意图、工具注册表、有界状态图、编排入口、LangGraph 适配器
  application/   用例：run 生命周期、导入暂存、岗位匹配、面试、记忆、依赖装配
  api/           路由、会话、CSRF、限流、错误契约、安全头
  security/      会话签名、上传边界、SSRF 校验、限流桶、脱敏
  prompts/       版本化提示词与输出 Schema
apps/web/        index.html + css/app.css + js/{app,history,chat,editor,preview,state,imports,jobs,interview,profile,…}.js
knowledge/jobs/  带来源与日期的岗位种子样本
tests/           领域 / 安全 / API / 编排 四组测试
docs/decisions/  架构决策记录（ADR）
```

依赖方向是单向的：`api → application → workflows → domain`，`adapters` 只实现 `ports`。
换模型、换存储、换岗位源，只动 `adapters` 与 `config`。

---

## 4. 与架构书的对应关系

### M1—M14

| 规格模块 | 本工程落点 | 关键接口 / 扩展点 |
|---|---|---|
| M1 编辑引擎 | `domain/resume.py`、`domain/modules.py` | `ResumeDocument`、`ModuleSpec`、命令函数（copy-on-write + revision） |
| M2 主题 | `domain/modules.py: THEMES`、`preview.js` | 主题令牌只改 `--accent` 一族，加主题不改组件 |
| M3 A4 导出 | `apps/web/js/preview.js`、`css/app.css@print` | `render()/measure()`；打印用同一份 DOM/CSS |
| M4 本地存储 | `apps/web/js/state.js` | `Store.commit/undo/redo/exportJson`；迁移 `jianmian_studio_v1` |
| M5 对话 UI | `apps/web/js/chat.js` | SSE 事件、步骤时间线、提案逐项采纳、错误可重试提示 |
| 外壳 | `apps/web/js/app.js`、`js/history.js` | 四个入口的视图切换、本地对话历史、`guessTargetJob` |
| 工作台 | `apps/web/js/editor.js` | 模块库（注册表驱动）、已编辑列表、右侧字段编辑、让智能体修改 |
| M6 编排 | `workflows/{intents,tools,graph,engine}.py` | `AgentState`、`ToolRegistry`、五类入口 + build/edit/clarify 子意图 |
| M7 润色填充 | `workflows/tools.py: rewrite_field/build_draft` | 事实驱动；缺信息先追问 |
| M8 一页压缩 | `graph.compress_*`、`request_layout`、`resume_after_layout` | 三档字符预算、事实保护、真实页数反馈、有界重试 |
| M9 解析导入 | `application/imports.py`、`adapters/parser_*.py` | `ParseResult`/`DocumentBlock`；扫描件标 `needsOcr` |
| M10 岗位检索 | `application/jobs.py`、`adapters/search_local.py` | `SearchProvider`；来源、获取时间、样本声明、本地回退 |
| M11 模拟面试 | `application/interviews.py`、`domain/interview.py` | `InterviewSession`/`InterviewReport`；turnId 防重复推进 |
| M12 记忆 | `application/profile.py`、`domain/memory.py` | `MemoryCandidate`→`ConfirmedFact`；三种遗忘语义 |
| M13 服务代理 | `api/{middleware,guards,errors}.py`、`adapters/budget_memory.py` | 匿名签名会话、CSRF、限流、预算租约、BYOK 分账 |
| M14 模型 | `ports/model.py`、`adapters/model_*.py` | 能力表、超时、有限重试、`finish_reason=length` 截断标记 |

### R1—R7（原始说明书要求）

| 编号 | 要求 | 本 Demo 的可演示行为 |
|---|---|---|
| R1 | 延续八类模块、六主题、PDF 预览与导出 | 8 类模块 + 2 模板 + 6 主题；编辑即时预览；Ctrl+P 导出 |
| R2 | 自然语言生成 + 多轮迭代 | 对话产出模块；「第二个项目」只改那一个；刷新不丢（localStorage） |
| R3 | 记忆岗位/项目/偏好 | 候选需确认；可查看、更正、遗忘、导出 JSON |
| R4 | 岗位知识库与联网 | 带来源与获取时间的种子样本；联网开关默认关；失败自动回退本地 |
| R5 | 导入 PDF 拆解模块 | PDF/DOCX → 暂存区 → 逐条合并；扫描件明确提示校对 |
| R6 | 基于简历模拟面试 | 一问一答 + 追问 + 复盘（含原文引用与规则评分） |
| R7 | 类似扣子的工作流体验 | 步骤可见、等待确认、失败原因；图定义可被 LangGraph 执行（有对照测试） |

---

## 5. 关键设计取舍（为什么这么做）

**提案而不是直接改。** 模型输出永远是 `ChangeProposal`：`baseRevision + baseHash + operations`。
采纳时服务端重查版本、哈希、到期时间和 run 所有权，然后在一份副本上**整批**应用，任何一步失败整批不写。

**字段级事实策略。** 每个字段声明 `locked / guarded / open / asset`：
`locked` 的姓名、学校、公司、时间，AI 连写入权限都没有；`guarded` 的长文本允许改写，
但新增或删除数字/日期/金额/百分比会直接失败（`domain/facts.py`）。

**版面测量在浏览器，判断在服务端。** 页数和溢出不靠模型猜：浏览器真实排版后回传
`{pageCount, overflowPx, blockHeights, minFontPt, candidateHash}`，服务端据此决定再压缩还是让用户选。
字号低于 10.5pt 不会被当作「已压成一页」。

**本地优先不是口号。** 路由表里**没有** `POST /resumes`；简历正文只在浏览器。
服务端只保存 run 的工作副本，30 分钟过期后由后台清理任务真正删除。

**三处确定性优先于模型。** 意图识别、目标定位、字段守卫全是规则；规则拿不准就澄清，不让模型自由发挥。

---

## 6. 安全边界（做了什么 / 没做什么）

已实现：

- 匿名**签名会话**（HMAC，HttpOnly + SameSite=Lax），会话 ID 不可伪造
- CSRF 双提交 + Origin/Referer 同源校验；错误码 `csrf_failed` / `origin_rejected`
- 令牌桶限流（会话维度 + IP 维度），429 带 `retryAfter`
- 上传边界：magic bytes 校验、拒绝宏/旧版 doc、zip slip、zip bomb、10MB/20 页上限
- SSRF 防护：`assert_public_http_url` 拦截内网/云元数据/非 http 协议
- CSP（`script-src 'self'`、`connect-src 'self'`）、`nosniff`、`DENY` 框架嵌入、COOP
- 密钥隔离：模型 Key 只从环境或请求头进入，永不回传、不入库、不入事件；`security/redaction.py` 负责日志脱敏
- 统一错误体 `{code, message, requestId, retryable}`；堆栈与上游响应不出网

未实现（**有意**，写在这里避免误解）：

- 账号体系与云端简历同步（与本地优先冲突，需要单独设计）
- 多 worker 的 run 所有权/执行租约/确认 CAS（首版单实例内存实现，已留端口）
- 持久任务队列与隔离 OCR worker（扫描件走「提示 + 手动校对」路径）
- 任意 Base URL 的模型代理（只接受服务端白名单）
- 覆盖率统计与真实市场数据（岗位结论只针对本次检索到的样本）

---

## 7. 扩展点

| 想加什么 | 改哪里 | 不用改什么 |
|---|---|---|
| 新模块类型（如「论文发表」） | `domain/modules.py: MODULE_SPECS` 加一条 | 编排、提案校验、迁移、前端编辑器、预览都自动支持 |
| 新模型厂商 | 实现 `ports/model.py: ModelProvider` | 业务逻辑（能力表 + 契约测试通过即可） |
| 新解析器（如 Docling / OCR） | 实现 `ports/parser.py: ParserAdapter` | 导入服务只认 `ParseResult` |
| 新岗位来源 | 实现 `ports/search.py: SearchProvider` | 匹配与引用逻辑不变 |
| 新工具 | `workflows/tools.py` 注册 `ToolSpec` + 在 `ALLOWED_BY_INTENT` 声明权限 | 默认拒绝未注册/未授权的工具调用 |
| 换编排框架 | `workflows/langgraph_runner.py` 已给出同构示例 | 图定义与领域规则不动（有对照测试） |

---

## 8. 测试

```bash
python -m pytest            # 79 passed
python -m pytest tests/test_case_tc001.py -v -s   # 单跑主链路，打印逐步过程
python -m pytest tests/test_security.py -v
```

| 文件 | 覆盖 |
|---|---|
| `tests/test_domain.py` | 模块闭集、字段白名单、危险键、哈希稳定、事实守卫（新增/删除数字都拦住）、提案原子性、迁移丢 Key |
| `tests/test_security.py` | 会话伪造、CSRF 绑定、限流恢复、magic bytes、宏/zip slip/zip bomb、SSRF、脱敏 |
| `tests/test_api.py` | 契约 422、CSRF 403、越权 403、幂等重放与冲突、版本冲突 409、SSE 顺序与续传、澄清恢复、版面闭环、导入、岗位、面试轮次冲突、记忆确认与遗忘、过期清理、429 |
| `tests/test_workflows.py` | 意图分类表、标题/序号定位、工具权限边界、工具预算、步数上限、暂停、空提案拦截、LangGraph 对照 |
| `tests/test_case_tc001.py` | **TC-001 端到端主链路**：一句话 → 提案（不落地）→ 整批采纳（只 +1）→ 重复采纳幂等 → 第二轮改写 → 篡改文档 409 → 硬事实守恒 |

测试全程不打网络、不用真 Key、不写用户目录（岗位库落 `tmp_path`）。

---

## 9. 已知限制

- 首次加载字体未就绪时，版面测量可能偏 1–3px；打印前建议再看一眼预览。
- PDF 只读文本层；扫描件会提示「需要 OCR」，不强装成功。
- 面试评分是规则基线（可解释、可复现），不是「AI 打分」。
- 单实例内存存储：进程重启后活动 run 失效，前端草稿仍在本地，需要重建任务。
- 岗位样本是课程种子数据，只描述这批样本，不代表市场统计或薪资水平。

---

## 10. 文档索引

- `docs/decisions/0001-模块化单体而非微服务.md`
- `docs/decisions/0002-提案与本地优先.md`
- `docs/decisions/0003-内存运行态与多实例前置条件.md`
- `docs/decisions/0004-事实守卫的分层与边界.md`
- `docs/decisions/0005-自研有界图与-LangGraph-同构.md`
- `docs/decisions/0006-模型适配与密钥隔离.md`
- `docs/decisions/0007-第三方依赖与许可证台账.md`
- `docs/decisions/0008-界面-对话做主页-工作台只做编辑.md`

许可证：本项目为课程作业演示，第三方依赖见 `docs/decisions/0007-第三方依赖与许可证台账.md`。
