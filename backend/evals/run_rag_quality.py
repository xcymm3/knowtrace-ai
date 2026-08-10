from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

import httpx

from app.features.evaluation.rag_quality import (
    RagQualityCase,
    evaluate_rag_case,
    load_quality_cases,
    summarize_rag_quality,
)


def _api_root(value: str) -> str:
    normalized = value.rstrip("/")
    return normalized if normalized.endswith("/api/v1") else f"{normalized}/api/v1"


def _parse_sse_event(block: str) -> tuple[str, dict[str, object]] | None:
    event = next((line[7:] for line in block.splitlines() if line.startswith("event: ")), "")
    data = "\n".join(line[5:].lstrip() for line in block.splitlines() if line.startswith("data:"))
    if not event or not data:
        return None
    payload = json.loads(data)
    return event, payload if isinstance(payload, dict) else {}


async def _run_case(
    client: httpx.AsyncClient,
    api_root: str,
    workspace_id: UUID,
    case: RagQualityCase,
    retrieval_limit: int,
) -> object:
    conversation = await client.post(
        f"{api_root}/workspaces/{workspace_id}/conversations",
        json={"title": f"RAG 质量验证 · {case.id}"},
    )
    conversation.raise_for_status()
    conversation_id = UUID(str(conversation.json()["id"]))
    answer = ""
    cited_sources: list[str] = []
    try:
        async with client.stream(
            "POST",
            f"{api_root}/workspaces/{workspace_id}/conversations/{conversation_id}/messages/stream",
            json={"question": case.question, "retrieval_limit": retrieval_limit},
        ) as response:
            response.raise_for_status()
            buffer = ""
            async for chunk in response.aiter_text():
                buffer += chunk
                blocks = buffer.split("\n\n")
                buffer = blocks.pop()
                for block in blocks:
                    parsed = _parse_sse_event(block)
                    if not parsed:
                        continue
                    event, payload = parsed
                    if event == "retrieval":
                        cited_sources = [
                            str(source.get("citation", {}).get("file_name", ""))
                            for source in payload.get("sources", [])
                            if isinstance(source, dict)
                        ]
                    if event == "complete":
                        message = payload.get("message", {})
                        answer = (
                            str(message.get("content", ""))
                            if isinstance(message, dict)
                            else ""
                        )
                    if event == "error":
                        raise RuntimeError(str(payload.get("message", "RAG 回答失败。")))
        return evaluate_rag_case(case, answer=answer, cited_sources=cited_sources)
    finally:
        await client.delete(f"{api_root}/workspaces/{workspace_id}/conversations/{conversation_id}")


async def _run(args: argparse.Namespace) -> int:
    cases = load_quality_cases(Path(args.dataset))
    headers = {"Authorization": f"Bearer {args.access_token}"}
    async with httpx.AsyncClient(headers=headers, timeout=90) as client:
        results = [
            await _run_case(
                client,
                _api_root(args.api_base_url),
                UUID(args.workspace_id),
                case,
                args.retrieval_limit,
            )
            for case in cases
        ]
    summary = summarize_rag_quality(results)
    rendered = summary.model_dump_json(indent=2)
    print(rendered)
    if args.output:
        Path(args.output).write_text(rendered + "\n", encoding="utf-8")
    return 0 if summary.passed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Run KnowTrace RAG quality checks.")
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--access-token", required=True)
    parser.add_argument("--workspace-id", required=True)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--retrieval-limit", type=int, default=6)
    parser.add_argument("--output")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
