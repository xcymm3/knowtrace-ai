# KnowTrace API 契约（MVP）

接口根路径为 `/api/v1`。错误统一返回：

```json
{ "error": { "code": "MACHINE_READABLE_CODE", "message": "面向用户的中文提示" } }
```

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/health` | 进程存活检查，不访问外部依赖。 |
| `GET` | `/ready` | 配置就绪状态，不返回密钥。 |
| `POST/GET` | `/workspaces` | 创建或列出工作区。 |
| `GET/PATCH` | `/workspaces/{workspace_id}` | 查询或更新工作区。 |
| `GET/POST` | `/workspaces/{workspace_id}/documents` | 查看资料，或上传文件并创建解析任务。 |
| `POST` | `/workspaces/{workspace_id}/search` | 工作区内混合检索，返回可追溯片段。 |
| `GET` | `/tasks/{task_id}` | 查询任务状态。 |
| `GET` | `/tasks/{task_id}/events` | SSE 任务状态流。 |
| `GET` | `/tasks/workspaces/{workspace_id}` | 查询工作区任务。 |
| `POST/GET` | `/workspaces/{workspace_id}/conversations` | 创建或列出对话。 |
| `GET` | `/workspaces/{workspace_id}/conversations/{conversation_id}/messages` | 读取带引用的历史消息。 |
| `POST` | `/workspaces/{workspace_id}/conversations/{conversation_id}/messages/stream` | 以 SSE 输出检索结果、文本增量和完成消息。 |

## RAG 流事件

流式回答依次可能包含：

1. `retrieval`：本次检索到的资料片段、文件名和相关度。
2. 一个或多个 `token`：`{ "delta": "…" }` 文本增量。
3. `complete`：已保存的助手消息和最终引用。
4. `error`：生成中断时的脱敏错误码与中文说明。

前端通过 `fetch` 读取 POST SSE 流；浏览器的 `EventSource` 仅用于任务进度，因为它不支持 POST 请求体。
