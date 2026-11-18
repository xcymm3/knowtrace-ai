# KnowTrace Agent

KnowTrace 是在本机运行的文件 Agent。通过会话发起任务、查看工具记录、审批变更并继续提问。会话和审批存储在本机 SQLite。

## 启动

需要 Git、Node.js、pnpm 和 uv。从仓库根目录运行：

```powershell
pnpm install --frozen-lockfile
pnpm dev:local
```

打开 [本机工作台](http://127.0.0.1:3001)。启动器同时运行 Next.js、FastAPI 和内置执行器。此版本的工作台无需登录，也无需 Supabase、Redis 或 Docker。

## 模型

在根目录的 `.env` 配置 `DEEPSEEK_API_KEY`。使用 OpenAI 兼容服务时可设置 `AGENT_BASE_URL`、`AGENT_MODEL` 和 `AGENT_API_KEY`。通过环境变量 `LOCAL_AGENT_MODEL_CONFIG` 和 `LOCAL_AGENT_PROFILE` 可以选择配置文件里的 OpenAI 兼容或 Anthropic Messages 档案。参见[模型与安全边界](backend/README.md#模型与安全边界)。

## 文件权限

| 权限 | 任务可用的文件操作 |
| --- | --- |
| 只读 | 查看、搜索和读取项目文件。 |
| 项目工作树 | 在独立 Git 工作树中读写，审批后写入，按本机命令清单运行验证。 |
| 完全访问 | 在当前 Windows 用户可访问的本机磁盘路径读取、修改 UTF-8 文本文件，或创建文件、空文件夹。 |

权限在发起任务时写入记录。所有写操作都会展示确认；「完全访问」使用当前账户权限。普通模型任务读取的文件内容可能发送给配置的模型提供方。

例如选择「完全访问」，输入「在 D 盘创建一个空文件夹，名为 AgentDemo」，核对预览的 `D:\AgentDemo` 后点「确认写入」。输入「在桌面新建一个 123.txt」同样可以直接创建。明确的这两类任务由本机执行器处理，无需调用模型。

可用 `LOCAL_AGENT_ROOT` 指定默认项目目录，用 `LOCAL_AGENT_COMMANDS` 指定工作树检查命令清单。参见[审批与回退](backend/README.md#在-web-工作台运行)。

## 验证

```powershell
pnpm lint
pnpm build
pnpm test:e2e
Set-Location backend
uv run --locked python -m pytest
```

旧版本的知识库迁移和 API 源码保留用于历史部署维护，当前本机 Agent 的接口和 UI 独立运行。
