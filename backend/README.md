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

### 在 Web 工作台运行

先应用 [Agent 任务迁移](../supabase/migrations/20261118000000_create_agent_runs.sql)，并部署包含 Agent
接口的 FastAPI。启动本地执行器前，用前面的配置设置模型和 `KNOWTRACE_ACCESS_TOKEN`。
令牌需属于当前登录 Web 工作台的用户。

```powershell
Set-Location backend
uv run python -m app.features.agent --serve `
  --root "D:\projects\example" `
  --workspace-id "<知识库 UUID>" `
  --api-base-url "http://127.0.0.1:8000"
```

打开对应知识库的 **Agent 任务**，填入终端打印的执行器 ID，提交任务。工具记录和 diff 会显示在任务页。
点击 **确认写入** 后，本地执行器会校验预览版本并写入。点击 **拒绝变更** 可保留任务的回答，
点击 **取消任务** 则结束后续执行。如果写入已经开始，界面仍会记录写入结果及回退 ID。

任务、工具记录、diff 和审批保存在 Supabase。diff 可能包含本地文件原文，请只选择允许同步这些内容的目录。
刷新页面可以恢复选中的任务。浏览器断线时执行器可继续运行，执行器与 API 短暂断线后会重试同一请求。
执行器进程退出后，已领取的任务不会自动重新执行。重新启动时可以通过 `--executor-id` 复用原 ID，
并从工作台取消尚未进入写入阶段的旧任务。

### 隔离工作树和自动验证

`--serve` 为每个 Web 任务创建独立的 Git 工作树。终端任务可用 `--worktree` 启用同样的隔离模式。
两种模式的 `--root` 都指向 Git 仓库根目录。工作树以已提交的 `HEAD` 为基线，包含仓库中的
`AGENTS.md`。暂存、未暂存和未跟踪的内容留在原目录。结果保留在终端打印的工作树中，供检查和接收。

以本项目为例，在本机创建一份 JSON 清单，键是 Agent 可以请求的命令名，值是固定的参数数组。
命令在隔离工作树根目录执行。Windows 下首项可用 `uv.exe`、`node.exe` 或其他可执行文件的全路径。

```json
{
  "build": ["uv.exe", "run", "--project", "backend", "--locked", "python", "-m", "compileall", "-q", "backend/app"],
  "lint": ["uv.exe", "run", "--project", "backend", "--locked", "ruff", "check", "backend"],
  "test": ["uv.exe", "run", "--project", "backend", "--locked", "python", "-m", "pytest", "backend/tests"]
}
```

```powershell
Set-Location backend
uv run python -m app.features.agent `
  --worktree --root "D:\projects\example" --workspace-id "<知识库 UUID>" `
  --commands "D:\projects\commands.json" `
  "统一代码、配置和 README 中的启动端口，并执行验证。"
```

Web 执行器可在 `--serve` 命令后追加 `--commands`。Agent 只能请求清单中的名称，子进程会获得
精简后的环境变量。命令按当前本机用户的权限执行，请授权可信的构建、Lint 和测试命令。
工作树需要的依赖可由授权命令准备，例如在运行前端构建前按锁文件安装依赖。

一批可预览并确认最多 8 个现有文本文件。每次批准写入后都要验证新版本，检查失败时真实退出码与日志
会交给 Agent 继续修正。Web 执行记录保留每次检查结果和修改的回退 ID。批量回退时，`--root` 指向
终端打印的工作树，使用对应批次的 `--undo` ID。
部署 Web 多轮审批前需追加应用 [审批历史迁移](../supabase/migrations/20261118010000_preserve_agent_approval_history.sql)。

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
| Agent 任务 | `GET/POST /api/v1/workspaces/{workspace_id}/agent/runs`，任务下有详情、事件流、审批和取消接口 |

## 模型与安全边界

- `EMBEDDING_*` 配置用于解析完成后的向量化和检索查询；当前 pgvector 维度固定为 1536。
- `LLM_*` 配置由 LangChain 使用，要求提供 OpenAI-compatible Chat Completions 端点。
- 回答只使用当前工作区检索到的资料；当资料不足时，服务要求模型明确说明不确定性。
- `SUPABASE_SERVICE_ROLE_KEY`、Embedding Key 和 LLM Key 只能存在 API/Worker 进程环境中，绝不能使用 `NEXT_PUBLIC_*` 前缀。

完整环境变量和容器运行方式见仓库根目录的 [部署说明](../docs/deployment.md)。
