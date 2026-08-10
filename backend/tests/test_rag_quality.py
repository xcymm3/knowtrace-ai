from app.features.evaluation.rag_quality import (
    RagQualityCase,
    evaluate_rag_case,
    summarize_rag_quality,
)


def test_rag_quality_gate_passes_grounded_answer_with_expected_source() -> None:
    result = evaluate_rag_case(
        RagQualityCase(
            id="meeting-decision",
            question="会议最终决定了什么？",
            expected_sources=["会议纪要.md"],
            expected_answer_terms=["继续推进", "张三"],
        ),
        answer="会议决定继续推进，并由张三负责后续验证。",
        cited_sources=["会议纪要.md", "项目计划.md"],
    )

    assert result.passed is True
    assert result.retrieval_recall == 1.0
    assert result.citation_precision == 0.5
    assert result.answer_term_coverage == 1.0


def test_rag_quality_gate_reports_missing_evidence_and_answer_terms() -> None:
    result = evaluate_rag_case(
        RagQualityCase(
            id="meeting-decision",
            question="会议最终决定了什么？",
            expected_sources=["会议纪要.md"],
            expected_answer_terms=["继续推进", "张三"],
        ),
        answer="项目还在讨论中。",
        cited_sources=["项目计划.md"],
    )

    assert result.passed is False
    assert result.missing_sources == ["会议纪要.md"]
    assert result.missing_answer_terms == ["继续推进", "张三"]
    assert summarize_rag_quality([result]).passed is False
