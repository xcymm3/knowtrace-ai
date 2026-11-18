# KnowTrace API

FastAPI 是 KnowTrace 的唯一业务 API 层。浏览器通过 Next.js 同域代理访问 API，不直接获得 Supabase Service Role key，也不直连 Storage 或 Redis。

## 本地运行

从仓库根目录复制 `.env.example` 为 `.env` 并填写连接信息后：

```powershell
cd backend
$env:UV_PROJECT_ENVIRONMENT='.venv-knowtrace'
uv sync --group dev
uv run uvicorn app.main:app --reload --port 8000
```

另开一个终端启动后台 Worker：

```powershell
cd backend
$env:UV_PROJECT_ENVIRONMENT='.venv-knowtrace'
uv run arq app.worker.WorkerSettings
```

访问 `http://localhost:8000/docs` 查看 OpenAPI 文档。

## Agent CLI

启动 KnowTrace API，登录并准备一个已有索引资料的知识库。CLI 使用当前用户的
Supabase Access Token 调用现有检索接口。在 PowerShell 中输入临时令牌和 DeepSeek API Key。

```powershell
Set-Location backend
$env:DEEPSEEK_API_KEY = Read-Host 'DeepSeek API Key' -MaskInput
$env:KNOWTRACE_ACCESS_TOKEN = Read-Host 'Supabase Access Token' -MaskInput
uv run python -m app.features.agent `
  --root "D:\projects\example" `
  --workspace-id "<知识库 UUID>" `
  "对照知识库里的部署说明，找出本地 README 中启动步骤的差异，给出来源和文件行号。"
```

- `DEEPSEEK_API_KEY` 或 `AGENT_API_KEY` 配合默认端点 `https://api.deepseek.com` 和模型
  `deepseek-flash` 使用。兼容网关可在自己的 `.env` 中单独设置
  `AGENT_API_KEY`、`AGENT_BASE_URL` 和 `AGENT_MODEL`。未设置 Agent 专用配置时，
  CLI 复用现有 `LLM_*` 连接。
- `--api-base-url` 或 `KNOWTRACE_API_BASE_URL` 可指定 KnowTrace API，默认
  `http://127.0.0.1:8000`。`--max-steps` 控制模型请求轮数，默认 8。
- CLI 逐段输出模型文本，显示调用过的工具和检索片段 ID。文件工具只在指定目录内列出文件、
  按字面搜索并分页读取 UTF-8 文本，单文件读取上限为 256 KiB。
- 模型服务会收到任务、检索片段和工具读取的文本。请将 `--root` 指向允许发送内容的项目目录。
  文件工具会跳过常见密钥文件、依赖目录和链接。

### 修改与回退

CLI 默认只读。给任务加上 `--edit` 后，Agent 可以对已有 UTF-8 文本文件提出单文件补丁。
终端显示 diff 后，输入 `y` 才会重新检查原始字节并写入。回车或其他输入会拒绝变更。

```powershell
uv run python -m app.features.agent `
  --root "D:\projects\example" `
  --workspace-id "<知识库 UUID>" `
  --edit "根据知识库中的部署说明，修正本地 README 的启动步骤。"
```

写入成功后会显示回退 ID。使用相同的 `--root`，预览并确认反向 diff 后即可离线回退。
回退只在文件内容仍与该次写入的结果一致时执行，以免覆盖后续改动。

```powershell
uv run python -m app.features.agent --root "D:\projects\example" --undo "<回退 ID>"
```

回退记录保存原始文件内容。Windows 默认保存在 `%LOCALAPPDATA%\KnowTrace\agent`，其他系统使用
`$XDG_STATE_HOME/knowtrace/agent` 或 `~/.local/state/knowtrace/agent`。
可以用 `KNOWTRACE_AGENT_STATE_DIR` 指定其他位置。Git 仓库可照常用 `git diff` 检查改动。

## 核心接口

| 能力 | 接口 |
| --- | --- |
| 健康检查 | `GET /api/v1/health`、`GET /api/v1/ready` |
| 工作区 | `POST/GET /api/v1/workspaces`、`GET/PATCH /api/v1/workspaces/{workspace_id}` |
| 文件 | `GET/POST /api/v1/workspaces/{workspace_id}/documents` |
| 任务 | `GET /api/v1/tasks/{task_id}`、`GET /api/v1/tasks/{task_id}/events` |
| 检索 | `POST /api/v1/workspaces/{workspace_id}/search` |
| 会话 | `POST/GET /api/v1/workspaces/{workspace_id}/conversations` |
| 消息 | `GET /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages` |
| 流式回答 | `POST /api/v1/workspaces/{workspace_id}/conversations/{conversation_id}/messages/stream` |

## 模型与安全边界

- `EMBEDDING_*` 配置用于解析完成后的向量化和检索查询；当前 pgvector 维度固定为 1536。
- `LLM_*` 配置由 LangChain 使用，要求提供 OpenAI-compatible Chat Completions 端点。
- 回答只使用当前工作区检索到的资料；当资料不足时，服务要求模型明确说明不确定性。
- `SUPABASE_SERVICE_ROLE_KEY`、Embedding Key 和 LLM Key 只能存在 API/Worker 进程环境中，绝不能使用 `NEXT_PUBLIC_*` 前缀。

完整环境变量和容器运行方式见仓库根目录的 [部署说明](../docs/deployment.md)。
