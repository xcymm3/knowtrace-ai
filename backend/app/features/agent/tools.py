import asyncio
import json
from collections.abc import Awaitable, Callable
from typing import Annotated, Any
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from app.features.agent.checks import Verification
from app.features.agent.files import WorkspaceFiles
from app.features.agent.runtime import AgentError, ToolCall
from app.features.knowledge.schemas import KnowledgeSearchHit, KnowledgeSearchResponse


class _Arguments(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)


class _KnowledgeQuery(_Arguments):
    query: str = Field(min_length=2, max_length=500)
    limit: int = Field(default=6, ge=1, le=8)


class _FileList(_Arguments):
    directory: str = Field(default=".", min_length=1, max_length=512)
    limit: int = Field(default=60, ge=1, le=120)


class _FileSearch(_FileList):
    query: str = Field(min_length=1, max_length=200)
    limit: int = Field(default=20, ge=1, le=50)


class _FileRead(_Arguments):
    path: str = Field(min_length=1, max_length=512)
    start_line: int = Field(default=1, ge=1)
    line_count: int = Field(default=60, ge=1, le=120)


class _FilePatch(_Arguments):
    path: str = Field(min_length=1, max_length=512, description="现有文件的相对路径")
    old_text: Annotated[
        str, StringConstraints(strip_whitespace=False, min_length=1, max_length=32768)
    ] = Field(description="从读到的文件复制、能唯一匹配的原文，保留空格和换行")
    new_text: Annotated[str, StringConstraints(strip_whitespace=False, max_length=32768)] = Field(
        description="替换文本，保留必要的空格和换行"
    )


class _BatchPatch(_Arguments):
    edits: list[_FilePatch] = Field(min_length=1, max_length=8)


class _Check(_Arguments):
    name: str = Field(min_length=1, max_length=40)


def _parameters(arguments: type[BaseModel]) -> dict[str, Any]:
    schema = arguments.model_json_schema()
    if arguments is _BatchPatch:
        # Inline the array item so gateways can pass the full shape to the model.
        schema.pop("$defs", None)
        schema["properties"]["edits"]["items"] = _FilePatch.model_json_schema()
    return schema


_TOOLS = {
    "search_knowledge": (_KnowledgeQuery, "从当前知识库检索片段、来源编号和文件名。"),
    "list_files": (_FileList, "列出授权目录下的相对文件路径，可指定子目录。"),
    "search_files": (_FileSearch, "在 UTF-8 文件中搜索字面文本，返回路径与行号。"),
    "read_file": (_FileRead, "读取指定相对路径的 UTF-8 文本，可按行分页。"),
}


class KnowledgeClient:
    def __init__(
        self, http: httpx.AsyncClient, api_base_url: str, workspace_id: UUID, access_token: str
    ) -> None:
        api_root = api_base_url.rstrip("/").removesuffix("/api/v1") + "/api/v1"
        self._http = http
        self._url = f"{api_root}/workspaces/{workspace_id}/search"
        self._workspace_id = workspace_id
        self._access_token = access_token

    async def search(self, query: str, limit: int) -> list[KnowledgeSearchHit]:
        try:
            response = await self._http.post(
                self._url,
                headers={"Authorization": f"Bearer {self._access_token}"},
                json={"query": query, "limit": limit},
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            raise AgentError(f"知识库检索返回 HTTP {error.response.status_code}。") from error
        except httpx.RequestError as error:
            raise AgentError("无法连接 KnowTrace 检索接口。") from error
        try:
            data = KnowledgeSearchResponse.model_validate_json(response.content)
        except ValidationError as error:
            raise AgentError("KnowTrace 检索接口返回了无效数据。") from error
        if data.workspace_id != self._workspace_id:
            raise AgentError("检索结果与所选知识库不一致。")
        return data.hits[:limit]


PatchTool = Callable[..., Awaitable[dict[str, str]]]
BatchTool = Callable[[list[dict[str, str]]], Awaitable[dict[str, Any]]]


class WorkspaceTools:
    def __init__(
        self,
        knowledge: KnowledgeClient,
        files: WorkspaceFiles,
        apply_patch: PatchTool | None = None,
        *,
        apply_patches: BatchTool | None = None,
        verification: Verification | None = None,
    ) -> None:
        self._knowledge = knowledge
        self._apply_patch = apply_patch
        self._apply_patches = apply_patches
        self.verification = verification
        self._definitions = _TOOLS.copy()
        self._file_actions = {
            "list_files": files.list_files,
            "search_files": files.search_files,
            "read_file": files.read_file,
        }
        if apply_patch is not None:
            self._definitions["apply_patch"] = (
                _FilePatch,
                "预览单个现有文本文件的替换 diff。仅在用户确认后写入并返回回退 ID。",
            )
        if apply_patches is not None:
            self._definitions["apply_patches"] = (
                _BatchPatch,
                "提出一批相关文件的 diff。每个文件只能出现一次，old_text 须取自该文件并唯一匹配，"
                "new_text 须与原文不同。批次失败时根据指出的文件修正。",
            )
        if verification and verification.commands:
            names = ", ".join(verification.commands)
            self._definitions["run_check"] = (
                _Check,
                f"在隔离工作树内运行已授权的命令，并返回退出码和日志。可选名称：{names}。",
            )
        self.sources: dict[UUID, tuple[str, KnowledgeSearchHit]] = {}

    def definitions(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": description,
                    "parameters": _parameters(arguments),
                },
            }
            for name, (arguments, description) in self._definitions.items()
        ]

    async def _search_knowledge(self, query: str, limit: int) -> dict[str, object]:
        hits = await self._knowledge.search(query, limit)
        matches = []
        for hit in hits:
            source, _ = self.sources.setdefault(hit.chunk_id, (f"K{len(self.sources) + 1}", hit))
            matches.append(
                {
                    "source": source,
                    "chunk_id": str(hit.chunk_id),
                    "citation": hit.citation.model_dump(mode="json"),
                    "excerpt": hit.content[:1200],
                }
            )
        return {"matches": matches}

    async def call(self, tool_call: ToolCall) -> str:
        definition = self._definitions.get(tool_call.name)
        if definition is None:
            return json.dumps({"error": "该工具未授权。"}, ensure_ascii=False)
        try:
            arguments = definition[0].model_validate_json(tool_call.arguments).model_dump()
        except ValidationError as error:
            field = error.errors(include_input=False, include_url=False)[0]
            location = ".".join(map(str, field["loc"]))[:80] or "arguments"
            message = f"工具参数无效：{location} · {field['msg']}。请按工具定义重试。"
            return json.dumps({"error": message}, ensure_ascii=False)
        if tool_call.name == "search_knowledge":
            result = await self._search_knowledge(**arguments)
        else:
            try:
                if tool_call.name == "apply_patch" and self._apply_patch is not None:
                    result = await self._apply_patch(**arguments)
                elif tool_call.name == "apply_patches" and self._apply_patches is not None:
                    result = await self._apply_patches(arguments["edits"])
                elif tool_call.name == "run_check" and self.verification is not None:
                    result = await self.verification.run(arguments["name"])
                else:
                    result = await asyncio.to_thread(
                        self._file_actions[tool_call.name], **arguments
                    )
            except AgentError:
                raise
            except (OSError, RuntimeError):
                result = {"error": "无法访问指定的本地路径。"}
            except ValueError as error:
                result = {"error": str(error)}
        if (
            self.verification is not None
            and tool_call.name in {"apply_patch", "apply_patches"}
            and result.get("status") != "rejected"
        ):
            self.verification.invalidate()
        return json.dumps(result, ensure_ascii=False)
