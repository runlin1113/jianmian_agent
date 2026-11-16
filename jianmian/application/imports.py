"""导入用例（M10）：文件 → DocumentBlock → 模块候选（暂存区）。

设计取舍：
- 解析结果**只进暂存区**，不直接改简历；用户在界面上逐块确认后才合并；
- 抽不到就是抽不到：宁可留空让用户补，也不猜一个学校名或数字；
- 每个候选都带 `confidence` 与来源块 id，前端可以高亮"这段是从哪来的"；
- 扫描件（文字覆盖率低）明确标 `needsOcr`，不假装解析成功。
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import PurePath
from typing import Any

from ..domain import errors
from ..domain.modules import get_spec
from ..ports.parser import DocumentBlock, ParseResult
from ..security.ids import opaque_id
from ..security.net import UploadRejected, validate_upload
from .container import AppContainer

#: 章节标题 → 模块类型的匹配词
SECTION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("basic", ("基本信息", "个人信息", "联系方式", "个人资料")),
    ("education", ("教育背景", "教育经历", "学历", "教育")),
    ("project", ("项目经历", "项目经验", "主要项目", "项目")),
    ("internship", ("实习经历", "工作经历", "实习经验", "工作经验")),
    ("skills", ("专业技能", "个人技能", "技能清单", "技能")),
    ("honor", ("荣誉奖项", "获奖情况", "个人荣誉", "奖项", "证书")),
    ("summary", ("自我评价", "个人总结", "自我介绍")),
)

PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9})(?!\d)")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
URL_RE = re.compile(r"https?://[^\s，。；、)）]+")
DATE_RANGE_RE = re.compile(
    r"((?:19|20)\d{2}\s*[.\-/年]?\s*(?:0?[1-9]|1[0-2])?\s*月?\s*[-–—~至到]\s*"
    r"((?:19|20)\d{2}\s*[.\-/年]?\s*(?:0?[1-9]|1[0-2])?\s*月?|至今|现在))"
)
SCHOOL_RE = re.compile(r"[\u4e00-\u9fa5]{2,15}(?:大学|学院|学校|中学)")
DEGREE_WORDS = ("博士", "硕士", "研究生", "本科", "学士", "大专", "专科", "高中")
TECH_HINT = ("技术栈", "技术", "使用", "框架", "工具", "环境", "语言")


@dataclass
class Candidate:
    moduleType: str
    data: dict[str, str]
    confidence: float
    sourceBlockIds: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class ImportDraft:
    id: str
    sessionId: str
    filename: str
    createdAt: float
    expiresAt: float
    blocks: list[DocumentBlock]
    candidates: list[Candidate]
    meta: dict[str, Any]


class ImportService:
    def __init__(self, container: AppContainer) -> None:
        self.container = container
        self.settings = container.settings
        self._drafts: dict[str, ImportDraft] = {}
        self._max_drafts = 200
        self._ttl = 1800.0

    # ------------------------------------------------------------------
    async def ingest(self, session_id: str, *, filename: str, data: bytes) -> ImportDraft:
        ext = PurePath(filename).suffix.lower().lstrip(".")
        parser = self.container.parsers.get(ext)
        if parser is None:
            raise errors.DomainError(
                "unsupported_format",
                "目前只支持 PDF 与 DOCX；纯文本可以直接粘贴到对话里",
                status=422,
                details={"ext": ext},
            )
        try:
            validate_upload(data, filename=filename, max_bytes=self.settings.max_upload_bytes)
        except UploadRejected as exc:
            # 只有"太大"是 413；类型不对/含宏/zip 炸弹是 422，错误码要如实带出去
            if exc.code in {"payload_too_large", "zip_bomb"}:
                raise errors.payload_too_large(exc.message, maxBytes=self.settings.max_upload_bytes) from exc
            raise errors.DomainError(exc.code, exc.message, status=422) from exc

        result = await parser.parse(data, filename=filename, max_pages=self.settings.max_pdf_pages)
        if not result.ok:
            raise errors.DomainError(
                "parse_failed",
                "这份文件没能解析出可用文本" + ("（可能是扫描件）" if result.needsOcr else ""),
                status=422,
                details={"engine": result.engine, "warnings": result.warnings[:5]},
            )

        candidates = self._to_candidates(result)
        now = time.time()
        draft = ImportDraft(
            id=opaque_id("imp", 6),
            sessionId=session_id,
            filename=filename,
            createdAt=now,
            expiresAt=now + self._ttl,
            blocks=result.blocks[:400],
            candidates=candidates,
            meta={
                "engine": result.engine,
                "pageCount": result.pageCount,
                "textCoverage": result.textCoverage,
                "twoColumnSuspected": result.twoColumnSuspected,
                "needsOcr": result.needsOcr,
                "encrypted": result.encrypted,
                "warnings": result.warnings[:8],
                "blockCount": len(result.blocks),
            },
        )
        self._store(draft)
        return draft

    def get(self, import_id: str, session_id: str) -> ImportDraft:
        draft = self._drafts.get(import_id)
        if draft is None or draft.expiresAt < time.time():
            raise errors.not_found("导入会话")
        if draft.sessionId != session_id:
            raise errors.forbidden("该导入会话属于其他会话")
        return draft

    # ------------------------------------------------------------------
    def _to_candidates(self, result: ParseResult) -> list[Candidate]:
        blocks = [b for b in sorted(result.blocks, key=lambda x: (x.page, x.order)) if b.text.strip()]
        if not blocks:
            return []

        sections: list[tuple[str, list[DocumentBlock]]] = []
        current_type = ""
        current: list[DocumentBlock] = []
        for block in blocks:
            hit = self._section_of(block)
            if hit and hit != current_type:
                if current:
                    sections.append((current_type, current))
                current_type = hit
                current = []  # 标题块本身不进正文
                continue
            current.append(block)
        if current:
            sections.append((current_type, current))

        candidates: list[Candidate] = []
        head_text = "\n".join(b.text for b in blocks[:12])

        # 1) 基本信息：从全文头部找电话/邮箱/主页，姓名只从"短行且不含数字"里取
        basic: dict[str, str] = {}
        ids: list[str] = []
        phone = PHONE_RE.search(head_text)
        email = EMAIL_RE.search(head_text)
        url = URL_RE.search(head_text)
        if phone:
            basic["phone"] = phone.group(1)
            ids += [b.id for b in blocks[:12] if phone.group(1) in b.text]
        if email:
            basic["email"] = email.group(0)
            ids += [b.id for b in blocks[:12] if email.group(0) in b.text]
        if url:
            basic["github"] = url.group(0)
        for block in blocks[:4]:
            line = block.text.strip()
            if 2 <= len(line) <= 4 and not any(ch.isdigit() for ch in line) and "@" not in line:
                basic.setdefault("name", line)
                ids.append(block.id)
                break
        for block in blocks[:8]:
            if "求职意向" in block.text or "应聘" in block.text:
                basic["job"] = re.sub(r"^(求职意向|应聘)[:：\s]*", "", block.text).strip()[:40]
                ids.append(block.id)
                break
        if basic:
            confidence = 0.9 if basic.get("phone") and basic.get("email") else 0.55
            candidates.append(
                Candidate("basic", basic, confidence, list(dict.fromkeys(ids)),
                          "姓名/电话/邮箱是从原文中直接识别的，请核对后再合并")
            )

        # 2) 其余章节
        for section_type, section_blocks in sections:
            if not section_type or section_type == "basic":
                continue
            text = "\n".join(b.text for b in section_blocks).strip()
            if not text:
                continue
            block_ids = [b.id for b in section_blocks]
            if section_type == "skills":
                candidates.append(
                    Candidate("skills", {"skills": text[:800]}, 0.75, block_ids, "技能按原文整段保留，未做删改")
                )
            elif section_type == "summary":
                candidates.append(
                    Candidate("summary", {"eval": text[:1200]}, 0.7, block_ids, "自我评价保留原文，可再润色")
                )
            elif section_type == "honor":
                for line, block in self._split_items(section_blocks):
                    data = {"honor_name": line[:60], "time": "", "level": ""}
                    date = DATE_RANGE_RE.search(line)
                    if date:
                        data["time"] = _clean_date(date.group(0))
                    candidates.append(Candidate("honor", data, 0.6, [block.id], "奖项按行拆分，级别留空待补"))
            elif section_type == "education":
                for item_text, block in self._split_items(section_blocks):
                    data = self._parse_education(item_text)
                    if data:
                        candidates.append(Candidate("education", data, 0.65, [block.id], "学校/专业按关键词识别"))
            elif section_type in {"project", "internship"}:
                for item_text, block in self._split_items(section_blocks):
                    data = self._parse_experience(item_text, section_type)
                    if data:
                        candidates.append(
                            Candidate(section_type, data, 0.6, [block.id], "项目/实习条目按行首标题切分，请核对负责人部分")
                        )

        candidates.sort(key=lambda c: (-c.confidence, c.moduleType))
        return candidates

    # ------------------------------------------------------------------
    def _section_of(self, block: DocumentBlock) -> str:
        text = block.text.strip()
        if len(text) > 24:
            return ""
        for module_type, words in SECTION_WORDS:
            if any(word in text for word in words):
                return module_type
        return ""

    def _split_items(self, blocks: list[DocumentBlock]) -> list[tuple[str, DocumentBlock]]:
        """按"看起来像条目标题"的行切分，返回 (整条文本, 起始块)。

        判断标准刻意保守：带日期、标题样式、或很短且不像正文/键值行的，才算标题。
        宁可把两段并成一条让用户拆分，也不要把一句话拆成三个"项目"。
        """
        items: list[tuple[str, DocumentBlock]] = []
        buf: list[str] = []
        start: DocumentBlock | None = None
        for block in blocks:
            text = block.text.strip()
            is_title = self._looks_like_title(text, block)
            new_item = is_title and (start is None or len(buf) >= 2)
            if new_item:
                if buf and start is not None:
                    items.append(("\n".join(buf), start))
                buf, start = [text], block
            else:
                if start is None:
                    start = block
                buf.append(text)
        if buf and start is not None:
            items.append(("\n".join(buf), start))
        return items

    @staticmethod
    def _looks_like_title(text: str, block: DocumentBlock) -> bool:
        if block.kind == "heading":
            return True
        if DATE_RANGE_RE.search(text):
            return True
        if len(text) > 22:
            return False
        if text.endswith(("。", "；", ";", "，", ",")):
            return False
        if "：" in text or ":" in text:  # 键值行属于正文（如"技术栈：Flask"）
            return False
        return bool(text)

    def _parse_education(self, text: str) -> dict[str, str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        data: dict[str, str] = {"school": "", "major": "", "degree": "", "time": "", "course": ""}
        date = DATE_RANGE_RE.search(text)
        if date:
            data["time"] = _clean_date(date.group(0))
        school = SCHOOL_RE.search(text)
        if school:
            data["school"] = school.group(0)
        for degree in DEGREE_WORDS:
            if degree in text:
                data["degree"] = degree
                break
        for line in lines:
            if "专业" in line:
                data["major"] = re.sub(r".*?专业[:：]?", "", line).strip()[:40] or line[:40]
                break
        if not data["major"]:
            # 去掉已知片段后，最长的一段通常就是专业名（不猜、只从原文里取）
            remain = lines[0] if lines else ""
            for token in (data["school"], data["degree"], data["time"], date.group(0) if date else ""):
                if token:
                    remain = remain.replace(token, " ")
            parts = [p for p in re.split(r"[\s|｜/·、,，]+", remain) if p]
            if parts:
                data["major"] = max(parts, key=len)[:40]
        rest = [line for line in lines if line not in (data["school"], data["time"]) and "专业" not in line]
        course = [line for line in lines if "课程" in line or "GPA" in line.upper()]
        if course:
            data["course"] = "；".join(course)[:800]
        return data if (data["school"] or data["major"]) else {}

    def _parse_experience(self, text: str, module_type: str) -> dict[str, str]:
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        if not lines:
            return {}
        title = lines[0]
        date = DATE_RANGE_RE.search(text)
        time_text = _clean_date(date.group(0)) if date else ""
        title_clean = DATE_RANGE_RE.sub("", title).strip(" |·-—")
        tech = ""
        for line in lines[1:]:
            if any(hint in line for hint in TECH_HINT) and len(line) <= 120:
                tech = line.split("：", 1)[-1].split(":", 1)[-1].strip()
                break
        body_lines = lines[1:]
        if tech:
            body_lines = [line for line in body_lines if tech not in line]
        if module_type == "project":
            return {
                "proj_name": title_clean[:60],
                "role": "",
                "time": time_text,
                "tech": tech[:200],
                "desc": "\n".join(body_lines)[:2000],
            }
        return {
            "company": title_clean[:60],
            "position": "",
            "time": time_text,
            "desc": "\n".join(body_lines)[:2000],
        }

    # ------------------------------------------------------------------
    def _store(self, draft: ImportDraft) -> None:
        if len(self._drafts) >= self._max_drafts:
            oldest = min(self._drafts.values(), key=lambda d: d.createdAt)
            self._drafts.pop(oldest.id, None)
        self._drafts[draft.id] = draft
        self.purge()

    def purge(self) -> int:
        now = time.time()
        dead = [key for key, draft in self._drafts.items() if draft.expiresAt < now]
        for key in dead:
            self._drafts.pop(key, None)
        return len(dead)

    def public_view(self, draft: ImportDraft) -> dict[str, Any]:
        """暂存区视图：只回传候选和来源块，让前端能做"逐条确认"。"""
        return {
            "importId": draft.id,
            "filename": draft.filename,
            "expiresAt": draft.expiresAt,
            "meta": draft.meta,
            "blocks": [
                {"id": b.id, "kind": b.kind, "text": b.text[:1200], "page": b.page, "order": b.order}
                for b in draft.blocks[:120]
            ],
            "candidates": [
                {
                    "moduleType": c.moduleType,
                    "zh": get_spec(c.moduleType).zh if c.moduleType else "",
                    "data": c.data,
                    "confidence": c.confidence,
                    "sourceBlockIds": c.sourceBlockIds,
                    "note": c.note,
                }
                for c in draft.candidates
            ],
            "truncated": len(draft.blocks) > 120,
        }


def _clean_date(raw: str) -> str:
    text = re.sub(r"\s+", "", raw).replace("至", "-").replace("到", "-")
    text = text.replace("年", ".").replace("月", "").replace("/", ".")
    return text[:60]
