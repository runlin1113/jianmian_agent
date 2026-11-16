"""DOCX 解析适配器：段落 + 表格，按正文顺序输出 DocumentBlock。

不执行宏、不拉取外链、不解压外部关系文件；仅读取 word/document.xml 的正文。
页数无法可靠得知（DOCX 无固定分页），因此 page 统一为 1，并在 meta 中说明。
"""

from __future__ import annotations

import io

from ..ports.parser import DocumentBlock, ParseResult


class DocxParser:
    name = "docx"
    supports = ("docx",)

    async def parse(self, data: bytes, *, filename: str = "", max_pages: int = 20) -> ParseResult:
        try:
            import docx
        except ImportError as exc:  # pragma: no cover
            return ParseResult(
                ok=False, engine=self.name, warnings=["未安装 python-docx，无法解析 DOCX"]
            )
        from docx.document import Document as _Doc
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        try:
            document = docx.Document(io.BytesIO(data))
        except Exception:
            return ParseResult(ok=False, engine=self.name, warnings=["DOCX 结构损坏，无法解析"])

        blocks: list[DocumentBlock] = []
        order = 0
        body = document.element.body

        def _add(kind: str, text: str) -> None:
            nonlocal order
            text = (text or "").strip()
            if not text:
                return
            blocks.append(
                DocumentBlock(
                    id=f"b{order}",
                    kind=kind,  # type: ignore[arg-type]
                    text=text,
                    page=1,
                    order=order,
                    engine=self.name,
                    confidence=0.95,
                )
            )
            order += 1

        for child in body.iterchildren():
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                para = Paragraph(child, document)
                style = (para.style.name or "").lower()
                kind = "heading" if "heading" in style or "标题" in style else "paragraph"
                if (para.style.name or "").lower().startswith("list"):
                    kind = "list_item"
                _add(kind, para.text)
            elif tag == "tbl":
                table = Table(child, document)
                for row in table.rows:
                    cells = [c.text.strip() for c in row.cells if c.text.strip()]
                    if cells:
                        _add("table_cell", " | ".join(cells))

        text_len = sum(len(b.text) for b in blocks)
        coverage = min(1.0, text_len / max(1, len(blocks) * 30)) if blocks else 0.0
        warnings: list[str] = []
        if not blocks:
            warnings.append("DOCX 中没有可提取文本，可能全是图片")
        return ParseResult(
            ok=bool(blocks),
            engine=self.name,
            blocks=blocks,
            pageCount=1,
            textCoverage=coverage,
            twoColumnSuspected=False,
            encrypted=False,
            needsOcr=not blocks,
            warnings=warnings,
            meta={"filename": filename, "pageCountEstimated": True},
        )
