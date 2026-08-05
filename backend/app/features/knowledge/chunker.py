from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TextChunk:
    index: int
    content: str
    start_char: int
    end_char: int

    @property
    def metadata(self) -> dict[str, int]:
        return {"startChar": self.start_char, "endChar": self.end_char}


def chunk_text(text: str, *, max_chars: int = 1000, overlap_chars: int = 160) -> list[TextChunk]:
    """Create deterministic, overlapping chunks while preferring paragraph boundaries."""
    if max_chars <= 0:
        raise ValueError("max_chars must be positive")
    if not 0 <= overlap_chars < max_chars:
        raise ValueError("overlap_chars must be non-negative and smaller than max_chars")

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    if not normalized:
        return []

    chunks: list[TextChunk] = []
    start = 0
    text_length = len(normalized)
    while start < text_length:
        target_end = min(start + max_chars, text_length)
        end = target_end
        if target_end < text_length:
            paragraph_break = normalized.rfind("\n\n", start + max_chars // 2, target_end)
            line_break = normalized.rfind("\n", start + max_chars // 2, target_end)
            word_break = normalized.rfind(" ", start + max_chars // 2, target_end)
            boundary = max(paragraph_break, line_break, word_break)
            if boundary > start:
                end = boundary

        content = normalized[start:end].strip()
        if content:
            leading_trim = len(normalized[start:end]) - len(normalized[start:end].lstrip())
            trailing_trim = len(normalized[start:end]) - len(normalized[start:end].rstrip())
            chunks.append(
                TextChunk(
                    index=len(chunks),
                    content=content,
                    start_char=start + leading_trim,
                    end_char=end - trailing_trim,
                )
            )
        if end >= text_length:
            break
        start = max(end - overlap_chars, start + 1)
    return chunks
