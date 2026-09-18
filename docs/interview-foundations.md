# KnowTrace AI 面试基础复习

这份笔记服务于“全栈工程师（偏前端）”的第一轮面试。重点不是背概念定义，而是能把概念和 KnowTrace AI 的实际实现对应起来。回答时优先按“它解决什么问题、项目里怎么用、为什么这样做”来讲。

## 1. 先用一分钟介绍项目

KnowTrace AI 是一个面向个人资料的可追溯知识库工作台。用户先创建私有工作区，再上传 PDF、Word、Excel、Markdown、CSV 等文件。系统提取文件中的文本，按段落切成较小的文本块，为每个文本块生成向量并保存。用户提问时，系统只在当前工作区的资料中检索相关内容，把检索到的文本块作为上下文交给大模型生成答案。

它和普通聊天机器人的区别在于“可追溯”：每段回答都能显示引用来源，例如文件名、文本块位置和片段。用户能回到原始资料核对答案依据。

前端使用 Next.js、React 和 TypeScript；后端使用 FastAPI；Supabase 提供认证、PostgreSQL 数据库、pgvector 向量扩展和对象存储。Docker 部署时，Redis 和 ARQ Worker 把耗时的文件解析、切块、向量化放到异步任务中完成。

可以用下面这张流程图帮助理解：

```text
浏览器 React 页面
    │ 上传、提问、显示引用、实时显示回答
    ▼
Next.js 前端 / FastAPI 接口
    │                 │
    │                 ├── 身份校验、业务逻辑、检索与流式生成
    ▼                 ▼
Supabase Storage     PostgreSQL + pgvector
原始文件/解析文本       用户、工作区、文档、分块、向量、会话、引用
                          ▲
                          │
               Redis ← ARQ Worker
              异步任务     解析、切块、向量化、写回数据库
```

## 2. React：用组件组织页面

React 是构建网页界面的 JavaScript 库。它把页面拆成可复用的**组件**。组件本质上通常是一个函数：接收输入数据，返回页面应该长什么样。

```tsx
type DocumentCardProps = {
  name: string;
  status: "queued" | "running" | "succeeded" | "failed";
};

export function DocumentCard({ name, status }: DocumentCardProps) {
  return (
    <article>
      <strong>{name}</strong>
      <span>处理状态：{status}</span>
    </article>
  );
}
```

这里 `DocumentCard` 是组件，`name`、`status` 是组件的 `props`，也就是父组件传进来的数据。组件不应直接修改 props；需要改变内容时，应该通知父组件或更新自己的状态。

### 2.1 JSX

JSX 是一种写在 TypeScript/JavaScript 中、外形接近 HTML 的语法。它最终会被编译为 React 创建页面元素的代码。JSX 中用花括号插入 JavaScript 表达式：`{name}`。属性名称多数用驼峰写法，例如 `className`、`onClick`。

列表渲染要给每项稳定的 `key`，用于让 React 识别哪一项被新增、删除或移动。不要把数组下标当作会变化列表的 key；文档列表应该用文档 ID。

```tsx
{documents.map((document) => (
  <DocumentCard key={document.id} name={document.name} status={document.status} />
))}
```

### 2.2 状态和单向数据流

**状态（state）**是组件会随用户操作或请求结果而变化的数据。比如上传中的文件列表、输入框内容、正在生成的回答。`useState` 返回当前值和更新函数。

```tsx
const [question, setQuestion] = useState("");
const [isSending, setIsSending] = useState(false);
```

不要直接写 `question = "..."` 来改状态；应调用 `setQuestion`。React 收到状态更新后会重新渲染组件。

React 的数据通常从父组件向子组件传递，这叫单向数据流。若两个组件都需要同一份数据，通常把状态提升到它们共同的父组件，或使用 Context/状态管理工具。对于 KnowTrace AI，当前工作区、当前会话、文档列表和消息列表都属于页面层的共享状态。

### 2.3 事件、表单和受控组件

按钮点击、输入框变化、文件选择都是事件。受控输入框把输入值放到 React state 中，因此界面与数据始终同步。

```tsx
<input
  value={question}
  onChange={(event) => setQuestion(event.target.value)}
  placeholder="向知识库提问"
/>
```

提交表单时要防止浏览器默认刷新：`event.preventDefault()`。随后检查输入、设置 loading 状态、调用接口，最后在 `finally` 中恢复 loading 状态。失败不能只在控制台打印；应给用户可理解的提示并允许重试。

### 2.4 useEffect：处理副作用

渲染的目标是描述界面。请求接口、订阅事件、设置计时器等会影响组件外部世界的行为叫副作用，通常放在 `useEffect` 中。

```tsx
useEffect(() => {
  loadDocuments(workspaceId);
}, [workspaceId]);
```

依赖数组表示何时重新执行。当 `workspaceId` 改变时重新加载文档。异步请求可能在组件卸载或工作区切换后才返回，因此要考虑取消请求或忽略过期结果，避免旧工作区的数据覆盖新工作区。

常见错误是依赖项漏写，导致读取了旧状态；或把每次渲染都新建的对象放进去，导致无限请求。面试中不必背规则细节，但要知道 Effect 用于同步外部系统，清理函数可取消订阅、请求或定时器。

### 2.5 状态设计和性能意识

状态应该尽量保存“源数据”，能由现有数据计算出的值不要重复保存。例如 `hasFailedDocuments` 可由文档状态计算，而不必再维护一个可能不同步的布尔值。

不要一看到重新渲染就急于优化。React 重新渲染不等于浏览器会重新创建整个 DOM。出现大列表、昂贵计算或回调导致大量子组件重复渲染时，再用 `useMemo`、`useCallback`、`React.memo` 等工具，并通过性能分析确认收益。

## 3. TypeScript：让错误更早出现

TypeScript 是 JavaScript 的超集，为变量、函数、接口数据增加静态类型检查。它主要在开发和构建阶段发现问题，运行到浏览器后仍是 JavaScript。

在前后端项目中，类型最实际的价值是：接口字段拼错、遗漏空值处理、把字符串当数字、调用参数顺序错误等问题，会在运行前暴露。

### 3.1 常见类型

```ts
const title: string = "KnowTrace AI";
const count: number = 3;
const finished: boolean = false;
const tags: string[] = ["RAG", "React"];

type TaskStatus = "queued" | "running" | "succeeded" | "failed" | "cancelled";

interface KnowledgeDocument {
  id: string;
  filename: string;
  taskStatus: TaskStatus;
  errorMessage?: string;
}
```

联合类型如 `TaskStatus` 限制状态只能是列出的值。`?` 表示可选字段，读取时可能是 `undefined`，应处理这个情况。`interface` 与 `type` 都能描述对象形状；日常业务代码选一种团队约定并保持一致即可。

### 3.2 unknown、any 和类型收窄

`any` 会关闭类型检查，适合极少数过渡场景，但滥用会失去 TypeScript 的意义。外部输入，例如网络错误、JSON、用户输入，初始更适合看作 `unknown`。先判断后使用，叫**类型收窄**。

```ts
function getErrorMessage(error: unknown) {
  if (error instanceof Error) return error.message;
  return "发生未知错误";
}
```

接口返回的数据也不能仅凭 TypeScript 就相信。类型只在编译时存在；后端、第三方服务或旧版本客户端仍可能给出不符合预期的数据。重要接口要在后端用 Pydantic 校验，在前端对关键异常做保护。

### 3.3 泛型

泛型让函数或类型在不丢失具体类型的情况下复用。一个典型例子是通用请求函数：调用者指定或推断返回的数据类型。

```ts
async function requestJson<T>(url: string): Promise<T> {
  const response = await fetch(url);
  if (!response.ok) throw new Error("请求失败");
  return response.json() as Promise<T>;
}
```

例如 `requestJson<KnowledgeDocument[]>("/api/documents")` 表示结果是文档数组。注意 `as` 只是告诉编译器自己的判断，它不验证真实网络数据，因此不能拿它掩盖不确定性。

### 3.4 前后端类型边界

前端类型应围绕接口契约写，例如请求体、响应体、状态枚举。数据库的完整表结构不等于前端都该看到的数据。接口应该只返回页面需要的字段，敏感字段也不能被传到浏览器。

在 KnowTrace AI 中，文档接口可返回 `id`、文件名、处理状态、创建时间、失败原因；不需要把 Storage 的服务端密钥、用户密码或模型密钥给前端。类型清晰也让接口变更更容易发现影响范围。

## 4. Next.js：React 应用的工程框架

Next.js 是基于 React 的全栈框架。它提供路由、构建、服务端渲染、接口路由、静态资源优化等能力。KnowTrace AI 的页面用 Next.js 组织，浏览器端主要负责交互和展示，FastAPI 负责核心业务后端。

### 4.1 路由和页面

App Router 中，`app` 目录按文件夹映射 URL，`page.tsx` 是页面，`layout.tsx` 是共享布局。比如 `app/workspace/page.tsx` 可以对应工作区页面。这样前端页面无需自己手写一张路由表。

### 4.2 Server Component 与 Client Component

Next.js 默认组件可以在服务器渲染。需要使用 `useState`、`useEffect`、浏览器 API 或点击事件的组件，需要在文件顶部写 `"use client"`，成为 Client Component。

不是所有组件都要变成客户端组件。静态布局、初始数据展示可留在服务端；上传、输入、SSE 流式阅读等交互部分才需要在浏览器端运行。这样能减少发送给浏览器的 JavaScript，并避免把服务端密钥误带到客户端。

### 4.3 Next.js 后端能力和 FastAPI 的分工

Next.js 也能写 Route Handler，例如 `app/api/.../route.ts`，适合 BFF（面向前端的后端）、轻量接口、转发或隐藏第三方密钥。但本项目把 RAG、文档解析、任务调度、数据库业务放在 FastAPI：Python 生态更适合文本解析、向量化和异步 Worker。

可以这样表述：Next.js 在这里是前端应用框架，也可承担少量服务端边界；FastAPI 是主要业务 API 服务。两者通过 HTTP 接口通信，职责清楚，后端可以独立部署和测试。

## 5. HTTP 接口与前后端联调

接口是前端与后端的约定。一次 HTTP 请求通常包含方法、路径、请求头、查询参数、请求体；响应包含状态码、响应头和响应体。

常用方法：

- `GET`：读取资源，例如读取工作区文档列表。
- `POST`：创建资源或触发动作，例如创建工作区、上传文件、发起提问。
- `PATCH` 或 `PUT`：修改资源，例如修改工作区名称。
- `DELETE`：删除资源，例如删除文档或会话。

常见状态码：`200` 成功，`201` 创建成功，`204` 成功但无内容，`400` 请求参数不合法，`401` 未登录或 token 无效，`403` 已登录但没有权限，`404` 不存在，`409` 冲突，`422` 参数校验失败，`500` 服务端异常。

### 5.1 一个接口契约例子

```text
POST /api/workspaces/{workspaceId}/documents
Content-Type: multipart/form-data
Authorization: Bearer <access token>

文件字段：file

响应 201：
{
  "id": "doc_123",
  "filename": "产品手册.pdf",
  "taskStatus": "queued"
}
```

上传完成只表示文件和任务记录已创建，不代表文件已能被问答使用。前端需要根据任务状态显示“排队中、处理中、完成、失败”，必要时轮询状态或接收状态更新。这个业务含义是接口设计的一部分。

### 5.2 联调的正确顺序

1. 先对齐接口路径、方法、鉴权、请求参数、成功响应、失败响应和状态码。
2. 前端先用 mock 数据完成页面交互，后端用 Swagger/OpenAPI 或接口工具验证接口。
3. 接入真实接口后，按正常路径和异常路径逐项验证。
4. 出问题先看浏览器 Network：请求是否发出、URL 和方法是否正确、请求体是否正确、状态码和响应内容是什么；再查后端日志。

联调中最常见的问题包括字段名不一致、时间格式不一致、前端预期 JSON 但后端返回文本、跨域限制、token 缺失或过期、上传类型错误、空值没有约定。不要只说“接口不通”，应带着请求 ID、状态码、请求和响应摘要定位。

### 5.3 认证和授权

**认证（authentication）**回答“你是谁”，例如用户使用账号密码登录，Supabase Auth 签发 JWT。**授权（authorization）**回答“你能否操作这条数据”，例如用户只能读写属于自己的工作区。

前端在请求中携带 access token；后端校验 token，获取当前用户身份；随后按用户 ID 检查工作区和文档归属。不能因为前端隐藏了按钮就认为安全，后端每个受保护接口都必须验证权限。Supabase 的 RLS（行级安全策略）可以在数据库层再限制每位用户能读取或修改的行，形成额外保护。

### 5.4 Fetch 与异常处理

`fetch` 即使收到 404、500 也不一定自动抛异常，因此要检查 `response.ok`。网络超时、断网、JSON 解析失败也要处理。请求期间要禁用重复提交或区分处理中状态；失败后应告知用户下一步，例如重试上传或重新登录。

```ts
const response = await fetch(url, { method: "DELETE", headers });
if (!response.ok) {
  throw new Error(`删除失败：${response.status}`);
}
```

## 6. SSE：让答案逐字显示

SSE（Server-Sent Events）是一种服务器向浏览器持续推送事件的 HTTP 流。一次连接保持一段时间，服务器可以不断发送数据，浏览器收到一段就更新一次界面。

在本项目中，用户发出问题后，后端先检索资料，然后在大模型逐步生成答案时推送事件。前端把每个 token 文本片段追加到当前消息，因此用户不必等全部回答完成。还可以推送检索阶段、引用信息、完成和错误事件。

```text
event: token
data: {"text":"根据文档，"}

event: token
data: {"text":"该产品支持……"}

event: complete
data: {"citations":[...]}
```

原生 `EventSource` 主要使用 GET，且不方便在请求体里携带问题。KnowTrace AI 需要用 POST 提交问题和鉴权信息，所以前端使用 `fetch` 获取响应，再用 `response.body.getReader()` 逐块读取。读取到的字节先用 `TextDecoder` 解码，按 SSE 的事件边界解析，然后更新 React state。

流式接口还要处理用户取消、网络中断、服务端错误和组件卸载。取消可用 `AbortController`；最后要关闭 reader、停止 loading，并把未完成的消息标记为失败或可重试。

## 7. PostgreSQL：保存关系型业务数据

PostgreSQL 是关系型数据库。数据放在表中，表之间通过主键和外键建立关系。它适合保存有明确结构、需要查询、排序、关联、事务和权限控制的业务数据。

KnowTrace AI 中可能有用户、工作区、文档、文档分块、处理任务、会话、消息和引用等表。比如：一个用户有多个工作区；一个工作区有多个文档；一个文档有多个 chunk；一条回答可以引用多个 chunk。

### 7.1 表、主键、外键和索引

主键唯一标识一行，例如 `documents.id`。外键表示引用关系，例如 `documents.workspace_id` 指向 `workspaces.id`。删除工作区时，需要设计关联数据如何处理：拒绝删除、手动清理，或用级联删除。项目中删除文件不仅要删数据库记录，还要清理 Storage 原文件、解析产物、向量、引用和任务，避免残留数据。

索引用于加快查询，例如经常按 `workspace_id` 查文档，可以为该列建立索引。索引不是越多越好：它会占用空间，也会增加写入维护成本。

### 7.2 基础 SQL

```sql
-- 查询某工作区中处理成功的文档
SELECT id, filename, created_at
FROM documents
WHERE workspace_id = $1 AND task_status = 'succeeded'
ORDER BY created_at DESC;

-- 新建一条文档记录，参数化避免 SQL 注入
INSERT INTO documents (id, workspace_id, filename, task_status)
VALUES ($1, $2, $3, 'queued');

-- 更新任务状态
UPDATE documents
SET task_status = $2, error_message = $3
WHERE id = $1;
```

使用参数化查询，不要把用户输入通过字符串拼接到 SQL 中，否则可能造成 SQL 注入。查询只取需要的列，不随意使用 `SELECT *`。

### 7.3 事务

事务把多个数据库操作视为一个整体：要么都成功，要么失败后回滚。例如创建文档记录和创建处理任务记录应保持一致；如果中途写入失败，不应留下半套数据。事务具备原子性、一致性、隔离性和持久性，简称 ACID。

不过 Storage 文件上传和 Redis 投递是外部操作，不可能天然和 PostgreSQL 处于同一个数据库事务中。因此要有补偿思路：上传成功但数据库写入失败则删对象；数据库已创建但任务投递失败则标记任务失败或允许重试。面试中能说出“跨服务操作要考虑部分成功和补偿”就够了。

### 7.4 pgvector 和混合检索

pgvector 是 PostgreSQL 的向量扩展，可把 embedding（例如 1536 维浮点向量）存入数据库并计算相似度。相似向量通常代表语义接近，因此用户问“如何重试处理失败的文档”时，不必和原文用词完全相同，也能找到“任务失败后可重新提交”的文本块。

本项目还可以结合 PostgreSQL 的全文检索。全文检索擅长精确术语、产品名和数字；向量检索擅长语义相近表达。把两种召回结果融合，叫混合检索。检索出的 chunk 既是大模型回答上下文，也是引用来源。

## 8. Supabase：认证、数据库和文件存储

Supabase 是一套后端服务。在本项目里主要使用：

- Auth：账号密码登录和 JWT 会话。
- PostgreSQL：持久化业务数据，配合 pgvector。
- Storage：对象存储，用来放原始文件和解析后的派生产物。
- RLS：在数据库行级别限制用户只能访问自己的数据。

Storage 是云端对象存储，类似“按路径存取文件”的文件仓库，并不是浏览器的 `localStorage`。用户上传的 PDF、Word、Excel 原文件放在私有 bucket。数据库保存文件名、对象路径、所属工作区、状态等元数据；真正较大的二进制文件放在 Storage。浏览器 localStorage 只能放少量本机数据，容易被清理，也不能作为多人或跨设备的文件存储。

客户端只能使用 Supabase 的公开 anon key；Service Role 等高权限密钥只能在服务端环境变量中使用。私有文件不应直接公开 URL，而应由服务端校验权限后生成受控访问，或经受保护接口下载。

## 9. Redis 与 ARQ Worker：把慢任务移出请求

Redis 是独立于 PostgreSQL 的内存型键值服务。二者并非从属关系。PostgreSQL 负责长期业务数据；Redis 在 Docker 部署中主要承担临时任务队列。

ARQ 是 Python 的异步任务队列库，ARQ Worker 是一个单独运行的 Python 进程。后端 API 收到上传请求后，先把文件放进 Storage、在 PostgreSQL 写入文档和任务状态，再把“处理 document_id”投递到 Redis。Worker 监听 Redis，取到任务后执行下载、解析、清洗、分块、向量化、写入分块和向量、更新状态等工作。

```text
上传接口快速返回 queued
       ↓
Redis 中有任务
       ↓
ARQ Worker 消费任务
       ↓
running → succeeded / failed，结果写回 PostgreSQL
```

这么做的原因是 PDF、Office 文件解析和向量化可能耗时很长。若放在 HTTP 请求内，浏览器容易超时，API 进程会被占住，用户也不能方便地观察进度、取消或重试。异步任务让接口更快返回，也便于失败重试。

Redis 速度快，但默认不应承担核心永久数据。任务的最终状态、文档和检索数据仍应保存 PostgreSQL。Worker 应具备幂等性：同一个任务意外重试时，不应生成重复 chunk 或重复扣费。常见做法包括为任务设置唯一标识、写入前检查状态、对文档旧索引先清理或使用唯一约束。

在 Vercel Serverless 这种没有常驻 Worker 的环境中，项目会采用短任务的 inline 模式，避免把任务投到没有消费者的永久队列。这体现了部署环境会影响架构选择。

## 10. 数据结构：用合适方式组织数据

数据结构是组织数据以及在数据上执行操作的方法。面试通常考察你能否理解时间复杂度和适用场景，而不是手写很难的算法。

### 10.1 数组和链表

数组按连续索引访问，按下标读取通常是 O(1)，在中间插入或删除需要移动后续元素，通常是 O(n)。前端的消息列表、文档列表一般用数组表示，渲染和排序都方便。

链表每个节点指向下一个节点，已知节点位置时插入删除可以是 O(1)，但按下标寻找第 N 个元素要从头走，通常是 O(n)。JavaScript 日常业务中通常优先使用数组。

### 10.2 栈和队列

栈遵循后进先出（LIFO），像浏览器回退或函数调用栈。队列遵循先进先出（FIFO），像排队办事。Redis 任务队列的直觉就是：先投递的任务通常先被 Worker 消费，虽然真实系统还可能有优先级、重试和并发控制。

### 10.3 哈希表 / Map

哈希表按 key 快速找到 value，平均查找、插入、删除是 O(1)。JavaScript 的 `Map` 或对象可表示“文档 ID 到文档对象”的映射。比如频繁根据文档 ID 更新列表时，先构建 Map 比每次 `array.find` 更高效。

```ts
const documentById = new Map(documents.map((item) => [item.id, item]));
const document = documentById.get(documentId);
```

### 10.4 集合 Set

Set 保存不重复的值，常用于去重和成员判断。例如把混合检索的多个结果按 `chunkId` 去重，避免同一文本块重复作为上下文。成员判断平均 O(1)。

### 10.5 树、堆和图

树适合表达层级关系，如文件目录、页面组件层级。堆适合持续取出优先级最高或最低的数据，可用于优先级任务调度。图由节点和边组成，适合表达复杂关系，例如文档、chunk、回答和引用的关联。

本项目重点不在手写树或图算法，但理解关系很有用：工作区—文档—chunk 是层级关系；回答—引用 chunk 是多对多关系，需要中间表来表达。

### 10.6 时间复杂度

时间复杂度描述输入规模变大时，算法大致增长多快：

- O(1)：常数时间，如按数组下标或 Map key 读取。
- O(log n)：对数时间，如二分查找。
- O(n)：线性时间，如遍历文档列表。
- O(n log n)：常见排序复杂度。
- O(n²)：双层遍历比较，数据大时要警惕。

复杂度是估算，不替代实际测量。对于几条数据，简单清晰的 O(n) 代码往往足够；对于成千上万条数据、频繁渲染或高并发请求，才需要认真选择数据结构、数据库索引、分页和缓存。

## 11. RAG 流程与可追溯性

RAG 是 Retrieval-Augmented Generation，中文常叫检索增强生成。它不是让模型“记住”用户上传的文件，而是在每次提问时先从文件内容中找相关段落，再让模型参考这些段落回答。

典型流程：

1. 上传原始文件到 Storage，创建文档记录。
2. Worker 提取文本，清洗无意义内容。
3. 文本按长度和语义边界切成 chunk，并记录 chunk 属于哪个文档、位于何处。
4. 调用 embedding 模型把每个 chunk 转成向量，写入 PostgreSQL/pgvector。
5. 用户提问时，把问题也转为向量，结合向量检索和全文检索，召回当前工作区的相关 chunk。
6. 把问题和候选 chunk 作为上下文交给大模型，要求它基于资料作答。
7. 保存回答与引用 chunk 的关系，前端展示引用。

“只在当前工作区检索”既符合用户预期，也是权限边界。服务端必须在查询条件中带上 workspace ID 和当前用户权限；不能只依赖前端传来的隐藏状态。

可追溯性要求每个引用都能回到稳定来源。不能只在回答文本中硬编码一个文件名，而要保存结构化关系，例如 `answer_citations(answer_id, chunk_id)`。这样即使前端刷新，仍能重建引用；也便于删除文件时清理相关引用，或在文件变更后重新索引。

## 12. 质量、测试和端到端 Ownership

代码质量不只是“能运行”。前端要处理 loading、空状态、失败状态、重复点击、网络中断和权限失败；后端要校验参数、记录日志、返回清晰错误、保护数据边界；数据库要有合理约束和索引；上线前要验证用户完整路径。

KnowTrace AI 可以使用：前端 ESLint、后端 Ruff 和 Pytest；Playwright 端到端测试覆盖创建工作区、上传、等待处理、提问并查看引用、删除会话或文档等流程。RAG 还可以维护一组标注问题，检查检索召回率、引用准确率和答案覆盖率，而不是只凭主观感觉判断效果。

**端到端 Ownership** 是对用户最终结果负责，不是一个人包办所有工作。具体来说：需求开始时确认目标、用户场景、边界和验收标准；设计时考虑数据、接口、异常和权限；开发中推动接口对齐和联调；交付前验证正常与异常流程；上线后关注问题、定位并推动修复。

项目中的例子是：不是只完成一个“上传按钮”，而是确保用户上传后看得到状态，文件被正确解析与索引，失败时能重试，提问能得到当前工作区资料支撑的答案，引用能打开来源，删除后相关文件和数据被清理。这就是从需求到交付的责任范围。

## 13. 第一轮面试的表达方法

回答技术问题时，可以按三句组织：先说定义，再说项目里怎么做，最后说这样做解决了什么问题。例如：

> Redis 是独立于 PostgreSQL 的内存服务。我的项目里把它当成 ARQ 的异步任务队列，文件解析和向量化任务由 Worker 消费，最终结果写回 PostgreSQL。这样上传接口不需要一直等待耗时任务，用户能看到处理状态，也方便失败重试。

遇到暂时不了解的细节，不要编造。可以先说已知范围，再给出验证方法，例如：“这一部分我需要再确认当前实现的重试策略；我会先看任务状态表和 Worker 日志，确认是否存在幂等约束以及失败后的重投逻辑。”

面试官通常更看重你是否能说清边界、解释取舍、根据现象定位问题。基础概念只要讲正确、能联系实际，就比堆砌术语有效。
