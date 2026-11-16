# -*- coding: utf-8 -*-
"""生成两页精简版策划书：简面智能体项目策划书（两页版）"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "简面智能体项目策划书（两页版）.docx")

INK = RGBColor(0x1A, 0x1A, 0x1A)
SUB = RGBColor(0x55, 0x55, 0x55)
ACC = RGBColor(0x2D, 0x6C, 0xDF)
LINE = RGBColor(0xD0, 0xD0, 0xD0)

doc = Document()

# 页边距：上下 1.9cm，左右 1.9cm，留出两页空间
sec = doc.sections[0]
sec.top_margin = Cm(1.9)
sec.bottom_margin = Cm(1.9)
sec.left_margin = Cm(1.9)
sec.right_margin = Cm(1.9)

# 默认字体：中文宋体，西文 Times
style = doc.styles["Normal"]
style.font.name = "宋体"
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
pf = style.paragraph_format
pf.line_spacing = 1.12
pf.space_after = Pt(2)
pf.space_before = Pt(0)


def set_cjk(run, name="宋体"):
    run.font.name = name
    r = run._element
    r.rPr.rFonts.set(qn("w:eastAsia"), name)


def H1(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(2)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(11.5)
    r.font.color.rgb = ACC
    set_cjk(r, "黑体")
    # 底部细线
    pPr = p._p.get_or_add_pPr()
    pbdr = pPr.makeelement(qn("w:pBdr"), {})
    bottom = pbdr.makeelement(qn("w:bottom"), {
        qn("w:val"): "single", qn("w:sz"): "6", qn("w:space"): "2", qn("w:color"): "2D6CDF"})
    pbdr.append(bottom)
    pPr.append(pbdr)
    return p


def H2(text):
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(1)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(10.5)
    set_cjk(r, "黑体")
    return p


def body(text, bold_lead=None):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(2)
    p.paragraph_format.first_line_indent = Pt(21)  # 2 字符缩进
    if bold_lead:
        r = p.add_run(bold_lead)
        r.bold = True
        set_cjk(r)
        r2 = p.add_run(text)
        set_cjk(r2)
    else:
        r = p.add_run(text)
        set_cjk(r)
    return p


def bullet(text):
    p = doc.add_paragraph(style="List Bullet")
    p.paragraph_format.space_after = Pt(1)
    p.paragraph_format.left_indent = Pt(18)
    r = p.add_run(text)
    set_cjk(r)
    return p


# ---------------- 封面标题 ----------------
t = doc.add_paragraph()
t.alignment = WD_ALIGN_PARAGRAPH.CENTER
t.paragraph_format.space_after = Pt(2)
r = t.add_run("简面智能体 · 项目策划书")
r.bold = True
r.font.size = Pt(18)
r.font.color.rgb = INK
set_cjk(r, "黑体")

sub = doc.add_paragraph()
sub.alignment = WD_ALIGN_PARAGRAPH.CENTER
sub.paragraph_format.space_after = Pt(6)
r = sub.add_run("面向求职者的 AI 简历编辑与面试准备智能体")
r.font.size = Pt(10.5)
r.font.color.rgb = SUB
set_cjk(r, "楷体")

# 一句话定位条
lead = doc.add_paragraph()
lead.alignment = WD_ALIGN_PARAGRAPH.CENTER
lead.paragraph_format.space_after = Pt(6)
r = lead.add_run("把“简历工具”升级为“简历智能体”——会对话、有记忆、能查岗、懂面试。")
r.italic = True
r.font.size = Pt(10)
r.font.color.rgb = SUB
set_cjk(r, "楷体")

# ---------------- 第一章 项目概述 ----------------
H1("一、项目概述")
H2("1. 名称与定位")
body("“简面”取“简洁的简历、简要的面试准备”之意。本项目在已有“简面”简历编辑平台基础上，引入智能体能力，定位为面向校招与社招求职者的 AI 简历构建与面试陪练工具：用户用自然语言描述经历，智能体负责结构化、量化与岗位对齐，并延伸出模拟面试。")
H2("2. 项目背景")
body("简历是求职的第一道门槛，但多数求职者不会把“做过的事”写成“可量化的结果”，也不了解目标岗位的真实要求。现有简历工具多为静态模板，缺乏语义理解与岗位对齐能力；通用大模型对话又难以沉淀个人经历、形成持续可用的个人档案。本项目填补“可记忆、可对齐、可陪练”的空白。")

# ---------------- 第二章 市场与需求 ----------------
H1("二、市场与需求")
H2("1. 目标用户")
bullet("校招学生：缺乏简历写作经验，需要结构引导与表达润色。")
bullet("社招转岗者：经历丰富但不会针对新岗位重新组织重点。")
bullet("求职辅导者：需要批量产出初稿与面试题库的轻量工具。")
H2("2. 核心痛点")
bullet("结构层：不知道一份完整简历由哪些部分构成。")
bullet("转化层：不会把职责描述成“动作 + 结果 + 数据”。")
bullet("对齐层：同一段经历投不同岗位，重点应完全不同。")
bullet("市场层：不了解目标岗位的真实职责与能力要求。")
H2("3. 需求优先级")
body("必备（MVP）：模块编辑、单模块润色、整体一页压缩。重要：简历解析导入、模拟面试官。可选：岗位知识库联网、团队协作。")

# ---------------- 第三章 产品方案 ----------------
H1("三、产品方案")
H2("1. 现有平台能力")
body("已上线平台为单文件 HTML 前端（无框架、无构建），内置 8 类模块（基本信息、教育、项目、实习、技能、奖项、自我评价、头像）、6 套主题、A4 分页打印导出，数据经 localStorage 本地持久化，并由 Cloudflare Pages Function 代理调用 DeepSeek 完成润色、压缩与面试题生成，支持用户自备 Key 免占站长额度。")
H2("2. 智能体五项能力升级")
bullet("对话式构建：用聊天代替表单，自然语言生成并回填模块。")
bullet("记忆：沉淀用户岗位、项目库与表达偏好，跨会话复用。")
bullet("知识库与联网：检索目标岗位 JD 与行业要求，做对齐建议。")
bullet("简历解析：解析现有 PDF/文本简历，自动映射为结构化模块。")
bullet("面试官：基于简历与目标岗生成追问式模拟面试与评分。")

# ---------------- 第四章 技术方案 ----------------
H1("四、技术方案")
body("采用“浏览器层—服务层—模型层”三层架构：前端只负责呈现与编辑，Pages Function 负责密钥托管、CORS 消除与按 IP 限流（KV 记录额度），模型层调用 DeepSeek /chat/completions（兼容 OpenAI 格式）承担三类生成任务。提示词工程以“字段约束 + 量化要求 + 岗位对齐”为核心，输出结构化 JSON 再回填界面；A4 分页与打印导出由前端 CSS 与浏览器打印实现；用户数据仅存本地，密钥不落地前端，兼顾隐私与合规。")

# ---------------- 第五章 实施计划 ----------------
H1("五、实施计划")
rows = [
    ("阶段", "周期", "交付物"),
    ("M1 夯实底座", "第 1–2 月", "对话式构建 + 记忆模块上线"),
    ("M2 联通外脑", "第 3–4 月", "简历解析 + 岗位知识库联网"),
    ("M3 闭环陪练", "第 5–6 月", "模拟面试官 + 评分反馈"),
    ("M4 打磨发布", "第 7–8 月", "主题美化、性能优化、公测"),
]
tbl = doc.add_table(rows=0, cols=3)
tbl.style = "Light Grid Accent 1"
tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
widths = [Cm(4.5), Cm(3.2), Cm(8.0)]
for i, row in enumerate(rows):
    cells = tbl.add_row().cells
    for j, val in enumerate(row):
        cells[j].width = widths[j]
        p = cells[j].paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        r = p.add_run(val)
        r.font.size = Pt(9.5)
        set_cjk(r, "黑体" if i == 0 else "宋体")
        if i == 0:
            r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        else:
            set_cjk(r, "宋体")

# ---------------- 第六章 价值与风险 ----------------
H1("六、价值与风险")
H2("1. 核心价值")
body("对个人：把“写简历”从耗时试错变为对话式产出；对平台：从一次性工具升级为可沉淀、可复用的智能体，提升留存与口碑。商业模式以免费基础功能 + 高级额度/团队版订阅为主。")
H2("2. 风险与合规")
bullet("模型依赖：锁定 OpenAI 兼容接口，可平滑切换备选模型。")
bullet("数据隐私：经历仅存用户本地，不主动上传。")
bullet("内容合规：AI 产出为辅助建议，用户自行核对真实性。")

doc.save(OUT)
print("saved:", OUT)
