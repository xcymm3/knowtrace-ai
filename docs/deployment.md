# KnowTrace 部署说明

完整的容器部署由五类资源构成：Next.js、FastAPI、ARQ Worker、Redis 和 Supabase。前四者的职责不能互相替代。

| 资源 | 持续运行需求 | 关键配置 |
| --- | --- | --- |
| Next.js | HTTP 服务 | `API_PROXY_TARGET` 指向 FastAPI 地址。 |
| FastAPI | HTTP 服务 | Supabase、Redis、Embedding、LLM 配置。 |
| ARQ Worker | 持续消费队列 | 与 API 相同的 Supabase、Redis、Embedding 配置。 |
| Redis | 持续服务 | API/Worker 共同使用的 `REDIS_URL`。 |
| Supabase | 托管服务 | PostgreSQL、pgvector、私有 Storage。 |

## 推荐方式：Docker Compose

小型演示或自托管环境直接使用根目录 `docker-compose.yml`。部署前执行 Supabase Migration，填好 `.env`，然后运行：

```powershell
docker compose up --build -d
docker compose ps
```

为公网部署设置：

- `CORS_ORIGINS`：前端公网域名，例如 `https://app.example.com`。
- `API_PROXY_TARGET`：Next.js 服务到 FastAPI 服务的内部或公网地址。
- `NEXT_PUBLIC_APP_URL`：前端公网地址。
- `SUPABASE_URL`、`SUPABASE_SERVICE_ROLE_KEY`、`REDIS_URL`、`EMBEDDING_*`、`LLM_*`：仅部署环境变量，不进入代码库。当前后端通过 Supabase REST API 访问业务数据，`DATABASE_URL` 仅在 Docker Compose 配置中保留，不是 Vercel API 的运行时前提。

## 使用 Vercel 的边界

Vercel 适合承载 Next.js 前端和短生命周期的 FastAPI 路由，但不适合作为持续消费 Redis 队列的 Worker 运行环境。KnowTrace 在 `TASK_EXECUTION_MODE=auto` 时会识别 Vercel 环境，并使用与 Worker 共用的处理函数在上传请求内完成短文件的解析与索引。

1. Vercel 可承载登录、知识库读写、提问和短文件解析；需配置 `SUPABASE_*`、`EMBEDDING_*` 与 `LLM_*`，不必为内联模式配置 Redis。
2. 对大文件、批量导入或需要稳定吞吐的场景，仍应在容器平台运行 ARQ Worker，并提供托管 Redis；此时设置 `TASK_EXECUTION_MODE=queue`。
3. 如 FastAPI 部署在 Vercel 之外，将 Vercel 的 `API_PROXY_TARGET` 设置为该服务 HTTPS 地址，并在 FastAPI 的 `CORS_ORIGINS` 添加前端域名。
4. 不要把任何 `SUPABASE_SERVICE_ROLE_KEY`、Embedding Key 或 LLM Key 配置为 `NEXT_PUBLIC_*`。

现有 `vercel.json` 描述前端与 API 路由关系；容器模式仍是完整异步处理与横向扩展的推荐方案。

## Agent 模型档案

Agent 模型在执行 CLI 的本机配置。Web 工作台的 `--serve` 执行器同样使用本机选择的档案。
知识库的 Embedding 和 Web 普通问答仍由 FastAPI 的 `EMBEDDING_*` 和 `LLM_*` 配置提供。
未指定档案时，CLI 继续读取既有 `DEEPSEEK_API_KEY`、`AGENT_*` 或 `LLM_*` 配置。

在本机保存一份模型档案 JSON。可按提供商公布的地址和模型 ID 修改以下示例。
密钥只放入启动 CLI 的终端环境，JSON 中的 `api_key_env` 指向变量名。

```json
{
  "deepseek": {
    "protocol": "openai-chat",
    "base_url": "https://api.deepseek.com",
    "model": "deepseek-flash",
    "api_key_env": "DEEPSEEK_API_KEY"
  },
  "local": {
    "protocol": "openai-chat",
    "base_url": "http://127.0.0.1:11434/v1",
    "model": "qwen3:8b"
  },
  "messages": {
    "protocol": "anthropic-messages",
    "base_url": "https://api.siliconflow.cn",
    "model": "deepseek-ai/DeepSeek-V4-Flash",
    "api_key_env": "SILICONFLOW_API_KEY",
    "auth": "bearer"
  }
}
```

- `openai-chat` 在基础地址后拼接 `/chat/completions`。使用 `local` 档案前，启动 Ollama 并选择
  已安装的模型，本机服务可以省略密钥配置。若网关要求
  使用 `max_completion_tokens`，在档案内设置 `"token_field": "max_completion_tokens"`。 [Ollama 兼容接口](https://github.com/ollama/ollama/blob/main/docs/api/openai-compatibility.mdx)
- `anthropic-messages` 请求 `/v1/messages`，基础地址可包含已有的 `/v1` 或服务商前缀。原生
  Anthropic 档案使用 `https://api.anthropic.com` 及对应模型 ID，默认通过 `x-api-key` 认证。
  SiliconFlow 等使用 Bearer 的兼容服务可设置 `"auth": "bearer"`。 [SiliconFlow Messages](https://api-docs.siliconflow.cn/docs/api/messages-post) · [Anthropic Messages](https://platform.claude.com/docs/en/api/messages)
- 远程地址使用 HTTPS。模型探测只发送合成文本和合成工具回执，无需登录知识库或指定本地项目。

```powershell
Set-Location backend
$env:DEEPSEEK_API_KEY = Read-Host 'DeepSeek API Key' -MaskInput
$env:SILICONFLOW_API_KEY = Read-Host 'SiliconFlow API Key' -MaskInput
uv run python -m app.features.agent --model-config "D:\projects\models.json" --profile deepseek --check-model
```

`--check-model` 分别返回 `text_streaming`、`tool_calling` 和 `tool_round_trip`。探测工具往返时，
模型须先发起结构化调用，再在下一次响应中读出执行器生成的回执。命名档案在任务启动时也会检查这条链路。
用 `--chat "你的问题"` 可发起纯文本问答。加上 `--workspace-id` 和同一用户的 Supabase Access Token，
即可由 CLI 预先检索知识库并在回答下方列出引用。

将 `--model-config "D:\projects\models.json" --profile messages` 附加到 [本地执行器命令](../backend/README.md#在-web-工作台运行)
或 [隔离工作树任务命令](../backend/README.md#隔离工作树和自动验证) 即可使用该档案。
切换正在运行的 Web 执行器时，待当前任务结束后重启，再使用 `--executor-id` 复用配对 ID。

可运行同一套跨协议验收，验证工具结果回传、审批写入，以及失败日志驱动的修正和复测。

```powershell
uv run --locked python -m pytest tests/test_agent_models.py
```
