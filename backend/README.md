# CommerceLens API

FastAPI 是 CommerceLens AI 的唯一业务 API 层。Next.js 不直接连接 Supabase；浏览器的资料上传、调研任务、报告查询与后续 SSE 进度均经由本服务。

## 本地运行

```powershell
uv sync --group dev
uv run uvicorn app.main:app --reload --port 8000
```

访问 `http://localhost:8000/docs` 查看自动生成的 OpenAPI 文档。

## 当前接口

- `GET /`：服务身份与文档入口。
- `GET /api/v1/health`：存活探针，不依赖外部服务。
- `GET /api/v1/ready`：配置就绪探针，仅返回 Supabase 是否已配置，不暴露任何密钥。
- `POST /api/v1/projects/{project_id}/documents`：上传调研资料并创建解析任务。
- `POST /api/v1/projects/{project_id}/search`：返回语义与关键词混合检索结果，以及来源引用。
- `POST/GET/PATCH /api/v1/projects`：创建、浏览和编辑调研项目。
- `POST/GET/PATCH /api/v1/projects/{project_id}/products`：维护自有候选商品与竞品。
- `GET /api/v1/projects/{project_id}/comparison`：比较价格带和资料覆盖度。
- `POST/GET /api/v1/projects/{project_id}/reports`：生成或查看带证据引用的选品报告。
- `POST /api/v1/projects/{project_id}/reports/{report_id}/feedback`：记录审核反馈。

## 后台 Worker

资料上传创建 `PARSE_DOCUMENT` 任务后会写入 Redis。另开一个终端运行 Worker：

```powershell
uv run arq app.worker.WorkerSettings
```

Worker 读取原始资料、提取文本或图片元数据，并将解析结果写回 Supabase Storage 与任务记录。含文本的资料会自动创建 `GENERATE_EMBEDDINGS` 任务，完成切分和向量化。失败任务最多重试三次；浏览器通过 SSE 读取任务状态，不会直接连接 Redis。

## Embedding 配置

在根目录 `.env` 中填写 `EMBEDDING_BASE_URL`、`EMBEDDING_API_KEY` 和 `EMBEDDING_MODEL`。服务采用 OpenAI-compatible `POST /embeddings` 协议；当前 pgvector 表固定使用 1536 维向量，因此 `EMBEDDING_DIMENSIONS` 必须为 `1536`。这仅用于文本检索，不需要任何生图 API。

报告目前采用确定性的证据规则：它基于商品角色、价格及已索引资料生成待审核结论，并为每条结论保存引用；后续可在不改变引用模型的前提下接入 LLM 辅助归纳。

## 容器运行

使用根目录 `docker-compose.yml` 可同时启动 API、Redis Worker、Redis 和 Next.js 工作台；Supabase 仍为外部托管服务。完整的环境变量、Migration、演示数据与验收步骤见 [Docker Compose 运行说明](../docs/run-with-docker.md)。
