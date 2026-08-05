import asyncio
from uuid import uuid4

from app.features.knowledge.chunker import chunk_text
from app.features.knowledge.schemas import KnowledgeSearchRequest
from app.features.knowledge.service import KnowledgeSearchService
from app.features.knowledge.store import _vector_literal


def test_chunk_text_keeps_order_and_overlap() -> None:
    text = "商品卖点：轻薄。\n\n" + ("续航表现稳定，适合通勤场景。" * 30)

    chunks = chunk_text(text, max_chars=90, overlap_chars=15)

    assert len(chunks) > 2
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    assert chunks[0].start_char == 0
    assert all(chunk.start_char < chunk.end_char for chunk in chunks)
    assert any(
        chunks[index].end_char > chunks[index + 1].start_char for index in range(len(chunks) - 1)
    )


def test_vector_literal_uses_pgvector_format() -> None:
    assert _vector_literal([0.1, -0.2, 3.0]) == "[0.1,-0.2,3]"


class FakeEmbeddings:
    async def embed(self, texts: list[str]) -> list[list[float]]:
        assert texts == ["通勤轻薄笔记本"]
        return [[0.1, 0.2]]


class FakeKnowledgeStore:
    def __init__(self, row: dict[str, object]) -> None:
        self.row = row
        self.received: tuple[object, ...] | None = None

    def search(self, *args: object) -> list[dict[str, object]]:
        self.received = args
        return [self.row]


def test_search_returns_traceable_citation() -> None:
    project_id = uuid4()
    document_id = uuid4()
    chunk_id = uuid4()
    store = FakeKnowledgeStore(
        {
            "id": chunk_id,
            "document_id": document_id,
            "content": "重量 1.2kg，适合通勤携带。",
            "metadata": {"chunkIndex": 2, "startChar": 32, "endChar": 48},
            "file_name": "竞品参数.xlsx",
            "kind": "COMPETITOR_SHEET",
            "product_id": None,
            "semantic_score": 0.8,
            "keyword_score": 0.3,
            "final_score": 0.675,
        }
    )
    service = KnowledgeSearchService(store=store, embeddings=FakeEmbeddings())

    result = asyncio.run(
        service.search(project_id, KnowledgeSearchRequest(query="通勤轻薄笔记本", limit=5))
    )

    assert store.received is not None
    assert store.received[0] == project_id
    assert result.hits[0].citation.file_name == "竞品参数.xlsx"
    assert result.hits[0].citation.chunk_index == 2
    assert result.hits[0].citation.start_char == 32
