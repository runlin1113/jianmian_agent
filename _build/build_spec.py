# -*- coding: utf-8 -*-
"""生成《简面智能体·模块功能规格说明书 v0.1》"""
from docx import Document
from docx.shared import Pt, RGBColor, Cm
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

OUT = r"D:/凌润林/大三上学期/python/python期末大作业/简面智能体模块功能规格说明书 v0.1.docx"

doc = Document()

# ---------- 基础样式（中文字体）----------
style = doc.styles['Normal']
style.font.name = 'Microsoft YaHei'
style.font.size = Pt(10.5)
rpr = style.element.get_or_add_rPr()
rfonts = rpr.get_or_add_rFonts()
rfonts.set(qn('w:eastAsia'), 'Microsoft YaHei')

for sname in ['Heading 1', 'Heading 2', 'Heading 3', 'Title']:
    try:
        st = doc.styles[sname]
        st.font.name = 'Microsoft YaHei'
        st.element.get_or_add_rPr().get_or_add_rFonts().set(qn('w:eastAsia'), 'Microsoft YaHei')
    except Exception:
        pass

# 页面 A4 边距
sec = doc.sections[0]
sec.page_width = Cm(21.0)
sec.page_height = Cm(29.7)
sec.left_margin = Cm(2.2)
sec.right_margin = Cm(2.2)
sec.top_margin = Cm(2.0)
sec.bottom_margin = Cm(2.0)


def set_cn(run, name='Microsoft YaHei'):
    run.font.name = name
    r = run._element.get_or_add_rPr().get_or_add_rFonts()
    r.set(qn('w:eastAsia'), name)


def para(text, size=10.5, bold=False, color=None, before=4, after=4, align=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(before)
    p.paragraph_format.space_after = Pt(after)
    if align:
        p.alignment = align
    r = p.add_run(text)
    r.font.size = Pt(size)
    r.bold = bold
    if color:
        r.font.color.rgb = RGBColor(*color)
    set_cn(r)
    return p


def h1(text):
    p = doc.add_heading(level=1)
    r = p.add_run(text); set_cn(r); r.font.size = Pt(15); r.bold = True
    return p

def h2(text):
    p = doc.add_heading(level=2)
    r = p.add_run(text); set_cn(r); r.font.size = Pt(13); r.bold = True
    return p

def h3(text):
    p = doc.add_heading(level=3)
    r = p.add_run(text); set_cn(r); r.font.size = Pt(11.5); r.bold = True
    return p


def kv_table(rows):
    t = doc.add_table(rows=0, cols=2)
    t.style = 'Light Grid Accent 1'
    t.alignment = WD_TABLE_ALIGNMENT.LEFT
    for k, v in rows:
        cells = t.add_row().cells
        cells[0].text = ''
        cells[1].text = ''
        rk = cells[0].paragraphs[0].add_run(k); set_cn(rk); rk.bold = True; rk.font.size = Pt(10)
        rv = cells[1].paragraphs[0].add_run(v); set_cn(rv); rv.font.size = Pt(10)
    return t


def feat_table(features):
    t = doc.add_table(rows=1, cols=5)
    t.style = 'Light Grid Accent 1'
    hdr = t.rows[0].cells
    for i, htext in enumerate(['编号', '功能点', '说明', '优先级', '验收标准']):
        rr = hdr[i].paragraphs[0].add_run(htext); set_cn(rr); rr.bold = True; rr.font.size = Pt(9.5)
    for fid, name, desc, prio, acc in features:
        c = t.add_row().cells
        vals = [fid, name, desc, prio, acc]
        for i, v in enumerate(vals):
            rr = c[i].paragraphs[0].add_run(v); set_cn(rr); rr.font.size = Pt(9.5)
            if i == 3:
                rr.bold = True
    return t


# ===================== 封面 / 文档控制 =====================
tp = doc.add_paragraph(); tp.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = tp.add_run('简面智能体'); set_cn(r); r.font.size = Pt(26); r.bold = True
tp2 = doc.add_paragraph(); tp2.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = tp2.add_run('模块功能规格说明书'); set_cn(r); r.font.size = Pt(20); r.bold = True
tp3 = doc.add_paragraph(); tp3.alignment = WD_ALIGN_PARAGRAPH.CENTER
r = tp3.add_run('Module Functional Specification  v0.1'); set_cn(r); r.font.size = Pt(11); r.font.color.rgb = RGBColor(0x66,0x66,0x66)

doc.add_paragraph()
kv_table([
    ('文档名称', '简面智能体·模块功能规格说明书'),
    ('版本', 'v0.1（基线）'),
    ('文档 Owner', 'PM / 产品负责人（成员 A 兼任或单独指派）'),
    ('适用范围', '前端表现域、智能体域、平台域共 14 个模块'),
    ('关联文档', '《简面智能体项目策划书》《两周实施计划与分工表》'),
    ('变更流程', '任何模块规格变更须提交 PR 并经 PM 评审后冻结'),
    ('冻结节点', 'D2 冻结 L1 基线；D7 智能体域评审；D13 验收评审'),
])

# ===================== 1. 引言 =====================
h1('1. 引言')
h2('1.1 目的')
para('本文档是简面智能体项目的单一事实来源（Single Source of Truth），定义各模块的功能边界、功能点、输入输出契约、依赖与验收标准，作为前端（成员 A）与后端/AI（成员 B）协同开发与验收的依据。')
h2('1.2 范围')
para('覆盖从现有单文件 HTML 简历编辑平台升级为"简历智能体"的全部模块，包含表现域 5 个、智能体域 7 个、平台域 2 个模块。不包含部署运维手册与上线推广计划（见关联文档）。')
h2('1.3 术语')
kv_table([
    ('模块', '具备独立职责与边界的功能单元，编号 M1–M14'),
    ('功能点', '模块内可独立验收的最小能力，编号 F1、F2…'),
    ('优先级 P0/P1/P2', 'P0 必须交付；P1 应交付；P2 可延后'),
    ('延用设计', '前端表现域严格沿用现有 index.html 的结构、主题变量与 A4/打印 CSS，仅增量叠加'),
])

# ===================== 2. 文档体系与模块全景 =====================
h1('2. 文档体系与模块全景')
para('项目文档按企业级分层组织，本文档为 L1（模块功能规格）。')
h3('2.1 文档分层')
kv_table([
    ('L0 项目章程', '总体设计 / 策划书（目标、市场、技术方案）'),
    ('L1 模块功能规格（本文档）', '各模块功能点、契约、验收——开发依据'),
    ('L2 接口契约', '前端↔代理协议、意图→工具协议、提示词协议'),
    ('L3 数据模型', '8 类模块 schema、用户档案、记忆结构'),
    ('L4 测试与验收', '用例、联调报告、公测结论'),
])
h3('2.2 模块全景（域 → 模块）')
t = doc.add_table(rows=1, cols=4); t.style = 'Light Grid Accent 1'
for i, htext in enumerate(['域', '模块编号', '模块名称', '核心职责']):
    rr = t.rows[0].cells[i].paragraphs[0].add_run(htext); set_cn(rr); rr.bold = True; rr.font.size = Pt(9.5)
panorama = [
    ('表现域', 'M1', '模块编辑引擎', '8 类模块增删改、字段校验、排序、头像'),
    ('表现域', 'M2', '主题系统', '6 套主题切换与持久化'),
    ('表现域', 'M3', 'A4 分页与打印导出', 'A4 版式预览、打印样式、导出'),
    ('表现域', 'M4', '本地持久化', '本地存储、草稿、JSON 导入导出'),
    ('表现域', 'M5', '对话式构建 UI', '聊天面板、意图入口、结果回填'),
    ('智能体域', 'M6', '意图路由与编排', '识别 5 类意图、任务规划、校验'),
    ('智能体域', 'M7', '单模块润色与填充', '字段改写、空模块补全'),
    ('智能体域', 'M8', '整体一页压缩', '按档位压缩、一页重排'),
    ('智能体域', 'M9', '简历解析导入', 'PDF/文本 → 8 类模块映射'),
    ('智能体域', 'M10', '岗位知识库检索', 'JD 检索/联网、匹配建议'),
    ('智能体域', 'M11', '模拟面试官', '追问序列、评分反馈'),
    ('智能体域', 'M12', '记忆模块', '用户档案、跨会话记忆'),
    ('平台域', 'M13', '服务层代理 /api/chat', '密钥托管、CORS、限流、配额'),
    ('平台域', 'M14', '模型接入层', 'DeepSeek 适配、提示词、重试'),
]
for d, mid, name, duty in panorama:
    c = t.add_row().cells
    for i, v in enumerate([d, mid, name, duty]):
        rr = c[i].paragraphs[0].add_run(v); set_cn(rr); rr.font.size = Pt(9.5)

# ===================== 3. 模块规格 =====================
h1('3. 模块功能规格')

# ---- 数据驱动：模块定义 ----
MODULES = [
 dict(id='M1', name='模块编辑引擎', domain='表现域',
   overview='承载 8 类简历模块的内容录入与结构管理，基于单文件 HTML 渲染，无框架、无构建。是用户操作简历的主体界面。',
   goals=['提供结构化、低门槛的简历录入体验','保证 8 类模块字段与既有数据兼容'],
   out=['不做 AI 润色（交由 M7）','不做版面导出（交由 M3）'],
   features=[
     ('F1','8 类模块增删改','基本信息/肖像/教育/项目/实习/技能/荣誉/自我评价 的增、删、改', 'P0','8 类模块均可独立新增、编辑、删除且不影响其余模块'),
     ('F2','字段级实时校验','电话、邮箱格式校验与友好提示', 'P1','非法格式实时标红提示，不阻断输入'),
     ('F3','模块排序与折叠','模块上下排序、折叠收起', 'P1','排序即时生效并随持久化保存'),
     ('F4','头像上传与本地预览','image 类型字段上传与预览', 'P0','支持常见图片格式，预览即时显示'),
     ('F5','空模块容错','空模块在导出时自动跳过', 'P1','导出 PDF 不含空白模块占位'),
   ],
   inp='用户表单输入；M4 提供的持久化数据',
   outp='内存 state（简历数据结构）；触发 M4 保存',
   deps='依赖 M4 持久化、M2 主题样式、M3 导出',
   exc='超大文本截断提示；图片超限提示并拒绝'),

 dict(id='M2', name='主题系统', domain='表现域',
   overview='管理简历预览的视觉主题，提供 6 套预设主题，通过 body class 与 CSS 变量驱动整体配色。',
   goals=['提供差异化视觉风格','主题切换零刷新、即时生效'],
   out=['不修改模块结构，仅切换表现层'],
   features=[
     ('F1','6 套主题切换','navy/rose/amber/emerald/violet/teal', 'P0','6 套主题均可一键切换'),
     ('F2','即时生效','切换仅变更 body class 与 CSS 变量', 'P0','切换无页面刷新、无闪烁'),
     ('F3','主题持久化','主题选择随本地存储保存', 'P1','重新打开恢复上次主题'),
   ],
   inp='用户主题选择',
   outp='body class（theme-xxx）+ CSS 变量',
   deps='依赖 M4 持久化',
   exc='未知主题回退至 navy 默认'),

 dict(id='M3', name='A4 分页与打印导出', domain='表现域',
   overview='将简历内容按 A4 版式实时渲染，并提供打印/导出能力，保证"所见即所得"的纸质交付。',
   goals=['A4 版式精确还原','一键打印/导出'],
   out=['不做内容生成，仅负责排版呈现'],
   features=[
     ('F1','A4 实时预览','编辑时同步呈现 A4 版式', 'P0','预览与打印版式一致'),
     ('F2','打印样式','@media print 控制分页与边距', 'P0','打印无多余 UI 元素'),
     ('F3','一键导出/打印','调用浏览器打印', 'P0','可生成 PDF'),
     ('F4','超页处理','内容超一页时自动分页或提示', 'P1','用户可预判页数'),
   ],
   inp='M1 产出的 state',
   outp='打印视图 / 浏览器 PDF',
   deps='依赖 M1 数据、M2 主题',
   exc='极长内容提示用户精简'),

 dict(id='M4', name='本地持久化', domain='表现域',
   overview='负责简历数据与用户偏好的本地存储，保障刷新不丢失、可迁移。',
   goals=['自动保存、防丢失','支持数据迁移'],
   out=['不做云端同步（本期范围外）'],
   features=[
     ('F1','自动保存','编辑即写入本地存储', 'P0','刷新后数据完整恢复'),
     ('F2','草稿/多版本','保存历史草稿', 'P1','可回退至历史版本'),
     ('F3','JSON 导入导出','整体简历导入导出', 'P1','可跨设备迁移'),
   ],
   inp='各模块写入的 state',
   outp='本地存储记录',
   deps='被 M1/M2/M3 依赖',
   exc='存储配额满时提示清理'),

 dict(id='M5', name='对话式构建 UI', domain='表现域（新增）',
   overview='在延用现有 UI 风格的前提下，新增聊天面板，作为用户与智能体交互的入口，并将工具结果回填至对应模块。',
   goals=['自然语言驱动简历构建','结果可确认、可撤销'],
   out=['不做意图识别算法（交由 M6）','不直连模型（经 M13）'],
   features=[
     ('F1','聊天面板嵌入','风格与现有界面一致', 'P0','视觉融入现有布局'),
     ('F2','意图入口','自然语言 → 动作触发', 'P0','可识别润色/压缩/解析/面试等意图'),
     ('F3','结果回填','工具结果写回对应模块', 'P0','回填后用户可见并确认'),
     ('F4','流式展示','模型输出逐字呈现', 'P1','提升交互观感'),
     ('F5','确认与撤销','操作前确认、可撤销', 'P1','避免误覆盖'),
   ],
   inp='用户输入、M6 返回的结构化结果',
   outp='界面状态更新、模块回填',
   deps='依赖 M6 编排、M13 代理',
   exc='网络异常提示重试'),

 dict(id='M6', name='意图路由与编排', domain='智能体域',
   overview='智能体的"大脑"，识别用户意图、规划任务、选择工具并校验结果，是连接对话与能力层的枢纽。',
   goals=['准确路由 5 类意图','保证输出结构合法'],
   out=['不直接生成内容，仅编排工具'],
   features=[
     ('F1','意图识别','润色/压缩/解析/知识库/面试', 'P0','五类意图识别准确率达标'),
     ('F2','任务规划','单步或多步工具组合', 'P0','可串联 解析→润色→压缩'),
     ('F3','工具选择','按意图调用 M7–M11', 'P0','选择正确工具集'),
     ('F4','结果校验','JSON schema 校验', 'P0','非法结果拒绝并提示'),
   ],
   inp='用户指令、上下文记忆',
   outp='工具调用计划、结构化结果',
   deps='依赖 M12 记忆、M13 代理、M14 模型',
   exc='歧义意图反问澄清'),

 dict(id='M7', name='单模块润色与填充', domain='智能体域',
   overview='对单个字段或单个空模块进行 AI 改写与补全，是粒度最细的内容增强能力。',
   goals=['提升单点表达专业度','空模块可自动成稿'],
   out=['不跨模块统筹（交由 M8）'],
   features=[
     ('F1','字段改写 rewrite_field','按指令改写指定字段', 'P0','改写结果符合指令且通顺'),
     ('F2','空模块补全 fill_module','基于岗位补全空模块', 'P0','产出与岗位相关的内容'),
     ('F3','风格约束','专业/简洁等风格可控', 'P1','可指定语气与篇幅'),
   ],
   inp='模块字段 + 用户指令',
   outp='改写后的字段内容',
   deps='依赖 M14 模型、M13 代理',
   exc='内容为空时提示补充要点'),

 dict(id='M8', name='整体一页压缩', domain='智能体域',
   overview='将完整简历按指定档位压缩至一页 A4，保全关键信息，适配投递场景。',
   goals=['一页容纳核心信息','不丢失关键项目/奖项'],
   out=['不做版面渲染（交由 M3）'],
   features=[
     ('F1','档位压缩 compress_all','精炼480/适中760/详尽1200', 'P0','三档均可产出对应篇幅'),
     ('F2','一页重排','遵循 A4 约束', 'P0','结果可直接进 M3 导出'),
     ('F3','关键信息保全','项目/奖项/技能不丢', 'P0','压缩后核心模块完整'),
   ],
   inp='全模块 state + 档位',
   outp='压缩后的一页简历结构',
   deps='依赖 M14 模型、M13 代理',
   exc='极端超长提示用户先删减'),

 dict(id='M9', name='简历解析导入', domain='智能体域',
   overview='将已有 PDF 或纯文本简历解析为 8 类模块结构，降低从零录入成本。',
   goals=['高保真映射 8 类模块','解析结果可人工校正'],
   out=['不做原创生成，仅结构化提取'],
   features=[
     ('F1','PDF/文本解析','提取为 8 类模块', 'P0','主流简历可解析'),
     ('F2','置信度标注','低置信字段标记', 'P1','用户聚焦待校正项'),
     ('F3','人工校正','解析结果可编辑确认', 'P0','确认后写入 state'),
   ],
   inp='PDF / 文本简历文件',
   outp='8 类模块 state',
   deps='依赖 M1 编辑、M14 解析能力',
   exc='扫描版 PDF 提示识别率受限'),

 dict(id='M10', name='岗位知识库检索', domain='智能体域',
   overview='基于目标岗位 JD 检索（含联网）并给出简历匹配建议，让简历"对准岗位"。',
   goals=['岗位要求可检索','给出匹配与差距建议'],
   out=['不做简历改写（交由 M7）'],
   features=[
     ('F1','JD 检索 search_jd','内置库 + 联网检索', 'P0','可返回相关岗位要求'),
     ('F2','匹配建议','简历 vs 岗位差距', 'P0','输出可优化方向'),
     ('F3','JD 库管理','维护 ≥10 条岗位样本', 'P1','支持扩充'),
   ],
   inp='目标岗位名称 / JD 文本',
   outp='岗位要求、匹配建议',
   deps='依赖 M13 代理、M14 模型',
   exc='联网失败回退本地库'),

 dict(id='M11', name='模拟面试官', domain='智能体域',
   overview='基于用户简历与目标岗位生成面试追问并进行多轮对话，给出评分与反馈，作为投递前演练。',
   goals=['贴合简历与岗位的提问','提供可量化反馈'],
   out=['不做最终录用判断'],
   features=[
     ('F1','追问生成 generate_interview','基于简历+岗位', 'P0','问题有针对性'),
     ('F2','多轮追问','根据回答持续深入', 'P0','对话连贯'),
     ('F3','评分反馈','表达/经历/短板', 'P1','给出改进点'),
     ('F4','结束报告','汇总表现', 'P1','可导出复盘'),
   ],
   inp='简历 state + 目标岗位',
   outp='面试对话、评分报告',
   deps='依赖 M12 记忆、M14 模型',
   exc='空闲超时提示继续'),

 dict(id='M12', name='记忆模块', domain='智能体域',
   overview='沉淀用户档案（岗位偏好、项目库、表达偏好），实现跨会话复用，支撑"越用越懂你"。',
   goals=['跨会话记忆','隐私边界清晰'],
   out=['不存储敏感密钥'],
   features=[
     ('F1','用户档案沉淀','岗位/项目库/偏好', 'P0','可被 M6/M11 调用'),
     ('F2','跨会话读取','新会话恢复上下文', 'P0','无需重复输入背景'),
     ('F3','更新与遗忘','修正或清除记忆', 'P1','用户可控'),
     ('F4','隐私边界','不存 API Key 等敏感', 'P0','敏感信息隔离'),
   ],
   inp='交互中产生的用户事实',
   outp='结构化用户档案',
   deps='依赖 M4 持久化（或等效存储）',
   exc='存储异常不影响主流程'),

 dict(id='M13', name='服务层代理 /api/chat', domain='平台域',
   overview='Cloudflare Pages Function，承担密钥托管、CORS 消除、按 IP 限流与额度记录，是前端与模型之间的安全网关。',
   goals=['密钥不出服务端','限流与配额可控'],
   out=['不做内容生成'],
   features=[
     ('F1','密钥托管','OWNER_KEY 服务端保存', 'P0','前端不出现密钥'),
     ('F2','CORS 消除','同源代理模型请求', 'P0','前端无跨域报错'),
     ('F3','按 IP 限流','防止滥用', 'P0','超限返回友好提示'),
     ('F4','配额记录','KV/QUOTA 命名空间', 'P0','可统计用量'),
     ('F5','自备 Key 直连','Authorization 头透传', 'P1','自备 Key 不占站长额度'),
   ],
   inp='前端 POST（简历文本/指令）',
   outp='模型结构化结果',
   deps='依赖 M14 模型',
   exc='上游超时返回重试提示'),

 dict(id='M14', name='模型接入层', domain='平台域',
   overview='封装 DeepSeek /chat/completions（OpenAI 兼容），统一管理提示词、超时与重试，向上层提供稳定生成能力。',
   goals=['模型可替换','输出结构化可控'],
   out=['不做业务逻辑（交由 M6–M11）'],
   features=[
     ('F1','DeepSeek 适配','/chat/completions 调用', 'P0','兼容 OpenAI 消息格式'),
     ('F2','提示词版本管理','提示词可迭代', 'P1','支持回滚'),
     ('F3','超时与重试','网络抖动自愈', 'P0','失败自动重试'),
     ('F4','结构化约束','强制 JSON 输出', 'P0','便于 M6 校验'),
   ],
   inp='M13 转发的请求',
   outp='模型生成结果',
   deps='依赖外部 DeepSeek API',
   exc='额度耗尽返回明确错误'),
]

for m in MODULES:
    h2('%s %s（%s）' % (m['id'], m['name'], m['domain']))
    para(m['overview'])
    h3('目标')
    for g in m['goals']:
        para('· ' + g, before=0, after=0)
    h3('职责边界（不做什么）')
    for o in m['out']:
        para('· ' + o, before=0, after=0)
    h3('功能点清单')
    feat_table(m['features'])
    h3('输入 / 输出')
    kv_table([('输入', m['inp']), ('输出', m['outp'])])
    h3('依赖与接口')
    para(m['deps'])
    h3('异常处理')
    para(m['exc'])

# ===================== 4. 跨模块接口契约摘要 =====================
h1('4. 跨模块接口契约摘要')
h2('4.1 前端 → 代理')
para('前端（M5）以同源 POST 调用 /api/chat，请求体含指令与简历文本；代理（M13）注入 OWNER_KEY 后转发 M14；返回结构化 JSON 供 M6 校验、M5 回填。')
h2('4.2 意图 → 工具映射')
kv_table([
    ('润色', 'M7（单模块改写/补全）'),
    ('压缩', 'M8（整体一页压缩）'),
    ('解析导入', 'M9（PDF/文本 → 8 类模块）'),
    ('岗位对齐', 'M10（检索 + 匹配建议）'),
    ('模拟面试', 'M11（追问 + 评分）'),
])
h2('4.3 记忆读写接口')
para('M6/M11 在编排与面试时读取 M12 用户档案；交互中产生的新事实经 M12 写入，跨会话复用。')

# ===================== 5. 验收总表（P0 汇总） =====================
h1('5. 验收总表（P0 功能点）')
para('以下为必须交付的功能点，作为 D13 验收评审的通过门槛。')
p0 = [(m['id'], f[0], f[1]) for m in MODULES for f in m['features'] if f[3] == 'P0']
t = doc.add_table(rows=1, cols=3); t.style = 'Light Grid Accent 1'
for i, htext in enumerate(['模块', '功能点', '功能名称']):
    rr = t.rows[0].cells[i].paragraphs[0].add_run(htext); set_cn(rr); rr.bold = True; rr.font.size = Pt(9.5)
for mid, fid, fname in p0:
    c = t.add_row().cells
    for i, v in enumerate([mid, fid, fname]):
        rr = c[i].paragraphs[0].add_run(v); set_cn(rr); rr.font.size = Pt(9.5)

# ===================== 附录 =====================
h1('附录 A 前端模块真实字段（源自现有代码）')
field_data = [
    ('基本信息 basic', 'name 姓名 / phone 电话 / email 邮箱 / job 求职意向 / github 个人主页'),
    ('个人肖像 avatar', 'avatar 个人肖像（image 类型）'),
    ('教育背景 education', 'school 学校 / major 专业 / degree 学历 / time 就读时间 / course 主修课程·GPA'),
    ('项目经历 project', 'proj_name 项目名 / role 角色 / time 起止 / tech 技术栈 / desc 详情(STAR)'),
    ('实习经历 internship', 'company 公司 / position 职位 / time 在职 / desc 工作产出'),
    ('技能专长 skill', 'skills 技能清单（按熟练度分类）'),
    ('荣誉奖项 award', 'honor_name 奖项 / time 时间 / level 级别说明'),
    ('自我评价 summary', 'eval 核心竞争力 / 优势 / 驱动力'),
]
t = doc.add_table(rows=1, cols=2); t.style = 'Light Grid Accent 1'
for i, htext in enumerate(['模块', '字段（name 标识 · 中文标签）']):
    rr = t.rows[0].cells[i].paragraphs[0].add_run(htext); set_cn(rr); rr.bold = True; rr.font.size = Pt(9.5)
for mod, fld in field_data:
    c = t.add_row().cells
    rr = c[0].paragraphs[0].add_run(mod); set_cn(rr); rr.font.size = Pt(9.5)
    rr = c[1].paragraphs[0].add_run(fld); set_cn(rr); rr.font.size = Pt(9.5)

para('', before=6)
para('说明：主题色值为 navy #14365A / rose #9D174D / amber #B45309 / emerald #14532D / violet #4C1D95 / teal #0F5E66；压缩档位字数为 精炼480 / 适中760 / 详尽1200。以上均源自现有 index.html，规格书严格对齐，未做改动。', size=9, color=(0x66,0x66,0x66))

doc.save(OUT)
print('SAVED:', OUT)
print('模块数:', len(MODULES), ' P0功能点:', len(p0))
