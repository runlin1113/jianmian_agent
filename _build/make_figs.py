# -*- coding: utf-8 -*-
"""生成策划书插图：总体架构图、智能体分层图"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
from matplotlib import font_manager as fm
import os

for cand in ["C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"]:
    if os.path.exists(cand):
        fm.fontManager.addfont(cand)
plt.rcParams["font.sans-serif"] = ["Microsoft YaHei", "SimHei"]
plt.rcParams["axes.unicode_minus"] = False

INK = "#1F2933"
SUB = "#5B6770"
LINE = "#9AA5AE"
ACC = "#14365A"
ACC2 = "#9D174D"
SOFT = "#F2F4F6"


def box(ax, x, y, w, h, title, body="", fc="white", ec=LINE, tc=INK, fs=10.5, bfs=8.6, bold=True):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.004,rounding_size=0.020",
                       linewidth=1.1, edgecolor=ec, facecolor=fc, zorder=2)
    ax.add_patch(p)
    if body:
        ax.text(x + w / 2, y + h * 0.66, title, ha="center", va="center",
                fontsize=fs, color=tc, fontweight="bold" if bold else "normal", zorder=3)
        ax.text(x + w / 2, y + h * 0.30, body, ha="center", va="center",
                fontsize=bfs, color=SUB, linespacing=1.55, zorder=3)
    else:
        ax.text(x + w / 2, y + h / 2, title, ha="center", va="center",
                fontsize=fs, color=tc, fontweight="bold" if bold else "normal", zorder=3)


def arrow(ax, x1, y1, x2, y2, label="", style="-|>", color=ACC, ls="-", lw=1.1):
    ax.add_patch(FancyArrowPatch((x1, y1), (x2, y2), arrowstyle=style, mutation_scale=11,
                                 linewidth=lw, color=color, linestyle=ls,
                                 shrinkA=2, shrinkB=2, zorder=1))
    if label:
        ax.text((x1 + x2) / 2, (y1 + y2) / 2, label, ha="center", va="center",
                fontsize=8.0, color=SUB, bbox=dict(boxstyle="round,pad=0.25", fc="white", ec="none"), zorder=4)


def fig_arch(path):
    fig, ax = plt.subplots(figsize=(6.6, 4.9), dpi=300)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    L, W = 0.115, 0.77
    # 浏览器层
    box(ax, L, 0.750, W, 0.150, "浏览器层 ｜ 前端单文件应用",
        "单文件 HTML，无框架、无 CDN、无构建步骤\n模块编辑、A4 分页渲染、打印导出、localStorage 本地持久化",
        fc="white", fs=9.8, bfs=8.0)
    # 代理层
    box(ax, L, 0.495, W, 0.150, "服务层 ｜ Cloudflare Pages",
        "静态托管 index.html；Pages Function /api/chat 负责密钥托管\nCORS 消除与按 IP 限流；KV 命名空间 QUOTA 记录额度",
        fc=SOFT, ec=ACC, fs=9.8, bfs=8.0)
    # 模型层
    box(ax, L, 0.240, W, 0.150, "模型层 ｜ DeepSeek API",
        "/chat/completions 接口，兼容 OpenAI 消息格式\n承担单模块润色、整体一页压缩、面试题生成三类任务",
        fc="white", ec=ACC2, fs=9.8, bfs=8.0)

    # 纵向箭头 + 右侧标签
    arrow(ax, 0.345, 0.745, 0.345, 0.650, color=ACC)
    ax.text(0.370, 0.697, "POST 同源请求（简历文本）", ha="left", va="center", fontsize=8.0, color=SUB)
    arrow(ax, 0.645, 0.655, 0.645, 0.745, color=ACC, ls=(0, (4, 2)))
    ax.text(0.670, 0.697, "结构化 JSON 返回", ha="left", va="center", fontsize=8.0, color=SUB)

    arrow(ax, 0.345, 0.490, 0.345, 0.395, color=ACC2)
    ax.text(0.370, 0.442, "Bearer OWNER_KEY 转发", ha="left", va="center", fontsize=8.0, color=SUB)
    arrow(ax, 0.645, 0.400, 0.645, 0.490, color=ACC2, ls=(0, (4, 2)))
    ax.text(0.670, 0.442, "生成结果回传", ha="left", va="center", fontsize=8.0, color=SUB)

    ax.text(0.5, 0.155, "职责边界：前端只负责呈现与编辑，服务层只负责鉴权与限流，模型只负责生成，三者不互相越权。",
            ha="center", va="center", fontsize=8.2, color=SUB)

    fig.tight_layout(pad=0.2)
    fig.savefig(path, dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)


def fig_agent(path):
    fig, ax = plt.subplots(figsize=(6.9, 4.9), dpi=300)
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    # 左侧层名 + 右侧内容，纵向四层
    layers = [
        ("交互层", "对话输入　模块表单　A4 实时预览　结果确认与回填", 0.750, 0.150),
        ("编排层", "意图识别　→　任务规划　→　工具选择　→　结果校验", 0.550, 0.150),
        ("能力层", "fill_module　rewrite_field　compress_all　parse_resume\nsearch_jd　ask_user　generate_interview　render_preview", 0.330, 0.170),
        ("数据层", "会话状态　用户档案（岗位 / 项目库 / 表达偏好）　岗位知识库　历史版本", 0.110, 0.150),
    ]
    for name, body, y, h in layers:
        box(ax, 0.030, y, 0.145, h, name, fc=ACC, ec=ACC, tc="white", fs=10.2)
        box(ax, 0.215, y, 0.755, h, "", fc="white")
        ax.text(0.5925, y + h / 2, body, ha="center", va="center",
                fontsize=8.4, color=INK, linespacing=1.8, zorder=3)

    ax.text(0.030, 0.052, "说明：编排层不做固定工作流，按用户意图动态选择工具序列；数据层以结构化 JSON 为准，对话仅做增量修改。",
            ha="left", va="center", fontsize=8.0, color=SUB)

    fig.tight_layout(pad=0.2)
    fig.savefig(path, dpi=300, facecolor="white", bbox_inches="tight")
    plt.close(fig)


if __name__ == "__main__":
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "img")
    os.makedirs(out, exist_ok=True)
    fig_arch(os.path.join(out, "arch.png"))
    fig_agent(os.path.join(out, "agent.png"))
    print("done", out)
