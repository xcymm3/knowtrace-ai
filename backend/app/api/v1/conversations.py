import json
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import StreamingResponse

from app.api.dependencies import get_rag_conversation_service
from app.core.errors import ApiError
from app.features.conversations.schemas import (
    ConversationCreate,
    ConversationMessageResponse,
    ConversationResponse,
    RagQuestionRequest,
)
from app.features.conversations.service import PreparedRagTurn, RagConversationService

router = APIRouter(prefix="/workspaces/{workspace_id}/conversations", tags=["conversations"])


@router.post("", response_model=ConversationResponse, status_code=status.HTTP_201_CREATED)
async def create_conversation(
    workspace_id: UUID,
    payload: ConversationCreate,
    service: RagConversationService = Depends(get_rag_conversation_service),
) -> ConversationResponse:
    return await service.create_conversation(workspace_id, payload)


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    workspace_id: UUID,
    service: RagConversationService = Depends(get_rag_conversation_service),
) -> list[ConversationResponse]:
    return await service.list_conversations(workspace_id)


@router.delete("/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    workspace_id: UUID,
    conversation_id: UUID,
    service: RagConversationService = Depends(get_rag_conversation_service),
) -> None:
    await service.delete_conversation(workspace_id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=list[ConversationMessageResponse])
async def list_messages(
    workspace_id: UUID,
    conversation_id: UUID,
    service: RagConversationService = Depends(get_rag_conversation_service),
) -> list[ConversationMessageResponse]:
    return await service.list_messages(workspace_id, conversation_id)


async def rag_event_stream(
    service: RagConversationService, turn: PreparedRagTurn
) -> AsyncIterator[str]:
    try:
        async for event in service.stream_turn(turn):
            payload = json.dumps(event["data"], ensure_ascii=False, default=str)
            yield f"event: {event['event']}\ndata: {payload}\n\n"
    except ApiError as error:
        payload = json.dumps({"code": error.code, "message": error.message}, ensure_ascii=False)
        yield f"event: error\ndata: {payload}\n\n"
    except Exception:
        payload = json.dumps(
            {"code": "RAG_STREAM_FAILED", "message": "回答生成中断，请稍后重试。"},
            ensure_ascii=False,
        )
        yield f"event: error\ndata: {payload}\n\n"


@router.post("/{conversation_id}/messages/stream", summary="Stream a cited RAG answer")
async def stream_rag_answer(
    workspace_id: UUID,
    conversation_id: UUID,
    payload: RagQuestionRequest,
    service: RagConversationService = Depends(get_rag_conversation_service),
) -> StreamingResponse:
    turn = await service.prepare_turn(workspace_id, conversation_id, payload)
    return StreamingResponse(
        rag_event_stream(service, turn),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
