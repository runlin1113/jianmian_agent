"""意图识别与目标定位（M6 的一部分）。

原则：
- **规则优先**：五类业务入口 + build/edit/clarify 子意图用确定性规则做，
  这样同一句话永远得到同一结果，也能被测试固定住（架构书要求业务分类 ≥95%）；
- 定位不到唯一目标时必须澄清，绝不猜着改（"错误写入为零"是硬指标）；
- 规则拿不准时，不做"让模型自由发挥"的兜底，而是返回 clarify。

`resolve_target` 只做"这句话指向哪些模块"的解析，不执行任何写入。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field as dc_field

from ..domain.modules import MODULE_BY_TYPE, MODULE_SPECS
from ..domain.resume import ResumeDocument

INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "interview": ("模拟面试", "面试官", "面试一下", "面试练习", "追问", "面试复盘", "练面试"),
    "job": ("岗位要求", "招聘要求", "jd", "JD", "市场", "匹配度", "匹配", "能力差距", "需要什么能力", "岗位需要"),
    "compress": ("一页", "压到", "压缩", "太长", "精简到", "装不下", "页数", "超页"),
    "import": ("导入", "上传", "解析我", "解析一下", "原来的简历", "旧简历", "pdf", "PDF", "word", "docx", "DOCX"),
    "build": ("从零", "生成一份", "帮我写一份", "写一份简历", "没有简历", "我是大", "我是大三", "想投", "想要一份"),
    "memory": ("记住", "忘记", "我的档案", "记忆", "我的经历你都"),
    "edit": ("润色", "优化", "改一下", "改成", "换成", "删掉", "删除", "去掉", "加一个", "新增",
             "补充", "移到", "放前面", "调换", "更专业", "更简洁", "重写", "替换"),
}

SUBTYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    #: 「不要」这类弱否定太容易误判（"不要改数字"不是删除），只收明确删除词
    "remove": ("删掉", "删除", "去掉", "移除", "不想要", "不要这个", "不要了", "拿掉"),
    "reorder": ("移到", "放前面", "放到前面", "调换", "顺序", "排到"),
    "appearance": ("主题", "颜色", "配色", "模板", "换成青色", "换成藏蓝", "换成粉色", "换主题"),
    "add": ("加一个", "新增", "补充一个", "再加"),
    "compress": ("压缩", "精简", "短一点", "一页"),
    "generate": ("生成", "写一份", "从零"),
}

TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "basic": ("基本信息", "联系方式", "个人信息"),
    "portrait": ("头像", "照片", "肖像"),
    "education": ("教育", "学校", "学历"),
    "project": ("项目", "project"),
    "internship": ("实习", "工作经历", "公司"),
    "skills": ("技能", "技术栈"),
    "honor": ("荣誉", "奖项", "奖"),
    "summary": ("自我评价", "个人评价", "优势"),
}

FIELD_KEYWORDS: dict[str, str] = {
    "项目详情": "desc",
    "项目描述": "desc",
    "详情": "desc",
    "描述": "desc",
    "工作内容": "desc",
    "技能清单": "skills",
    "技能": "skills",
    "自我评价": "eval",
    "主修课程": "course",
    "课程": "course",
    "获奖说明": "level",
    "求职意向": "job",
    "项目名称": "proj_name",
    "公司": "company",
    "职位": "position",
    "奖项": "honor_name",
}

_ORDINALS: dict[str, int] = {
    "第一个": 0, "第1个": 0, "第一": 0,
    "第二个": 1, "第2个": 1, "第二": 1,
    "第三个": 2, "第3个": 2, "第三": 2,
    "第四个": 3, "第4个": 3,
    "最后一个": -1, "最后": -1,
}

THEME_WORDS: dict[str, str] = {
    "藏蓝": "navy", "藏青色": "navy", "navy": "navy",
    "粉": "rose", "玫瑰": "rose", "rose": "rose",
    "橙": "amber", "暖阳": "amber", "amber": "amber",
    "绿": "emerald", "翡翠": "emerald", "emerald": "emerald",
    "紫": "violet", "魅影": "violet", "violet": "violet",
    "青": "teal", "青瓷": "teal", "teal": "teal",
}


@dataclass
class IntentResult:
    intent: str
    sub_intent: str = ""
    confidence: float = 0.6
    reason: str = ""
    module_ids: list[str] = dc_field(default_factory=list)
    module_types: list[str] = dc_field(default_factory=list)
    field: str = ""
    appearance: dict[str, str] = dc_field(default_factory=dict)
    needs_clarification: bool = False
    question: str = ""
    options: list[dict] = dc_field(default_factory=list)
    matched_keywords: list[str] = dc_field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "intent": self.intent,
            "subIntent": self.sub_intent,
            "confidence": round(self.confidence, 2),
            "reason": self.reason,
            "matched": self.matched_keywords,
            "moduleIds": self.module_ids,
            "field": self.field,
            "appearance": self.appearance,
            "needsClarification": self.needs_clarification,
        }


def _hits(text: str, words: tuple[str, ...]) -> list[str]:
    return [w for w in words if w in text]


def _has_content(document: ResumeDocument) -> bool:
    """简历里有没有用户真正写过的东西（空模块不算内容）。"""
    for module in document.modules:
        data = getattr(module, "data", {}) or {}
        if any(str(value or "").strip() for value in data.values()):
            return True
    return False


def classify(
    instruction: str, document: ResumeDocument | None = None, *, forced_intent: str | None = None
) -> IntentResult:
    text = (instruction or "").strip()
    if forced_intent and forced_intent in INTENT_KEYWORDS:
        # 用户从澄清选项里明确选了业务入口：不再猜测，直接采信
        result = IntentResult(
            intent=forced_intent,
            matched_keywords=["clarification_choice"],
            confidence=1.0,
            reason="用户从澄清选项中明确选择",
        )
        if forced_intent == "edit":
            result.sub_intent = "rewrite"
            _resolve_targets(text, document, result)
        elif forced_intent == "compress":
            _resolve_targets(text, document, result)
        return result
    if not text:
        return IntentResult(
            intent="clarify",
            confidence=1.0,
            reason="空指令",
            needs_clarification=True,
            question="想让我做什么？例如「帮我从这段素材生成简历」或「把第二个项目写得更专业」。",
        )

    scores: dict[str, list[str]] = {}
    for intent, words in INTENT_KEYWORDS.items():
        hits = _hits(text, words)
        if hits:
            scores[intent] = hits

    if not scores:
        # 空简历上的任何一句话都当作"给我一份简历"：新用户第一句话不该先被反问一轮。
        # 有内容却识别不出意图时才澄清，避免误改已有简历。
        if document is None or not _has_content(document):
            return IntentResult(
                intent="build",
                matched_keywords=["empty_document_default"],
                confidence=0.6,
                reason="简历还是空的：按「生成一份简历」处理",
            )
        return IntentResult(
            intent="clarify",
            confidence=0.5,
            reason="没有命中任何业务入口关键词",
            needs_clarification=True,
            question="我可以帮你：①从素材生成简历 ②润色/删除/排序 ③压到一页 ④导入旧简历 ⑤对齐岗位 ⑥模拟面试。你想先做哪一件？",
            options=[
                {"intent": "build", "label": "从素材生成简历"},
                {"intent": "edit", "label": "润色或修改某一处"},
                {"intent": "compress", "label": "压到一页"},
                {"intent": "job", "label": "看看岗位要求"},
            ],
        )

    # 优先级：更具体的业务入口优先于泛化的 edit
    priority = ["interview", "import", "compress", "job", "memory", "build", "edit"]
    intent = next((i for i in priority if i in scores), "edit")
    result = IntentResult(intent=intent, matched_keywords=scores[intent], confidence=0.9)

    if intent == "edit":
        for sub, words in SUBTYPE_KEYWORDS.items():
            if _hits(text, words):
                result.sub_intent = sub
                break
        else:
            result.sub_intent = "rewrite"

    # 主题切换是外观操作，不是文本润色
    if intent == "edit":
        for word, theme in THEME_WORDS.items():
            if word in text:
                result.appearance = {"theme": theme}
                result.sub_intent = "appearance"
                break

    if intent in {"edit", "compress"}:
        _resolve_targets(text, document, result)
    return result


def _resolve_targets(text: str, document: ResumeDocument | None, result: IntentResult) -> None:
    types = [mt for mt, words in TYPE_KEYWORDS.items() if _hits(text, words)]
    result.module_types = types

    for phrase, fname in FIELD_KEYWORDS.items():
        if phrase in text:
            result.field = fname
            break

    if document is None:
        return

    candidates = [m for m in document.sorted_modules() if not types or m.type in types]
    ordinal = next((idx for word, idx in _ORDINALS.items() if word in text), None)

    if ordinal is not None:
        if not candidates:
            result.needs_clarification = True
            result.question = f"简历里还没有{'、'.join(MODULE_BY_TYPE[t].zh for t in types) if types else '相关'}模块，要先新增吗？"
            return
        index = ordinal if ordinal >= 0 else len(candidates) - 1
        if index >= len(candidates):
            result.needs_clarification = True
            result.question = (
                f"你只说了「{next(w for w, i in _ORDINALS.items() if i == ordinal)}」，"
                f"但简历里只有 {len(candidates)} 个候选模块（"
                + "、".join(f"{i + 1}.{m.title}" for i, m in enumerate(candidates))
                + "）。指的是哪一个？"
            )
            result.options = [
                {"moduleId": m.id, "label": f"{i + 1}. {m.title}"} for i, m in enumerate(candidates)
            ]
            return
        result.module_ids = [candidates[index].id]
        result.confidence = 0.95
        return

    # 指令里直接点名的模块（不依赖"项目/实习"这类类型词）
    if document is not None:
        named_any = [m for m in document.sorted_modules() if m.title and m.title in text]
        if not types and len(named_any) == 1:
            result.module_ids = [named_any[0].id]
            result.confidence = 0.9
            return

    if types:
        # 单例类型天然唯一；多实例类型先看指令里有没有直接点名的标题
        if len(candidates) == 1:
            result.module_ids = [candidates[0].id]
            result.confidence = 0.9
        elif len(candidates) > 1:
            named = [m for m in candidates if m.title and m.title in text]
            if len(named) == 1:
                result.module_ids = [named[0].id]
                result.confidence = 0.92
                return
            result.needs_clarification = True
            labels = "、".join(f"{i + 1}.{m.title}" for i, m in enumerate(candidates))
            result.question = f"简历里有多个同类模块（{labels}），你要改哪一个？"
            result.options = [
                {"moduleId": m.id, "label": f"{i + 1}. {m.title}"} for i, m in enumerate(candidates)
            ]
        return

    # 没提类型也没提序号：只在简历仅有一个可写模块时才敢自动定位
    writable = [m for m in document.sorted_modules() if m.type not in {"basic", "portrait"}]
    if len(writable) == 1:
        result.module_ids = [writable[0].id]
        result.confidence = 0.75


def default_field_for(module_type: str) -> str:
    spec = MODULE_BY_TYPE.get(module_type)
    if spec and spec.ai_target:
        return spec.ai_target
    if spec:
        for f in spec.fields:
            if f.ai_editable:
                return f.name
    return ""


def all_module_types() -> list[str]:
    return [s.type for s in MODULE_SPECS]
