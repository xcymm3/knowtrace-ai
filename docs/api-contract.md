# CommerceLens API 契约（MVP）

FastAPI 是浏览器访问 CommerceLens 数据与文件的唯一入口。Next.js 不直连 Supabase；所有需要 Service Role 的操作均由 API 或 Worker 完成。

## 已实现：系统接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `GET` | `/` | 服务名称、版本与 OpenAPI 文档入口 |
| `GET` | `/api/v1/health` | 存活探针；不访问 Supabase 或 Redis |
| `GET` | `/api/v1/ready` | 配置就绪探针；仅返回 Supabase 是否完整配置 |
| `GET` | `/api/v1/openapi.json` | OpenAPI 3 规范 |
| `POST` | `/api/v1/projects/{project_id}/documents` | 上传调研资料，写入 Storage、创建资料记录与待解析任务 |
| `GET` | `/api/v1/tasks/{task_id}` | 读取解析、Embedding 或报告任务状态 |
| `GET` | `/api/v1/tasks/{task_id}/events` | 通过 SSE 推送任务状态变化 |
| `POST` | `/api/v1/projects/{project_id}/search` | 对已索引资料做混合检索，并返回可追溯引用 |
| `POST` | `/api/v1/projects` | 创建选品调研项目 |
| `GET` | `/api/v1/projects` | 获取调研项目列表 |
| `GET/PATCH` | `/api/v1/projects/{project_id}` | 查看或编辑调研项目 |
| `POST/GET` | `/api/v1/projects/{project_id}/products` | 录入或查看自有候选商品与竞品 |
| `PATCH` | `/api/v1/projects/{project_id}/products/{product_id}` | 编辑商品或竞品资料 |
| `GET` | `/api/v1/projects/{project_id}/comparison` | 查看价格带和资料覆盖度对比 |
| `POST/GET` | `/api/v1/projects/{project_id}/reports` | 基于已索引证据生成或查看选品报告 |
| `GET` | `/api/v1/projects/{project_id}/reports/{report_id}` | 查看报告结论及其引用来源 |
| `POST` | `/api/v1/projects/{project_id}/reports/{report_id}/feedback` | 审批、驳回或标注报告/结论反馈 |

## 响应原则

- 成功响应使用资源对象或 `{ "data": ... }` 结构；后续业务接口会在 Pydantic Schema 中固定字段。
- 错误响应统一为 `{ "error": { "code": string, "message": string } }`。
- 任何文件下载均由 FastAPI 签发短时 URL，不向浏览器暴露 Supabase Service Role Key。
- SSE 只推送任务状态、进度和安全错误摘要，不推送原始文件内容或密钥。
- 知识检索结果包含来源文件、资料类型、关联商品与文本片段位置，供后续报告和人工复核引用；不向浏览器暴露 Storage 内部路径。
- 报告使用已上传资料的片段作为结论引用。当前版本按商品角色、价格和资料覆盖度生成可复核的规则化报告，不把规则结果伪装为模型判断。
