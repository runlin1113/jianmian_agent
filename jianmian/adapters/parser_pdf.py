"""PDF 解析适配器（本地优先，pypdf 文本层）。

真实产品里文本 PDF 走 PDF.js Worker、复杂版式走 Docling、扫描件走隔离 OCR；
本 demo 用 pypdf 抽取文本层，并**诚实标注**能力边界：
- 文字覆盖率低 → `needsOcr=True`，前端提示"扫描件请手动粘贴或校对"；
- 加密 PDF 直接拒绝；
- 页数超过上限直接拒绝。
宁可给出可校正的降级路径，也不宣称任意版式无损还原。
"""

from __future__ import annotations

import io

from ..ports.parser import DocumentBlock, ParseResult


class PdfParser:
    name = "pypdf"
    supports = ("pdf",)

    async def parse(self, data: bytes, *, filename: str = "", max_pages: int = 20) -> ParseResult:
        try:
            from pypdf import PdfReader
        except ImportError:  # pragma: no cover
            return ParseResult(ok=False, engine=self.name, warnings=["未安装 pypdf，无法解析 PDF"])

        try:
            reader = PdfReader(io.BytesIO(data))
        except Exception:
            return ParseResult(ok=False, engine=self.name, warnings=["PDF 结构损坏，无法解析"])

        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                return ParseResult(
                    ok=False,
                    engine=self.name,
                    encrypted=True,
                    warnings=["PDF 已加密，请先解除密码保护再上传"],
                )

        pages = len(reader.pages)
        if pages > max_pages:
            return ParseResult(
                ok=False,
                engine=self.name,
                pageCount=pages,
                warnings=[f"PDF 共 {pages} 页，超过 {max_pages} 页上限"],
            )

        blocks: list[DocumentBlock] = []
        empty_pages = 0
        order = 0
        for page_index, page in enumerate(reader.pages, start=1):
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            lines = [ln.strip() for ln in text.split("\n") if ln.strip()]
            if not lines:
                empty_pages += 1
            for line in lines:
                blocks.append(
                    DocumentBlock(
                        id=f"b{order}",
                        kind="paragraph",
                        text=line,
                        page=page_index,
                        order=order,
                        engine=self.name,
                        confidence=0.9,
                    )
                )
                order += 1

        total_chars = sum(len(b.text) for b in blocks)
        coverage = total_chars / max(1, pages * 800)
        needs_ocr = empty_pages > 0 or coverage < 0.15
        warnings: list[str] = []
        if needs_ocr:
            warnings.append("文字层稀疏，可能是扫描件；可手动粘贴文本或校正关键字段")
        return ParseResult(
            ok=bool(blocks),
            engine=self.name,
            blocks=blocks,
            pageCount=pages,
            textCoverage=min(1.0, coverage),
            twoColumnSuspected=False,
            encrypted=False,
            needsOcr=needs_ocr,
            warnings=warnings,
            meta={"filename": filename, "emptyPages": empty_pages},
        )
