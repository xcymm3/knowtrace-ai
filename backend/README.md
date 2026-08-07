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
