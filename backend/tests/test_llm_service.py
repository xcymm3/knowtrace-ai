import asyncio

import pytest

from app.core.config import Settings
from app.core.errors import ApiError
from app.features.llm.schemas import GroundedAnswerRequest
from app.features.llm.service import LangChainAnswerService, build_langchain_answer_service


class FakeAnswerChain:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.requests: list[dict[str, str]] = []

    async def ainvoke(self, input: dict[str, str]) -> str:
        self.requests.append(input)
        return self.answer

    async def astream(self, input: dict[str, str]):
        self.requests.append(input)
        yield self.answer[:2]
        yield self.answer[2:]


def test_answer_service_passes_question_and_context_to_chain() -> None:
    chain = FakeAnswerChain("资料显示该方案可行。")
    service = LangChainAnswerService(chain, "demo-model")

    result = asyncio.run(
        service.answer(GroundedAnswerRequest(question="是否可行？", context="测试结果：通过。"))
    )

    assert result.answer == "资料显示该方案可行。"
    assert result.model == "demo-model"
    assert chain.requests == [{"question": "是否可行？", "context": "测试结果：通过。"}]


def test_answer_service_rejects_empty_model_output() -> None:
    service = LangChainAnswerService(FakeAnswerChain("  "), "demo-model")

    with pytest.raises(ApiError, match="模型没有返回"):
        asyncio.run(service.answer(GroundedAnswerRequest(question="状态？", context="暂无资料")))


def test_answer_service_streams_chain_deltas() -> None:
    service = LangChainAnswerService(FakeAnswerChain("依据资料回答。"), "demo-model")

    async def collect() -> list[str]:
        return [
            delta
            async for delta in service.stream(
                GroundedAnswerRequest(question="状态？", context="资料")
            )
        ]

    assert asyncio.run(collect()) == ["依据", "资料回答。"]


def test_adapter_requires_explicit_chat_model_configuration() -> None:
    with pytest.raises(ApiError, match="对话模型"):
        build_langchain_answer_service(Settings(llm_base_url=None, llm_api_key=None))


def test_adapter_builds_langchain_chain_without_network_request() -> None:
    service = build_langchain_answer_service(
        Settings(
            llm_base_url="https://api.example.test/v1",
            llm_api_key="test-key",
            llm_model="test-model",
        )
    )

    assert service._model_name == "test-model"
