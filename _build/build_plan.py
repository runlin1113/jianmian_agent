# -*- coding: utf-8 -*-
"""生成：简面智能体·两周实施计划与分工表.docx"""
import os
from docx import Document
from docx.shared import Pt, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.oxml.ns import qn
from docx.oxml import OxmlElement

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(os.path.dirname(HERE), "简面智能体·两周实施计划与分工表.docx")

INK = RGBColor(0x1A, 0x1A, 0x1A)
SUB = RGBColor(0x55, 0x55, 0x55)
ACC = RGBColor(0x2D, 0x6C, 0xDF)
HEADBG = "2D6CDF"
ALTBG = "EEF3FE"

doc = Document()
sec = doc.sections[0]
sec.top_margin = Cm(2.2)
sec.bottom_margin = Cm(2.2)
sec.left_margin = Cm(2.0)
sec.right_margin = Cm(2.0)

style = doc.styles["Normal"]
style.font.name = "宋体"
style.font.size = Pt(10.5)
style.element.rPr.rFonts.set(qn("w:eastAsia"), "宋体")
style.paragraph_format.line_spacing = 1.15
style.paragraph_format.space_after = Pt(2)


def set_cjk(run, name="宋体"):
    run.font.name = name
    run._element.rPr.rFonts.set(qn("w:eastAsia"), name)


def shade(cell, color):
    tcPr = cell._tc.get_or_add_tcPr()
    sh = OxmlElement("w:shd")
    sh.set(qn("w:val"), "clear")
    sh.set(qn("w:color"), "auto")
    sh.set(qn("w:fill"), color)
    tcPr.append(sh)


def title(text, size=16):
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    p.paragraph_format.space_after = Pt(4)
    r = p.add_run(text)
    r.bold = True
    r.font.size = Pt(size)
    r.font.color.rgb = INK
    set_cjk(r, "黑体")
    return p


def para(text, italic=False, color=None, size=10.5, after=4):
    p = doc.add_paragraph()
    p.paragraph_format.space_after = Pt(after)
    r = p.add_run(text)
    r.italic = italic
    if color:
        r.font.color.rgb = color
    r.font.size = Pt(size)
    set_cjk(r)
    return p


def make_table(headers, rows, widths, head_bg=HEADBG, alt=ALTBG, fs=9.5):
    tbl = doc.add_table(rows=1, cols=len(headers))
    tbl.style = "Table Grid"
    tbl.alignment = WD_TABLE_ALIGNMENT.CENTER
    # header
    hcells = tbl.rows[0].cells
    for i, h in enumerate(headers):
        hcells[i].width = Cm(widths[i])
        shade(hcells[i], head_bg)
        p = hcells[i].paragraphs[0]
        p.paragraph_format.space_after = Pt(0)
        p.paragraph_format.space_before = Pt(1)
        r = p.add_run(h)
        r.bold = True
        r.font.size = Pt(fs)
        r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        set_cjk(r, "黑体")
    # body
    for ri, row in enumerate(rows):
        cells = tbl.add_row().cells
        for ci, val in enumerate(row):
            cells[ci].width = Cm(widths[ci])
            if alt and ri % 2 == 1:
                shade(cells[ci], alt)
            p = cells[ci].paragraphs[0]
            p.paragraph_format.space_after = Pt(0)
            p.paragraph_format.space_before = Pt(1)
            p.paragraph_format.line_spacing = 1.05
            r = p.add_run(val)
            r.font.size = Pt(fs)
            set_cjk(r, "宋体")
    return tbl


# ---------------- 封面 ----------------
title("简面智能体 · 两周实施计划与分工表")
para("目标：14 天内完成“简面”从简历工具到简历智能体的升级，覆盖对话构建、记忆、解析、知识库与模拟面试。",
     italic=True, color=SUB, after=8)

# ---------------- 角色定义 ----------------
para("一、角色与分工说明", color=ACC, size=11.5).runs[0].bold = True
set_cjk(para("一、角色与分工说明", color=ACC, size=11.5).runs[0], "黑体") if False else None
para("下表按“角色”划分。若为单人开发，所有角色由你按阶段切换；若组队，可据角色直接指派负责人。",
     after=4)

make_table(
    ["角色", "职责范围", "主要交付"],
    [
        ["PM / 产品", "需求梳理、验收标准、节奏把控、文档定稿", "功能清单、验收口径、策划书定稿"],
        ["前端 FE", "单文件 HTML 改造、对话 UI、A4 导出与主题", "聊天面板、模块回填、打印预览"],
        ["服务端 BE", "Cloudflare Pages Function、KV 额度、联网检索", "代理加固、限流、检索接口"],
        ["模型/提示词 AI", "意图路由、工具提示词、岗位对齐", "提示词库、评分口径"],
        ["测试/文档 QA", "联调、用例、公测与说明", "测试报告、使用说明"],
    ],
    [2.6, 8.2, 5.2],
)

doc.add_paragraph().paragraph_format.space_after = Pt(2)

# ---------------- 任务表（核心） ----------------
para("二、任务分解与输入输出（按天排期）", color=ACC, size=11.5).runs[0].bold = True
set_cjk(para("二、任务分解与输入输出（按天排期）", color=ACC, size=11.5).runs[0], "黑体")

headers = ["#", "任务", "角色", "输入", "输出", "工期"]
rows = [
    ["1", "现有代码与需求梳理", "PM+FE",
     "现有平台代码、项目策划书",
     "功能清单 + 改造点文档（含字段 schema）", "D1–D2"],
    ["2", "服务层代理加固", "BE",
     "现有 /api/chat、KV 命名空间",
     "密钥托管 + IP 限流 + 额度记录（完善版）", "D1–D4"],
    ["3", "对话式构建框架", "FE+AI",
     "模块 schema、对话 UI 草图",
     "聊天面板 + 意图路由（前端骨架）", "D2–D5"],
    ["4", "工具协议与单模块润色", "AI+FE",
     "8 类模块字段定义、样本身历",
     "rewrite_field / fill_module 提示词 + 回填逻辑", "D3–D6"],
    ["5", "记忆模块", "FE",
     "用户档案结构（岗位/项目库/偏好）",
     "跨会话记忆存储与读取（localStorage 或 KV）", "D4–D7"],
    ["6", "整体一页压缩", "AI+FE",
     "全模块内容、A4 版式约束",
     "compress_all 提示词 + 一页重排结果", "D8–D9"],
    ["7", "简历解析导入", "FE+AI",
     "PDF / 文本简历样例（≥5 份）",
     "解析 → 8 类模块自动映射逻辑", "D8–D11"],
    ["8", "岗位知识库 / 联网检索", "AI+BE",
     "目标岗 JD 样例（≥10 条）",
     "search_jd 检索 + 岗位对齐建议", "D9–D12"],
    ["9", "模拟面试官", "AI+FE",
     "用户简历 + 目标岗位",
     "generate_interview 追问序列 + 评分反馈", "D10–D13"],
    ["10", "主题美化与 A4 导出打磨", "FE",
     "6 套主题、打印 CSS",
     "终版视觉 + 打印预览（无截断/无空白页）", "D11–D13"],
    ["11", "联调、测试与公测", "QA（你）",
     "全部已实现模块",
     "测试报告 + 公测链接 + 已知问题清单", "D12–D14"],
    ["12", "文档与交付", "PM",
     "成品、测试报告",
     "使用说明 + 策划书定稿 + 演示稿", "D13–D14"],
]
make_table(headers, rows, [0.8, 3.4, 1.8, 4.0, 4.4, 1.6], fs=8.8)

doc.add_paragraph().paragraph_format.space_after = Pt(2)

# ---------------- 周视图 ----------------
para("三、两周节奏总览", color=ACC, size=11.5).runs[0].bold = True
set_cjk(para("三、两周节奏总览", color=ACC, size=11.5).runs[0], "黑体")

make_table(
    ["周次", "重心", "关键里程碑（截止）", "风险缓冲"],
    [
        ["第 1 周\n(D1–D7)", "底座 + 对话",
         "D2 需求清单定稿；D4 代理加固；D7 记忆模块可用",
         "D5–D7 留 1–2 天应对提示词调参"],
        ["第 2 周\n(D8–D14)", "外脑 + 陪练",
         "D9 一页压缩；D11 解析导入；D13 面试官；D14 公测上线",
         "D12–D14 留 2 天集成测试与修 bug"],
    ],
    [2.2, 2.4, 8.0, 3.4],
    fs=9.2,
)

doc.add_paragraph().paragraph_format.space_after = Pt(2)
para("说明：以上工期以“单人并行推进、每天有效投入 4–6 小时”为基准；若组队分工，第 1 周 BE/AI 可与 FE 同步启动，整体可压缩约 30%。",
     italic=True, color=SUB, size=9.5)

doc.save(OUT)
print("saved:", OUT)
