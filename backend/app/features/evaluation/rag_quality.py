from __future__ import annotations

import json
import re
from pathlib import Path

from pydantic import BaseModel, Field


class RagQualityCase(BaseModel):
    """A reviewable question with expected evidence and answer terms."""

    id: str = Field(min_length=1)
    question: str = Field(min_length=2)
    expected_sources: list[str] = Field(min_length=1)
    expected_answer_terms: list[str] = Field(min_length=1)


class RagQualityResult(BaseModel):
    case_id: str
    retrieval_recall: float
    citation_precision: float
    answer_term_coverage: float
    passed: bool
    missing_sources: list[str]
    missing_answer_terms: list[str]


class RagQualitySummary(BaseModel):
    total_cases: int
    passed_cases: int
    pass_rate: float
    average_retrieval_recall: float
    average_citation_precision: float
    average_answer_term_coverage: float
    passed: bool
    results: list[RagQualityResult]


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def load_quality_cases(path: Path) -> list[RagQualityCase]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("RAG 质量数据集必须是 JSON 数组。")
    cases = [RagQualityCase.model_validate(item) for item in raw]
    if not cases:
        raise ValueError("RAG 质量数据集至少需要一个用例。")
    return cases


def evaluate_rag_case(
    case: RagQualityCase,
    *,
    answer: str,
    cited_sources: list[str],
) -> RagQualityResult:
    expected_sources = {_normalize(source) for source in case.expected_sources}
    actual_sources = {_normalize(source) for source in cited_sources}
    matched_sources = expected_sources & actual_sources
    missing_sources = [
        source for source in case.expected_sources if _normalize(source) not in actual_sources
    ]

    normalized_answer = _normalize(answer)
    missing_terms = [
        term for term in case.expected_answer_terms if _normalize(term) not in normalized_answer
    ]
    retrieval_recall = len(matched_sources) / len(expected_sources)
    citation_precision = (
        len(matched_sources) / len(actual_sources) if actual_sources else 0.0
    )
    answer_term_coverage = (
        (len(case.expected_answer_terms) - len(missing_terms)) / len(case.expected_answer_terms)
    )
    passed = (
        retrieval_recall == 1.0
        and citation_precision >= 0.5
        and answer_term_coverage == 1.0
    )
    return RagQualityResult(
        case_id=case.id,
        retrieval_recall=retrieval_recall,
        citation_precision=citation_precision,
        answer_term_coverage=answer_term_coverage,
        passed=passed,
        missing_sources=missing_sources,
        missing_answer_terms=missing_terms,
    )


def summarize_rag_quality(results: list[RagQualityResult]) -> RagQualitySummary:
    if not results:
        raise ValueError("没有可汇总的 RAG 质量结果。")
    total = len(results)
    passed_cases = sum(result.passed for result in results)
    return RagQualitySummary(
        total_cases=total,
        passed_cases=passed_cases,
        pass_rate=passed_cases / total,
        average_retrieval_recall=sum(result.retrieval_recall for result in results) / total,
        average_citation_precision=sum(result.citation_precision for result in results) / total,
        average_answer_term_coverage=sum(result.answer_term_coverage for result in results)
        / total,
        passed=passed_cases == total,
        results=results,
    )
