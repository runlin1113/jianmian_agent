"""离线确定性模型适配器（默认档，零成本、零联网）。

它的定位不是"假装有一个大模型"，而是把**可规则化的部分**确定性地做掉：
- 只从材料里抽取真实存在的实体，绝不再造数字/学校/公司；
- 润色只做安全变换（删套话、统一标点、动词开头），因此天然满足事实守卫；
- 需要真正的语义判断时，明确返回 `needs_model=True` 的降级提示。

这样课程演示不需要 API Key 也能跑完整链路，同时真实模型适配器可以随时替换它。
"""

from __future__ import annotations

import re
from typing import Any

from ..ports.model import (
    ModelCapabilities,
    ModelProvider,
    ModelRequest,
    ModelResult,
    ModelUsage,
    estimate_tokens,
)
from ..prompts.registry import prompt_version

SKILL_VOCAB: tuple[str, ...] = (
    "Python", "Java", "Go", "C++", "C#", "JavaScript", "TypeScript", "Rust", "PHP",
    "Flask", "Django", "FastAPI", "Spring Boot", "Vue", "React", "Next.js", "Node.js",
    "MySQL", "PostgreSQL", "SQLite", "Redis", "MongoDB", "Elasticsearch",
    "Linux", "Docker", "Kubernetes", "Git", "Nginx", "Celery",
    "PyTorch", "TensorFlow", "scikit-learn", "Pandas", "NumPy", "OpenCV",
    "机器学习", "深度学习", "数据分析", "数据挖掘", "爬虫", "算法", "NLP", "计算机视觉",
    "HTML", "CSS", "REST", "GraphQL", "gRPC", "单元测试", "CI/CD",
)

FILLER_WORDS: tuple[str, ...] = (
    "非常", "十分", "特别", "比较", "相当", "极为", "极其", "认真地", "努力地",
    "积极地", "主动地", "各种", "一些", "相关的", "相关的", "尽可能", "基本上",
    "说实话", "其实", "总的来说", "可以说",
)

_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_SCHOOL_RE = re.compile(r"([\u4e00-\u9fa5]{2,12}(?:大学|学院|职业学院|学校))")
_MAJOR_RE = re.compile(r"(?:专业|主修)[：: ]?\s*([\u4e00-\u9fa5A-Za-z]{2,20})")
_TIME_RE = re.compile(
    r"((?:19|20)\d{2}\s*[.\-/年]\s*\d{1,2}\s*[月.]?"
    r"(?:\s*[-—~至]\s*(?:(?:19|20)\d{2}\s*[.\-/年]\s*\d{1,2}\s*[月.]?|至今))?)"
)
_DEGREE_RE = re.compile(r"(本科|硕士|研究生|博士|专科|大专|学士)")
_HONOR_RE = re.compile(r"(国家奖学金|一等奖学金|二等奖学金|三等奖学金|校级奖学金|国家励志奖学金|"
                       r"[\u4e00-\u9fa5]{0,8}(?:一等奖|二等奖|三等奖|金奖|银奖|铜奖|冠军|亚军))")
_NAME_PATTERNS = (
    re.compile(r"姓\s*名[：:\s]*([\u4e00-\u9fa5·]{2,8})"),
    re.compile(r"我\s*叫\s*([\u4e00-\u9fa5·]{2,8})"),
)
_PROJECT_RE = re.compile(r"(?:项目|作品)[：: ]\s*([^\n，。；]{2,30})")
_COMPANY_RE = re.compile(r"(?:公司|实习)[：: ]\s*([^\n，。；]{2,30})")


def _clean(text: str) -> str:
    return re.sub(r"[ \t]+", " ", (text or "").replace("\r\n", "\n")).strip()


def strip_filler(text: str) -> str:
    out = text
    for word in FILLER_WORDS:
        out = out.replace(word, "")
    return out


def split_sentences(text: str) -> list[str]:
    parts = re.split(r"[。；;\n]+", text or "")
    return [p.strip(" ，,、") for p in parts if p.strip(" ，,、")]


def split_clauses(text: str) -> list[str]:
    """比句子更细一层：按逗号也切开，方便挑出"做过什么"。"""
    parts = re.split(r"[。；;，,\n]+", text or "")
    return [p.strip(" ，,、") for p in parts if p.strip(" ，,、")]


#: 表示"我做了事"的动词；`做过` 这类口语说法必须在内，否则"用 Flask 做过选课系统"会被漏掉
_ACTION_WORDS = (
    "开发", "实现", "设计", "搭建", "优化", "负责", "完成", "部署", "重构",
    "做过", "做了", "参与", "编写", "上线", "维护", "迁移", "接入",
)
#: 结果子句的引导词：紧跟动作子句时可一并带走
_RESULT_WORDS = ("服务", "支持", "提升", "降低", "减少", "承载", "覆盖", "达到", "缩短", "增长", "节省")


def pick_project_clauses(text: str) -> list[str]:
    """挑出"做了什么事"的子句，并带上紧随其后的结果子句。

    只做筛选，不做补写：每一句都能在材料里找到原话，
    所以既不会漏掉"做过 X"，也不会编出没写过的成果。
    """
    clauses = split_clauses(text)
    picked: list[str] = []
    for idx, clause in enumerate(clauses):
        if not any(word in clause for word in _ACTION_WORDS):
            continue
        picked.append(clause)
        nxt = clauses[idx + 1] if idx + 1 < len(clauses) else ""
        if nxt and nxt.startswith(_RESULT_WORDS) and nxt not in picked:
            picked.append(nxt)
    return picked[:4]


def _guess_project_name(text: str) -> str:
    """从"做过 X / 实现了 X"里取项目名；取不到就返回空，交给调用方兜底。"""
    hit = re.search(
        r"(?:做过|做了|开发了|实现了|搭建了|设计了|负责了?)\s*([\u4e00-\u9fa5A-Za-z0-9+#.]{2,18})",
        text or "",
    )
    return hit.group(1).strip() if hit else ""


def detect_skills(text: str) -> list[str]:
    low = (text or "").lower()
    hits: list[str] = []
    for skill in SKILL_VOCAB:
        if skill.lower() in low and skill not in hits:
            hits.append(skill)
    return hits


def extract_profile(materials: str) -> dict[str, Any]:
    """从材料里抽取**有明确出处**的字段；没抽到就留空。"""
    text = _clean(materials)
    profile: dict[str, Any] = {}

    for pattern in _NAME_PATTERNS:
        m = pattern.search(text)
        if m:
            profile["name"] = m.group(1)
            break
    if m := _PHONE_RE.search(text):
        profile["phone"] = m.group(1)
    if m := _EMAIL_RE.search(text):
        profile["email"] = m.group(0)
    if m := _SCHOOL_RE.search(text):
        profile["school"] = re.sub(r"^(?:就读于|毕业于|学校|在)", "", m.group(1)).strip()
    if m := _MAJOR_RE.search(text):
        profile["major"] = m.group(1).strip()
    if m := _DEGREE_RE.search(text):
        profile["degree"] = m.group(1)
    times = [t.strip() for t in _TIME_RE.findall(text) if t.strip()]
    if times:
        profile["time"] = times[0]
    honors = list(dict.fromkeys(_HONOR_RE.findall(text)))
    if honors:
        profile["honors"] = honors
    skills = detect_skills(text)
    if skills:
        profile["skills"] = skills
    if m := _PROJECT_RE.search(text):
        profile["project"] = m.group(1).strip()
    if m := _COMPANY_RE.search(text):
        profile["company"] = m.group(1).strip()
    return profile


def starter_modules(target_job: str = "") -> list[dict[str, Any]]:
    """结构模板：用户什么都没给时，给一份"能直接填"的骨架，而不是空屏或编造经历。

    这里的文字全部是可识别的占位提示（"项目名称""做了什么"），不冒充真实经历：
    用户看一眼就知道该往哪儿填。数字一律留空，避免和事实守卫打架。
    """
    return [
        {"type": "basic", "data": {"name": "你的姓名", "job": target_job or "求职意向"}},
        {
            "type": "education",
            "data": {"school": "学校名称", "major": "专业名称", "degree": "本科", "time": "起止时间"},
        },
        {
            "type": "project",
            "data": {
                "proj_name": "项目名称",
                "role": "你的角色",
                "time": "起止时间",
                "tech": "用到的技术或工具",
                "desc": "· 做了什么：一句话说清你的动作\n· 怎么做的：方法、工具、关键取舍\n· 结果如何：尽量给出可验证的数字",
            },
        },
        {"type": "skills", "data": {"skills": "技能一、技能二、技能三（按熟练度排序）"}},
        {"type": "summary", "data": {"eval": "两三句话：你是谁、最擅长什么、想在什么岗位上解决什么问题。"}},
    ]


def build_modules(materials: str, target_job: str) -> dict[str, Any]:
    profile = extract_profile(materials)
    text = _clean(materials)
    modules: list[dict[str, Any]] = []
    clarifications: list[dict[str, str]] = []

    basic: dict[str, str] = {}
    for key in ("name", "phone", "email"):
        if key in profile:
            basic[key] = str(profile[key])
    if target_job:
        basic["job"] = target_job
    for key, label in (("name", "姓名"), ("phone", "手机号"), ("email", "邮箱")):
        if key not in basic:
            clarifications.append({"field": key, "question": f"请提供你的{label}，我不会自己编一个。"})
    if basic:
        modules.append({"type": "basic", "data": basic})

    education: dict[str, str] = {}
    for key in ("school", "major", "degree", "time"):
        if key in profile:
            education[key] = str(profile[key])
    if education:
        course_bits = [s for s in split_sentences(text) if "课程" in s or "GPA" in s.upper()]
        if course_bits:
            education["course"] = "；".join(course_bits[:2])
        modules.append({"type": "education", "data": education})

    # 项目：只取包含动作或技术栈的子句，不生成不存在的成果
    tech = profile.get("skills", [])
    action_sents = pick_project_clauses(text)
    if action_sents:
        name = (
            profile.get("project")
            or _guess_project_name("；".join(action_sents))
            or (f"{target_job}相关项目" if target_job else "项目经历")
        )
        desc = "；".join(action_sents[:4])
        modules.append(
            {
                "type": "project",
                "data": {
                    "proj_name": name,
                    "role": _role_guess(text),
                    "time": profile.get("time", ""),
                    "tech": "、".join(tech[:6]),
                    "desc": desc,
                },
            }
        )

    if profile.get("company"):
        modules.append(
            {
                "type": "internship",
                "data": {
                    "company": profile["company"],
                    "position": _role_guess(text),
                    "time": profile.get("time", ""),
                    "desc": "；".join(s for s in action_sents[:2]),
                },
            }
        )

    if tech:
        modules.append({"type": "skills", "data": {"skills": "、".join(tech)}})

    if profile.get("honors"):
        for honor in profile["honors"][:3]:
            modules.append(
                {"type": "honor", "data": {"honor_name": honor, "time": profile.get("time", ""), "level": ""}}
            )

    # 自我评价只取含评价性动词的分句；整段照搬素材会把手机号也写进去
    summary_bits = [
        c
        for c in split_clauses(text)
        if any(word in c for word in ("熟悉", "擅长", "热爱", "专注于", "致力于"))
    ]
    if summary_bits:
        modules.append({"type": "summary", "data": {"eval": "；".join(summary_bits[:2])}})

    missing = []
    if not any(m["type"] == "project" for m in modules):
        missing.append("没有识别到项目经历，需要你补充做过什么、负责哪部分")
    if not tech:
        missing.append("没有识别到技术栈，建议补充具体工具和熟练程度")

    return {
        "modules": modules,
        "clarifications": clarifications,
        "missing": missing,
        # 供编排层判断"是否需要真实模型"
        "needs_model": False,
        "profile": {k: v for k, v in profile.items()},
    }


def _role_guess(text: str) -> str:
    for role in ("后端开发", "前端开发", "全栈", "算法", "数据分析", "产品", "测试", "运维"):
        if role in text:
            return role
    if "负责" in text:
        m = re.search(r"负责([\u4e00-\u9fa5]{2,10})", text)
        if m:
            return m.group(1)
    return ""


_RESULT_LEADS = (
    "支持", "实现", "降低", "提升", "提高", "达到", "服务", "覆盖", "解决", "优化",
    "减少", "缩短", "完成", "上线", "落地", "节省", "承载", "保障", "稳定",
)


def split_action_result(text: str) -> list[str]:
    """把一句话按「做法 → 结果」拆开；只在结果分句有明确引导词时才拆。

    纯排版变换：不改字、不增删事实，只是把"做法…，结果…"换成两行，
    读起来更接近 STAR。拆不动（没有结果分句）就原样返回一个元素。
    """
    clauses = [c.strip(" ，,。；;") for c in re.split(r"[，,；;]", text or "") if c.strip(" ，,。；;")]
    if len(clauses) < 2:
        return [text.strip()]
    groups: list[str] = []
    current = clauses[0]
    for clause in clauses[1:]:
        if clause.startswith(_RESULT_LEADS) and len(current) >= 4:
            groups.append(current)
            current = clause
        else:
            current = f"{current}，{clause}"
    groups.append(current)
    if len(groups) < 2 or len(groups) > 4 or any(len(g) < 4 for g in groups):
        return [text.strip()]
    return groups


def polish_text(text: str, *, module_type: str, field: str) -> dict[str, Any]:
    """安全润色：只做不引入新事实的变换。"""
    raw = _clean(text)
    if not raw:
        return {"after": "", "notes": []}
    notes: list[str] = []
    lines = [ln.strip() for ln in raw.split("\n") if ln.strip()]
    out_lines: list[str] = []
    for line in lines:
        original = line
        line = re.sub(r"^[-•*·]\s*", "", line)
        cleaned = strip_filler(line)
        cleaned = re.sub(r"通过使用", "基于", cleaned)
        cleaned = re.sub(r"使用([A-Za-z][\w.+#-]*)", r"基于\1", cleaned)
        cleaned = re.sub(r"进行([\u4e00-\u9fa5]{2})", r"\1", cleaned)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip(" ，,、")
        if cleaned != original:
            notes.append("压缩修饰语并统一动词开头")
        if cleaned and not cleaned.endswith(("。", "；", "！", "？")):
            cleaned += "。"
        out_lines.append(cleaned)
    if field == "desc" and len(out_lines) == 1:
        # 单行描述：如果能把「做法 / 结果」拆开，就拆成要点（可见的排版改进，不改字）
        split = split_action_result(out_lines[0])
        if len(split) > 1:
            out_lines = [s if s.endswith(("。", "！", "？")) else s + "。" for s in split]
            notes.append("按「做法 / 结果」拆成要点，便于快速扫读")
    if field == "desc" and len(out_lines) > 1:
        joined = "\n".join("• " + ln for ln in out_lines)
    else:
        joined = "；".join(x.rstrip("。") for x in out_lines) + "。"
    if len(lines) == 1 and len(out_lines) == 1:
        joined = out_lines[0]
    return {"after": joined, "notes": list(dict.fromkeys(notes)) or ["统一标点"]}


def compress_text(text: str, budget: int, protected_tokens: str = "") -> dict[str, Any]:
    """在保留数字/日期令牌的前提下压缩；压不下去就如实说压不下去。"""
    raw = _clean(text)
    if len(raw) <= budget:
        return {"after": raw, "dropped": [], "notes": ["已在预算内，无需压缩"]}

    protected = [t for t in re.findall(r"(?:19|20)\d{2}|\d+(?:\.\d+)?%?", protected_tokens) if t]
    lines = [ln.strip(" •-") for ln in raw.split("\n") if ln.strip()]
    kept: list[str] = []
    dropped: list[str] = []
    total = 0
    for line in lines:
        compact = strip_filler(line)
        compact = re.sub(r"通过使用", "基于", compact)
        compact = re.sub(r"使用([A-Za-z][\w.+#-]*)", r"基于\1", compact)
        if total + len(compact) <= budget:
            kept.append(compact)
            total += len(compact)
        else:
            # 只有不含受保护令牌的句子才允许被丢弃
            if any(tok in line for tok in protected):
                kept.append(compact)
                total += len(compact)
            else:
                dropped.append(line[:40])
    after = "\n".join(kept)
    if len(after) > budget * 1.15:
        return {
            "after": raw,
            "dropped": [],
            "notes": [f"在不删除受保护事实的前提下无法压到 {budget} 字（当前 {len(after)}）"],
            "unable": True,
        }
    return {"after": after, "dropped": dropped, "notes": [f"压缩至 {len(after)} 字"]}


_SECTION_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("basic", ("姓名", "电话", "邮箱", "求职意向", "@")),
    ("education", ("教育", "学校", "学历", "GPA", "主修", "课程")),
    ("project", ("项目", "开发", "实现", "系统", "平台")),
    ("internship", ("实习", "公司", "在职", "工作内容")),
    ("skills", ("技能", "熟练", "掌握", "工具")),
    ("honor", ("荣誉", "奖", "竞赛", "证书")),
    ("summary", ("自我评价", "个人优势", "兴趣爱好")),
)


def map_blocks(blocks: str) -> dict[str, Any]:
    """把 `页码|类型|文本` 形式的块列表映射到模块。"""
    modules: dict[str, dict[str, Any]] = {}
    pages: dict[str, list[int]] = {}
    unmapped: list[str] = []
    for line in (blocks or "").split("\n"):
        if not line.strip():
            continue
        page_str, _, rest = line.partition("|")
        kind, _, text = rest.partition("|")
        text = text.strip()
        if not text:
            continue
        page = int(page_str) if page_str.strip().isdigit() else 0
        target = None
        for module_type, keys in _SECTION_RULES:
            if any(k in text for k in keys):
                target = module_type
                break
        if target is None:
            unmapped.append(text[:60])
            continue
        bucket = modules.setdefault(target, {})
        pages.setdefault(target, []).append(page)
        if target == "basic":
            if m := _PHONE_RE.search(text):
                bucket.setdefault("phone", m.group(1))
            if m := _EMAIL_RE.search(text):
                bucket.setdefault("email", m.group(0))
            if m := _SCHOOL_RE.search(text):
                bucket.setdefault("school", m.group(1))
            name_part = re.sub(r"(电话|邮箱|手机).*$", "", text).strip(" ：:")
            if 2 <= len(name_part) <= 4 and re.fullmatch(r"[\u4e00-\u9fa5·]+", name_part):
                bucket.setdefault("name", name_part)
        elif target == "education":
            for key in ("school", "major", "degree", "time"):
                if key in bucket:
                    continue
                if key == "school" and (m := _SCHOOL_RE.search(text)):
                    bucket[key] = m.group(1)
                elif key == "major" and (m := _MAJOR_RE.search(text)):
                    bucket[key] = m.group(1)
                elif key == "degree" and (m := _DEGREE_RE.search(text)):
                    bucket[key] = m.group(1)
                elif key == "time" and (m := _TIME_RE.search(text)):
                    bucket[key] = m.group(1).strip()
            bucket.setdefault("course", "")
        elif target == "project":
            bucket.setdefault("proj_name", text[:30])
            bucket["desc"] = (bucket.get("desc", "") + text + "\n").strip()
            bucket.setdefault("tech", "、".join(detect_skills(text)))
        elif target == "internship":
            bucket.setdefault("company", text[:30])
            bucket["desc"] = (bucket.get("desc", "") + text + "\n").strip()
        elif target == "skills":
            bucket["skills"] = (bucket.get("skills", "") + "、" + text).strip("、")
        elif target == "honor":
            bucket.setdefault("honor_name", text[:30])
            bucket.setdefault("level", "")
        elif target == "summary":
            bucket["eval"] = (bucket.get("eval", "") + text).strip()

    out_modules = []
    for module_type, data in modules.items():
        entry: dict[str, Any] = {"type": module_type, "data": data, "confidence": 0.7, "sourcePages": sorted(set(pages.get(module_type, [])))}
        out_modules.append(entry)
    return {"modules": out_modules, "unmapped": unmapped, "confidence": 0.7}


def follow_up(question: str, answer: str) -> dict[str, Any]:
    text = _clean(answer)
    keywords = re.findall(r"[\u4e00-\u9fa5]{2,6}", text)
    stop = {"我们", "这个", "然后", "就是", "因为", "所以", "可以", "没有", "其实", "当时", "之后", "问题"}
    picked = next((k for k in keywords if k not in stop), "你负责的部分")
    return {"question": f"你提到「{picked}」，具体是怎么做的？结果用什么指标衡量？"}


class MockModelProvider(ModelProvider):
    """确定性、可复现、零成本。用于默认演示与单元测试基线。"""

    name = "mock-local"
    capabilities = ModelCapabilities(
        nativeToolCalling=False,
        jsonMode=True,
        jsonSchema=False,
        vision=False,
        streaming=False,
        maxContextTokens=32_768,
    )

    def __init__(self, model_name: str = "mock-local") -> None:
        self.model_name = model_name

    async def generate(self, request: ModelRequest) -> ModelResult:
        task = request.task
        inputs = request.inputs
        structured: dict[str, Any]
        try:
            if task == "build_modules":
                structured = build_modules(str(inputs.get("materials", "")), str(inputs.get("target_job", "")))
            elif task == "rewrite_field":
                structured = polish_text(
                    str(inputs.get("text", "")),
                    module_type=str(inputs.get("module_type", "")),
                    field=str(inputs.get("field", "")),
                )
            elif task == "compress_all":
                structured = compress_text(
                    str(inputs.get("text", "")),
                    int(inputs.get("budget", 760) or 760),
                    str(inputs.get("tokens", "")),
                )
            elif task == "parse_map":
                structured = map_blocks(str(inputs.get("blocks", "")))
            elif task == "match_advice":
                structured = {"advice": inputs.get("advice", [])}
            elif task == "interview_question":
                topic = str(inputs.get("topic", "项目深挖"))
                spans = str(inputs.get("resume_spans", ""))
                first = split_sentences(spans)[0] if spans else ""
                question = (
                    f"你在简历里写到「{first[:40]}」，能展开讲讲你具体负责哪一部分吗？"
                    if first
                    else f"围绕「{topic}」，讲讲你最有代表性的一段经历。"
                )
                structured = {"question": question, "resumeRefs": []}
            elif task == "interview_followup":
                structured = follow_up(str(inputs.get("question", "")), str(inputs.get("answer", "")))
            elif task == "memory_extract":
                text = str(inputs.get("text", ""))
                candidates = []
                for sent in split_sentences(text)[:4]:
                    if any(v in sent for v in ("我", "做过", "熟悉", "擅长", "想投", "希望")):
                        kind = "project" if any(v in sent for v in ("项目", "做过", "开发")) else "preference"
                        candidates.append({"kind": kind, "text": sent[:80], "reason": "用户明确陈述"})
                structured = {"candidates": candidates}
            else:
                structured = {"note": f"mock 适配器未实现任务 {task}"}
        except Exception as exc:  # pragma: no cover - 防御性
            return ModelResult(
                ok=False,
                finishReason="error",
                error=f"mock_generation_failed:{type(exc).__name__}",
                model=self.model_name,
                provider=self.name,
                promptVersion=prompt_version(task),
            )

        prompt_tokens = estimate_tokens(str(inputs)) + 200
        completion_tokens = estimate_tokens(str(structured))
        return ModelResult(
            structured=structured,
            text="",
            usage=ModelUsage(
                promptTokens=prompt_tokens,
                completionTokens=completion_tokens,
                totalTokens=prompt_tokens + completion_tokens,
                costCny=0.0,
            ),
            model=self.model_name,
            provider=self.name,
            promptVersion=prompt_version(task),
        )
