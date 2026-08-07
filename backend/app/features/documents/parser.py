from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from pathlib import PurePath

from docx import Document as DocxDocument
from openpyxl import load_workbook
from PIL import Image
from pypdf import PdfReader

from app.core.errors import ApiError

TEXT_MIME_TYPES = {"text/plain", "text/markdown", "text/csv"}
SPREADSHEET_MIME_TYPES = {
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
}
DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
PDF_MIME_TYPE = "application/pdf"
IMAGE_MIME_TYPES = {"image/jpeg", "image/png", "image/webp"}
SUPPORTED_EXTENSIONS = {
    ".txt",
    ".md",
    ".markdown",
    ".csv",
    ".docx",
    ".xlsx",
    ".pdf",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


@dataclass(frozen=True)
class ParsedDocument:
    text: str
    metadata: dict[str, object]
    needs_ocr: bool = False


def limit_extracted_text(parsed: ParsedDocument, max_characters: int) -> ParsedDocument:
    """Cap extracted text before storing derived artifacts or sending it to an indexer."""
    if max_characters <= 0:
        raise ValueError("max_characters must be positive")
    if len(parsed.text) <= max_characters:
        return parsed
    return ParsedDocument(
        text=parsed.text[:max_characters],
        metadata={
            **parsed.metadata,
            "characterCount": max_characters,
            "originalCharacterCount": len(parsed.text),
            "truncated": True,
        },
        needs_ocr=parsed.needs_ocr,
    )


def _decode_text(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "gb18030"):
        try:
            return content.decode(encoding).strip()
        except UnicodeDecodeError:
            continue

    raise ApiError(
        422, "DOCUMENT_ENCODING_UNSUPPORTED", "文件编码无法识别，请使用 UTF-8 或 GB18030。"
    )


def _parse_text(content: bytes, mime_type: str) -> ParsedDocument:
    text = _decode_text(content)

    if mime_type != "text/csv":
        return ParsedDocument(text=text, metadata={"parser": "text", "characterCount": len(text)})

    rows = list(csv.reader(io.StringIO(text)))
    normalized_rows = [" | ".join(cell.strip() for cell in row if cell.strip()) for row in rows]
    extracted_text = "\n".join(row for row in normalized_rows if row).strip()
    return ParsedDocument(
        text=extracted_text,
        metadata={"parser": "csv", "rowCount": len(rows), "characterCount": len(extracted_text)},
    )


def _parse_spreadsheet(content: bytes) -> ParsedDocument:
    try:
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as error:
        raise ApiError(
            422, "DOCUMENT_PARSE_FAILED", "无法读取 Excel 文件，请确认文件未损坏。"
        ) from error

    rows: list[str] = []
    worksheet_names: list[str] = []
    row_count = 0

    for worksheet in workbook.worksheets:
        worksheet_names.append(worksheet.title)
        for row in worksheet.iter_rows(values_only=True):
            values = [
                str(value).strip() for value in row if value is not None and str(value).strip()
            ]
            if values:
                rows.append(f"[{worksheet.title}] " + " | ".join(values))
                row_count += 1

    workbook.close()
    text = "\n".join(rows).strip()
    return ParsedDocument(
        text=text,
        metadata={
            "parser": "spreadsheet",
            "worksheetNames": worksheet_names,
            "rowCount": row_count,
            "characterCount": len(text),
        },
    )


def _parse_docx(content: bytes) -> ParsedDocument:
    try:
        document = DocxDocument(io.BytesIO(content))
    except Exception as error:
        raise ApiError(
            422, "DOCUMENT_PARSE_FAILED", "无法读取 DOCX 文件，请确认文件未损坏。"
        ) from error

    paragraphs = [
        paragraph.text.strip() for paragraph in document.paragraphs if paragraph.text.strip()
    ]
    table_rows: list[str] = []
    for table in document.tables:
        for row in table.rows:
            cells = [
                cell.text.strip().replace("\n", " ") for cell in row.cells if cell.text.strip()
            ]
            if cells:
                table_rows.append(" | ".join(cells))

    text = "\n\n".join(paragraphs + table_rows).strip()
    return ParsedDocument(
        text=text,
        metadata={
            "parser": "docx",
            "paragraphCount": len(paragraphs),
            "tableCount": len(document.tables),
            "tableRowCount": len(table_rows),
            "characterCount": len(text),
        },
    )


def _parse_pdf(content: bytes) -> ParsedDocument:
    try:
        reader = PdfReader(io.BytesIO(content))
        pages = [(page.extract_text() or "").strip() for page in reader.pages]
    except Exception as error:
        raise ApiError(
            422, "DOCUMENT_PARSE_FAILED", "无法读取 PDF 文件，请确认文件未损坏或受密码保护。"
        ) from error

    text = "\n\n".join(page for page in pages if page).strip()
    return ParsedDocument(
        text=text,
        metadata={"parser": "pdf", "pageCount": len(pages), "characterCount": len(text)},
        needs_ocr=not bool(text),
    )


def _parse_image(content: bytes) -> ParsedDocument:
    try:
        image = Image.open(io.BytesIO(content))
        width, height = image.size
        image_format = image.format
    except Exception as error:
        raise ApiError(
            422, "DOCUMENT_PARSE_FAILED", "无法读取图片文件，请确认图片未损坏。"
        ) from error

    return ParsedDocument(
        text="",
        metadata={
            "parser": "image-metadata",
            "width": width,
            "height": height,
            "format": image_format,
        },
        needs_ocr=True,
    )


def validate_document_type(mime_type: str, filename: str) -> None:
    extension = PurePath(filename).suffix.lower()
    supported_mime_type = (
        mime_type in TEXT_MIME_TYPES
        or mime_type in SPREADSHEET_MIME_TYPES
        or mime_type == DOCX_MIME_TYPE
        or mime_type == PDF_MIME_TYPE
        or mime_type in IMAGE_MIME_TYPES
    )

    if extension and extension not in SUPPORTED_EXTENSIONS:
        raise ApiError(
            415,
            "DOCUMENT_TYPE_UNSUPPORTED",
            "仅支持 TXT、Markdown、CSV、XLSX、DOCX、PDF、JPG、PNG 和 WEBP 文件。",
        )
    if not supported_mime_type and extension not in SUPPORTED_EXTENSIONS:
        raise ApiError(
            415,
            "DOCUMENT_TYPE_UNSUPPORTED",
            "仅支持 TXT、Markdown、CSV、XLSX、DOCX、PDF、JPG、PNG 和 WEBP 文件。",
        )


def parse_document(content: bytes, mime_type: str, filename: str) -> ParsedDocument:
    """Extract deterministic text/metadata; OCR is deferred to the worker pipeline."""
    extension = PurePath(filename).suffix.lower()
    validate_document_type(mime_type, filename)

    if mime_type in TEXT_MIME_TYPES or extension in {".txt", ".md", ".markdown", ".csv"}:
        return _parse_text(content, "text/csv" if extension == ".csv" else mime_type)
    if mime_type in SPREADSHEET_MIME_TYPES or extension == ".xlsx":
        return _parse_spreadsheet(content)
    if mime_type == DOCX_MIME_TYPE or extension == ".docx":
        return _parse_docx(content)
    if mime_type == PDF_MIME_TYPE or extension == ".pdf":
        return _parse_pdf(content)
    if mime_type in IMAGE_MIME_TYPES or extension in {".jpg", ".jpeg", ".png", ".webp"}:
        return _parse_image(content)

    raise ApiError(
        415,
        "DOCUMENT_TYPE_UNSUPPORTED",
        "仅支持 TXT、Markdown、CSV、XLSX、DOCX、PDF、JPG、PNG 和 WEBP 文件。",
    )
