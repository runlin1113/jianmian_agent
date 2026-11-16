"""解析端口（M9）。所有解析器统一输出 `DocumentBlock`，与具体引擎无关。"""

from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field

BlockKind = Literal["heading", "paragraph", "list_item", "table_cell", "image", "unknown"]


class DocumentBlock(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    kind: BlockKind = "paragraph"
    text: str = ""
    page: int = 0
    order: int = 0
    #: 归一化坐标 [x0,y0,x1,y1]，0—1；不可得时为 None
    bbox: list[float] | None = None
    #: 该块来自哪个引擎（pdfjs / pypdf / docx / ocr / manual）
    engine: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class ParseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ok: bool
    engine: str
    blocks: list[DocumentBlock] = Field(default_factory=list)
    pageCount: int = 0
    #: 文字覆盖率：扫描件会很低
    textCoverage: float = 0.0
    twoColumnSuspected: bool = False
    encrypted: bool = False
    needsOcr: bool = False
    warnings: list[str] = Field(default_factory=list)
    meta: dict[str, Any] = Field(default_factory=dict)

    def plain_text(self) -> str:
        return "\n".join(b.text for b in sorted(self.blocks, key=lambda x: (x.page, x.order)) if b.text)


class ParserAdapter(Protocol):
    name: str
    supports: tuple[str, ...]

    async def parse(self, data: bytes, *, filename: str, max_pages: int) -> ParseResult: ...
