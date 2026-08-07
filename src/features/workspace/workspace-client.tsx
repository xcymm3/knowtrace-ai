"use client";

import { FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  ApiError,
  knowTraceApi,
  type Conversation,
  type ConversationMessage,
  type KnowledgeDocument,
  type ProcessingTask,
  type RagSource,
  type WorkspaceProject,
} from "@/lib/knowtrace-api";

import styles from "@/app/page.module.css";

type WorkspaceData = { documents: KnowledgeDocument[]; tasks: ProcessingTask[] };

const emptyWorkspace: WorkspaceData = { documents: [], tasks: [] };

function readableError(error: unknown) {
  return error instanceof ApiError || error instanceof Error ? error.message : "操作失败，请稍后重试。";
}

function workspaceStatus(status: WorkspaceProject["status"]) {
  return { ACTIVE: "进行中", DRAFT: "草稿", ARCHIVED: "已归档" }[status];
}

function documentStatus(status: string) {
  return { READY: "已索引", PARSED: "已解析，等待索引", PROCESSING: "处理中", PENDING: "等待处理", FAILED: "处理失败" }[status] ?? status;
}

function taskDetail(task: ProcessingTask) {
  if (task.status === "FAILED") return task.error_message ?? "任务执行失败";
  if (task.status === "SUCCEEDED") return task.task_type === "GENERATE_EMBEDDINGS" ? "向量索引已完成" : "文本解析已完成";
  return `${task.progress}% · ${task.task_type === "GENERATE_EMBEDDINGS" ? "正在建立向量索引" : "正在解析文件"}`;
}

function formatBytes(size: number) {
  return size < 1024 * 1024 ? `${Math.max(1, Math.ceil(size / 1024))} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function titleFromQuestion(question: string) {
  return question.length > 22 ? `${question.slice(0, 22)}…` : question;
}

function Sources({ sources }: { sources: RagSource[] }) {
  if (!sources.length) return null;
  return (
    <details className={styles.sourceDetails}>
      <summary>本次引用 {sources.length} 个资料片段</summary>
      <ol>
        {sources.map((source) => (
          <li key={source.chunk_id}>
            <strong>{source.citation.file_name}</strong>
            <span>片段 {source.citation.chunk_index + 1}{source.score === null ? "" : ` · 相关度 ${Math.round(source.score * 100)}%`}</span>
            <p>{source.excerpt}</p>
          </li>
        ))}
      </ol>
    </details>
  );
}

export function WorkspaceClient() {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceData>(emptyWorkspace);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);

  const activeProject = projects.find((project) => project.id === projectId) ?? null;
  const activeConversation = conversations.find((conversation) => conversation.id === conversationId) ?? null;
  const activeTasks = useMemo(() => workspace.tasks.filter((task) => ["QUEUED", "RUNNING"].includes(task.status)), [workspace.tasks]);
  const indexedDocuments = useMemo(() => workspace.documents.filter((document) => document.status === "READY"), [workspace.documents]);

  const loadWorkspace = useCallback(async (workspaceId: string) => {
    const [documents, tasks, nextConversations] = await Promise.all([
      knowTraceApi.listDocuments(workspaceId),
      knowTraceApi.listTasks(workspaceId),
      knowTraceApi.listConversations(workspaceId),
    ]);
    setWorkspace({ documents, tasks });
    setConversations(nextConversations);
    setConversationId((current) => nextConversations.some((conversation) => conversation.id === current) ? current : (nextConversations[0]?.id ?? null));
  }, []);

  const refreshProjects = useCallback(async () => {
    const nextProjects = await knowTraceApi.listWorkspaces();
    setProjects(nextProjects);
    return nextProjects;
  }, []);

  const loadMessages = useCallback(async (workspaceId: string, nextConversationId: string) => {
    const nextMessages = await knowTraceApi.listMessages(workspaceId, nextConversationId);
    setMessages(nextMessages);
  }, []);

  useEffect(() => {
    void (async () => {
      try {
        const nextProjects = await refreshProjects();
        if (nextProjects[0]) setProjectId(nextProjects[0].id);
      } catch (caughtError) {
        setError(readableError(caughtError));
      } finally {
        setIsLoading(false);
      }
    })();
  }, [refreshProjects]);

  useEffect(() => {
    if (!projectId) return;
    void (async () => {
      streamAbortRef.current?.abort();
      setIsLoading(true);
      setError(null);
      setMessages([]);
      setConversationId(null);
      try {
        await loadWorkspace(projectId);
      } catch (caughtError) {
        setError(readableError(caughtError));
      } finally {
        setIsLoading(false);
      }
    })();
  }, [loadWorkspace, projectId]);

  useEffect(() => {
    if (!projectId || !conversationId) return;
    void (async () => {
      try {
        await loadMessages(projectId, conversationId);
      } catch (caughtError) {
        setError(readableError(caughtError));
      }
    })();
  }, [conversationId, loadMessages, projectId]);

  useEffect(() => () => streamAbortRef.current?.abort(), []);

  const watchTask = useCallback((taskId: string) => {
    const source = knowTraceApi.taskEvents(taskId);
    const updateTask = (event: Event) => {
      const payload = JSON.parse((event as MessageEvent<string>).data) as ProcessingTask;
      setWorkspace((current) => ({ ...current, tasks: [payload, ...current.tasks.filter((task) => task.id !== payload.id)] }));
    };
    const complete = () => {
      source.close();
      if (projectId) void loadWorkspace(projectId);
    };
    source.addEventListener("progress", updateTask);
    source.addEventListener("complete", (event) => { updateTask(event); complete(); });
    source.addEventListener("timeout", complete);
    source.onerror = complete;
  }, [loadWorkspace, projectId]);

  async function handleCreateWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    const name = String(form.get("name") ?? "").trim();
    if (!name) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const project = await knowTraceApi.createWorkspace(name);
      setProjects((current) => [project, ...current]);
      setProjectId(project.id);
      event.currentTarget.reset();
      setNotice("项目已创建。上传资料后即可开始建立索引。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId) return;
    const form = new FormData(event.currentTarget);
    const file = form.get("file");
    if (!(file instanceof File) || file.size === 0) {
      setError("请选择需要入库的资料文件。");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    try {
      form.set("kind", "GENERAL");
      const response = await knowTraceApi.uploadDocument(projectId, form);
      event.currentTarget.reset();
      await loadWorkspace(projectId);
      watchTask(response.task_id);
      setNotice("文件已上传，正在解析并建立向量索引。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleCreateConversation() {
    if (!projectId || isStreaming) return;
    setError(null);
    try {
      const conversation = await knowTraceApi.createConversation(projectId, "新对话");
      setConversations((current) => [conversation, ...current]);
      setConversationId(conversation.id);
      setMessages([]);
    } catch (caughtError) {
      setError(readableError(caughtError));
    }
  }

  async function ensureConversation(cleanQuestion: string) {
    if (!projectId) throw new ApiError("请先选择一个项目。");
    if (conversationId) return conversationId;
    const conversation = await knowTraceApi.createConversation(projectId, titleFromQuestion(cleanQuestion));
    setConversations((current) => [conversation, ...current]);
    setConversationId(conversation.id);
    return conversation.id;
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isStreaming) {
      streamAbortRef.current?.abort();
      return;
    }
    const cleanQuestion = question.trim();
    if (!cleanQuestion || !projectId) return;
    if (!indexedDocuments.length) {
      setError("请先上传并等待至少一份资料完成索引，再开始提问。");
      return;
    }

    setQuestion("");
    setError(null);
    setNotice(null);
    setIsStreaming(true);
    const controller = new AbortController();
    streamAbortRef.current = controller;
    const localUserId = `local-user-${Date.now()}`;
    const localAssistantId = `local-assistant-${Date.now()}`;

    try {
      const nextConversationId = await ensureConversation(cleanQuestion);
      const now = new Date().toISOString();
      setMessages((current) => [
        ...current,
        { id: localUserId, conversation_id: nextConversationId, role: "USER", content: cleanQuestion, sequence: current.length, created_at: now, sources: [] },
        { id: localAssistantId, conversation_id: nextConversationId, role: "ASSISTANT", content: "", sequence: current.length + 1, created_at: now, sources: [] },
      ]);

      await knowTraceApi.streamRagAnswer(projectId, nextConversationId, cleanQuestion, (streamEvent) => {
        if (streamEvent.event === "retrieval") {
          setMessages((current) => current.map((message) => message.id === localAssistantId ? { ...message, sources: streamEvent.data.sources } : message));
        }
        if (streamEvent.event === "token") {
          setMessages((current) => current.map((message) => message.id === localAssistantId ? { ...message, content: `${message.content}${streamEvent.data.delta}` } : message));
        }
        if (streamEvent.event === "complete") {
          setMessages((current) => current.map((message) => message.id === localAssistantId ? { ...streamEvent.data.message, sources: streamEvent.data.sources } : message));
          setConversations((current) => current.map((conversation) => conversation.id === nextConversationId ? { ...conversation, updated_at: new Date().toISOString() } : conversation));
        }
      }, controller.signal);
    } catch (caughtError) {
      setMessages((current) => current.filter((message) => message.id !== localAssistantId));
      if (controller.signal.aborted) setNotice("已停止生成。已保存的问题仍可在此对话中继续追问。");
      else setError(readableError(caughtError));
    } finally {
      if (streamAbortRef.current === controller) streamAbortRef.current = null;
      setIsStreaming(false);
    }
  }

  function handleComposerKeyDown(event: KeyboardEvent<HTMLTextAreaElement>) {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      event.currentTarget.form?.requestSubmit();
    }
  }

  return (
    <div className={styles.page}>
      <a className={styles.skipLink} href="#workspace-main">跳至主内容</a>
      <aside className={styles.sidebar} aria-label="KnowTrace 项目导航">
        <a className={styles.brand} href="#workspace-main"><span className={styles.brandMark} aria-hidden="true">◫</span>KnowTrace</a>
        <p className={styles.brandSubline}>可追溯知识工作台</p>

        <section className={styles.projectNavigation} aria-labelledby="projects-title">
          <div className={styles.railHeading}><h2 id="projects-title">项目</h2><span>{projects.length}</span></div>
          <form className={styles.createForm} onSubmit={handleCreateWorkspace}>
            <label className={styles.srOnly} htmlFor="workspace-name">项目名称</label>
            <input id="workspace-name" name="name" required placeholder="新建项目" />
            <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>新建</button>
          </form>
          <div className={styles.projectList} role="list">
            {projects.map((project) => (
              <button className={`${styles.projectItem} ${project.id === projectId ? styles.projectItemActive : ""}`} key={project.id} type="button" onClick={() => setProjectId(project.id)} aria-pressed={project.id === projectId} disabled={isStreaming}>
                <span className={styles.projectItemName}>{project.name}</span><span>{workspaceStatus(project.status)}</span>
              </button>
            ))}
            {!projects.length && !isLoading ? <p className={styles.railEmpty}>建立一个项目，将资料和后续对话放在同一范围内。</p> : null}
          </div>
        </section>

        {activeProject ? <section className={styles.conversationNavigation} aria-labelledby="conversations-title">
          <div className={styles.railHeading}><h2 id="conversations-title">对话</h2><button className={styles.railAction} type="button" onClick={handleCreateConversation} disabled={isStreaming}>新建</button></div>
          <div className={styles.conversationList} role="list">
            {conversations.map((conversation) => <button className={`${styles.conversationItem} ${conversation.id === conversationId ? styles.conversationItemActive : ""}`} key={conversation.id} type="button" onClick={() => setConversationId(conversation.id)} aria-pressed={conversation.id === conversationId} disabled={isStreaming}>{conversation.title}</button>)}
            {!conversations.length ? <p className={styles.railEmpty}>第一次提问时会自动建立一段对话。</p> : null}
          </div>
        </section> : null}

        <div className={styles.sidebarFoot}><span className={styles.statusDot} aria-hidden="true" />RAG MVP · Step 9</div>
      </aside>

      <main className={styles.main} id="workspace-main">
        {error ? <p className={styles.feedbackError} role="alert">{error}</p> : null}
        {notice ? <p className={styles.feedbackNotice} role="status">{notice}</p> : null}

        {!activeProject && !isLoading ? <section className={styles.welcome} aria-labelledby="welcome-title"><p className={styles.eyebrow}>KNOWTRACE AI</p><h1 id="welcome-title">从一个项目开始整理资料。</h1><p>每个项目拥有独立的文件与后续对话范围。先在左侧命名项目，再上传第一份资料。</p></section> : null}

        {activeProject ? <div className={styles.workspaceGrid}>
          <section className={styles.chatPane} aria-labelledby="project-title">
            <header className={styles.workspaceHeader}><div><p className={styles.eyebrow}>当前项目 {activeConversation ? `· ${activeConversation.title}` : ""}</p><h1 id="project-title">{activeProject.name}</h1></div><span className={styles.workspaceState}>{workspaceStatus(activeProject.status)}</span></header>

            {messages.length ? <div className={styles.messageTimeline} aria-live="polite">
              {messages.map((message) => <article className={`${styles.message} ${message.role === "USER" ? styles.userMessage : styles.assistantMessage}`} key={message.id}>
                <p className={styles.messageRole}>{message.role === "USER" ? "你的问题" : "KnowTrace"}</p>
                <div className={styles.messageContent}>{message.content || "正在基于已检索资料生成回答…"}</div>
                {message.role === "ASSISTANT" ? <Sources sources={message.sources} /> : null}
              </article>)}
            </div> : <div className={styles.conversationPlaceholder}>
              <div className={styles.placeholderGlyph} aria-hidden="true" />
              <h2>{indexedDocuments.length ? "可以开始提问了。" : "资料准备就绪后，在这里开始对话。"}</h2>
              <p>KnowTrace 只检索当前项目中的已索引资料，并在回答中附上可回看的原文来源。</p>
              <dl className={styles.workspaceMetrics}><div><dt>已索引文件</dt><dd>{indexedDocuments.length}</dd></div><div><dt>等待处理</dt><dd>{workspace.documents.length - indexedDocuments.length}</dd></div><div><dt>运行任务</dt><dd>{activeTasks.length}</dd></div></dl>
            </div>}

            <form className={styles.composer} onSubmit={handleSend}>
              <label className={styles.srOnly} htmlFor="message">向项目资料提问</label>
              <textarea id="message" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={handleComposerKeyDown} disabled={!indexedDocuments.length || isStreaming} placeholder={indexedDocuments.length ? "向当前项目的资料提问，Enter 发送，Shift+Enter 换行" : "等待至少一份资料完成索引后即可提问"} rows={1} />
              <button className={styles.iconButton} type="submit" disabled={!isStreaming && (!question.trim() || !indexedDocuments.length)} aria-label={isStreaming ? "停止生成" : "发送问题"}>{isStreaming ? "■" : "↑"}</button>
            </form>
          </section>

          <aside className={styles.filesPane} aria-labelledby="files-title">
            <header className={styles.filesHeader}><div><p className={styles.eyebrow}>项目资料</p><h2 id="files-title">文件</h2></div><span>{workspace.documents.length}</span></header>
            <form className={styles.uploadForm} onSubmit={handleUpload}>
              <label className={styles.uploadLabel}>选择文件<input name="file" type="file" required accept=".txt,.md,.markdown,.csv,.xlsx,.docx,.pdf,.jpg,.jpeg,.png,.webp" /></label>
              <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>上传并解析</button>
            </form>
            <ul className={styles.documentList}>{workspace.documents.map((document) => <li key={document.id}><span className={styles.fileType}>{document.file_name.split(".").pop()?.toUpperCase() ?? "FILE"}</span><div><strong>{document.file_name}</strong><span>{formatBytes(document.size_bytes)} · {documentStatus(document.status)}</span></div></li>)}{!workspace.documents.length ? <li className={styles.documentEmpty}>尚未上传文件。当前版本支持文本、Markdown、表格、DOCX、PDF 和常见图片资料。</li> : null}</ul>
            <section className={styles.taskPanel} aria-labelledby="task-title"><div className={styles.taskHeading}><h3 id="task-title">处理状态</h3><span>{activeTasks.length ? "运行中" : "空闲"}</span></div><ul>{workspace.tasks.slice(0, 3).map((task) => <li key={task.id}><span className={`${styles.taskMarker} ${task.status === "SUCCEEDED" ? styles.taskDone : ""}`} /><div><strong>{task.task_type === "GENERATE_EMBEDDINGS" ? "向量索引" : "文件解析"}</strong><span>{taskDetail(task)}</span></div></li>)}{!workspace.tasks.length ? <li className={styles.taskEmpty}>上传文件后，解析和索引任务会显示在这里。</li> : null}</ul></section>
          </aside>
        </div> : null}
      </main>
    </div>
  );
}
