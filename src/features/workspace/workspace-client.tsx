"use client";

import Image from "next/image";
import { DragEvent, FormEvent, KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";

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
type DeletionTarget =
  | { kind: "workspace"; workspace: WorkspaceProject }
  | { kind: "conversation"; conversation: Conversation };
type UploadActivity = {
  documentId?: string;
  fileName: string;
  stage: "UPLOADING" | "PROCESSING";
};

const emptyWorkspace: WorkspaceData = { documents: [], tasks: [] };

function readableError(error: unknown) {
  return error instanceof ApiError || error instanceof Error ? error.message : "操作失败，请稍后重试。";
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

type WorkspaceClientProps = {
  userName: string;
  onSignOut: () => Promise<{ error: Error | null }>;
};

export function WorkspaceClient({ userName, onSignOut }: WorkspaceClientProps) {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceData>(emptyWorkspace);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [isConversationCreatorOpen, setIsConversationCreatorOpen] = useState(false);
  const [newConversationTitle, setNewConversationTitle] = useState("");
  const [isCreatingConversation, setIsCreatingConversation] = useState(false);
  const [messages, setMessages] = useState<ConversationMessage[]>([]);
  const [question, setQuestion] = useState("");
  const [retrievalLimit, setRetrievalLimit] = useState(6);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isDeleting, setIsDeleting] = useState(false);
  const [isStreaming, setIsStreaming] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isDraggingFile, setIsDraggingFile] = useState(false);
  const [selectedUploadFileName, setSelectedUploadFileName] = useState<string | null>(null);
  const [uploadActivity, setUploadActivity] = useState<UploadActivity | null>(null);
  const [deletionTarget, setDeletionTarget] = useState<DeletionTarget | null>(null);
  const streamAbortRef = useRef<AbortController | null>(null);
  const uploadInputRef = useRef<HTMLInputElement | null>(null);
  const conversationTitleInputRef = useRef<HTMLInputElement | null>(null);

  const activeProject = projects.find((project) => project.id === projectId) ?? null;
  const activeConversation = conversations.find((conversation) => conversation.id === conversationId) ?? null;
  const activeTasks = useMemo(() => workspace.tasks.filter((task) => ["QUEUED", "RUNNING"].includes(task.status)), [workspace.tasks]);
  const indexedDocuments = useMemo(() => workspace.documents.filter((document) => document.status === "READY"), [workspace.documents]);
  const visibleUploadActivity = useMemo(() => {
    if (!uploadActivity?.documentId) return uploadActivity;
    const document = workspace.documents.find((item) => item.id === uploadActivity.documentId);
    return document?.status === "READY" || document?.status === "FAILED" ? null : uploadActivity;
  }, [uploadActivity, workspace.documents]);

  const loadWorkspace = useCallback(async (workspaceId: string) => {
    const [documentsResult, tasksResult, conversationsResult] = await Promise.allSettled([
      knowTraceApi.listDocuments(workspaceId),
      knowTraceApi.listTasks(workspaceId),
      knowTraceApi.listConversations(workspaceId),
    ]);
    setWorkspace({
      documents: documentsResult.status === "fulfilled" ? documentsResult.value : [],
      tasks: tasksResult.status === "fulfilled" ? tasksResult.value : [],
    });
    if (conversationsResult.status === "fulfilled") {
      const nextConversations = conversationsResult.value;
      setConversations(nextConversations);
      setConversationId((current) => nextConversations.some((conversation) => conversation.id === current) ? current : (nextConversations[0]?.id ?? null));
    }

    const failedResult = [documentsResult, tasksResult, conversationsResult].find(
      (result) => result.status === "rejected",
    );
    if (failedResult?.status === "rejected") throw failedResult.reason;
  }, []);

  const refreshProjects = useCallback(async () => {
    const nextProjects = await knowTraceApi.listWorkspaces();
    setProjects(nextProjects);
    return nextProjects;
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
      setIsConversationCreatorOpen(false);
      setNewConversationTitle("");
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
    if (!projectId || !conversationId || isStreaming) return;
    let isCurrent = true;
    void (async () => {
      try {
        const nextMessages = await knowTraceApi.listMessages(projectId, conversationId);
        if (isCurrent) setMessages(nextMessages);
      } catch (caughtError) {
        if (isCurrent) setError(readableError(caughtError));
      }
    })();
    return () => {
      isCurrent = false;
    };
  }, [conversationId, isStreaming, projectId]);

  useEffect(() => () => streamAbortRef.current?.abort(), []);

  useEffect(() => {
    if (isConversationCreatorOpen) conversationTitleInputRef.current?.focus();
  }, [isConversationCreatorOpen]);

  useEffect(() => {
    if (!projectId || activeTasks.length === 0) return;
    const intervalId = window.setInterval(() => {
      void loadWorkspace(projectId).catch(() => undefined);
    }, 1500);
    return () => window.clearInterval(intervalId);
  }, [activeTasks.length, loadWorkspace, projectId]);

  async function handleCreateWorkspace(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const form = new FormData(formElement);
    const name = String(form.get("name") ?? "").trim();
    if (!name) return;
    setIsSubmitting(true);
    setError(null);
    try {
      const project = await knowTraceApi.createWorkspace(name);
      setProjects((current) => [project, ...current]);
      setProjectId(project.id);
      formElement.reset();
      setNotice("知识库已创建。上传资料后即可开始建立索引。");
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function uploadFile(file: File, formElement?: HTMLFormElement) {
    if (!projectId || isSubmitting) return;
    if (file.size === 0) {
      setError("请选择需要入库的资料文件。");
      return;
    }
    setIsSubmitting(true);
    setError(null);
    setUploadActivity({ fileName: file.name, stage: "UPLOADING" });
    setNotice(`正在上传“${file.name}”，请勿关闭页面。`);
    try {
      const form = new FormData();
      form.set("file", file, file.name);
      form.set("kind", "GENERAL");
      const response = await knowTraceApi.uploadDocument(projectId, form);
      setUploadActivity({ documentId: response.id, fileName: file.name, stage: "PROCESSING" });
      formElement?.reset();
      if (!formElement && uploadInputRef.current) uploadInputRef.current.value = "";
      setSelectedUploadFileName(null);
      await loadWorkspace(projectId);
      setNotice(`“${file.name}”已上传，正在解析并建立向量索引。`);
    } catch (caughtError) {
      setUploadActivity(null);
      setError(readableError(caughtError));
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleUpload(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const formElement = event.currentTarget;
    const file = new FormData(formElement).get("file");
    if (!(file instanceof File)) {
      setError("请选择需要入库的资料文件。");
      return;
    }
    await uploadFile(file, formElement);
  }

  function handleFileDrop(event: DragEvent<HTMLFormElement>) {
    event.preventDefault();
    setIsDraggingFile(false);
    const file = event.dataTransfer.files.item(0);
    if (!file) return;
    setSelectedUploadFileName(file.name);
    void uploadFile(file);
  }

  async function confirmDeletion() {
    if (!deletionTarget || isDeleting) return;
    setIsDeleting(true);
    setError(null);
    try {
      if (deletionTarget.kind === "workspace") {
        const { workspace: workspaceProject } = deletionTarget;
        await knowTraceApi.deleteWorkspace(workspaceProject.id);
        const remaining = projects.filter((project) => project.id !== workspaceProject.id);
        setProjects(remaining);
        if (projectId === workspaceProject.id) {
          streamAbortRef.current?.abort();
          setProjectId(remaining[0]?.id ?? null);
          setWorkspace(emptyWorkspace);
          setConversations([]);
          setConversationId(null);
          setMessages([]);
        }
        setNotice(`知识库“${workspaceProject.name}”已删除。`);
      } else if (projectId) {
        const { conversation } = deletionTarget;
        await knowTraceApi.deleteConversation(projectId, conversation.id);
        const remaining = conversations.filter((item) => item.id !== conversation.id);
        setConversations(remaining);
        if (conversationId === conversation.id) {
          setConversationId(remaining[0]?.id ?? null);
          setMessages([]);
        }
        setNotice(`对话“${conversation.title}”已删除。`);
      }
      setDeletionTarget(null);
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsDeleting(false);
    }
  }

  async function handleCreateConversation(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!projectId || isStreaming || isCreatingConversation) return;
    const title = newConversationTitle.trim();
    if (!title) {
      setError("请输入对话名称。");
      return;
    }
    setIsCreatingConversation(true);
    setError(null);
    try {
      const conversation = await knowTraceApi.createConversation(projectId, title);
      setConversations((current) => [conversation, ...current]);
      setConversationId(conversation.id);
      setMessages([]);
      setNewConversationTitle("");
      setIsConversationCreatorOpen(false);
    } catch (caughtError) {
      setError(readableError(caughtError));
    } finally {
      setIsCreatingConversation(false);
    }
  }

  async function handleSend(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isStreaming) {
      streamAbortRef.current?.abort();
      return;
    }
    const cleanQuestion = question.trim();
    if (!cleanQuestion || !projectId) return;
    if (!conversationId) {
      setError("请先在左侧新建一段对话，再开始提问。");
      return;
    }
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
      const nextConversationId = conversationId;
      const now = new Date().toISOString();
      setMessages((current) => [
        ...current,
        { id: localUserId, conversation_id: nextConversationId, role: "USER", content: cleanQuestion, sequence: current.length, created_at: now, sources: [] },
        { id: localAssistantId, conversation_id: nextConversationId, role: "ASSISTANT", content: "", sequence: current.length + 1, created_at: now, sources: [] },
      ]);

      await knowTraceApi.streamRagAnswer(projectId, nextConversationId, cleanQuestion, retrievalLimit, (streamEvent) => {
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
      <aside className={styles.sidebar} aria-label="KnowTrace 知识库导航">
        <a className={styles.brand} href="#workspace-main"><Image className={styles.brandMark} src="/knowtrace-mark.svg" width={48} height={48} alt="" priority />KnowTrace</a>

        <section className={styles.projectNavigation} aria-labelledby="projects-title">
          <div className={styles.railHeading}><h2 id="projects-title">知识库</h2><span>{projects.length}</span></div>
          <form className={styles.createForm} onSubmit={handleCreateWorkspace}>
            <label className={styles.srOnly} htmlFor="workspace-name">知识库名称</label>
            <input id="workspace-name" name="name" required placeholder="新建知识库" />
            <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>新建</button>
          </form>
          <div className={styles.projectList} role="list">
            {projects.map((project) => (
              <div className={styles.railItem} key={project.id} role="listitem">
                <button className={`${styles.projectItem} ${project.id === projectId ? styles.projectItemActive : ""}`} type="button" onClick={() => setProjectId(project.id)} aria-pressed={project.id === projectId} disabled={isStreaming}>
                  <span className={styles.projectItemName}>{project.name}</span>
                </button>
                <button className={styles.deleteRailItem} type="button" onClick={() => setDeletionTarget({ kind: "workspace", workspace: project })} aria-label={`删除知识库 ${project.name}`} title="删除知识库" disabled={isStreaming || isDeleting}>×</button>
              </div>
            ))}
            {!projects.length && !isLoading ? <p className={styles.railEmpty}>建立一个知识库，将资料和后续对话放在同一范围内。</p> : null}
          </div>
        </section>

        {activeProject ? <section className={styles.conversationNavigation} aria-labelledby="conversations-title">
          <div className={styles.railHeading}><h2 id="conversations-title">对话</h2><button className={styles.railAction} type="button" onClick={() => setIsConversationCreatorOpen(true)} aria-label="新建对话" title="新建对话" disabled={isStreaming || isCreatingConversation}>＋</button></div>
          {isConversationCreatorOpen ? <form className={styles.conversationCreateForm} onSubmit={handleCreateConversation}>
            <label className={styles.srOnly} htmlFor="conversation-title">对话名称</label>
            <input ref={conversationTitleInputRef} id="conversation-title" value={newConversationTitle} onChange={(event) => setNewConversationTitle(event.target.value)} placeholder="输入对话名称" maxLength={160} required disabled={isCreatingConversation} />
            <button className={styles.primaryButton} type="submit" disabled={isCreatingConversation}>{isCreatingConversation ? "创建中…" : "创建"}</button>
            <button className={styles.railAction} type="button" onClick={() => { setIsConversationCreatorOpen(false); setNewConversationTitle(""); }} aria-label="取消新建对话" disabled={isCreatingConversation}>×</button>
          </form> : null}
          <div className={styles.conversationList} role="list">
            {conversations.map((conversation) => <div className={styles.railItem} key={conversation.id} role="listitem"><button className={`${styles.conversationItem} ${conversation.id === conversationId ? styles.conversationItemActive : ""}`} type="button" onClick={() => setConversationId(conversation.id)} aria-pressed={conversation.id === conversationId} disabled={isStreaming}>{conversation.title}</button><button className={styles.deleteRailItem} type="button" onClick={() => setDeletionTarget({ kind: "conversation", conversation })} aria-label={`删除对话 ${conversation.title}`} title="删除对话" disabled={isStreaming || isDeleting}>×</button></div>)}
            {!conversations.length ? <p className={styles.railEmpty}>点击“＋”输入名称，创建一段对话后即可开始提问。</p> : null}
          </div>
        </section> : null}

        {activeProject ? <section className={styles.ragSettings} aria-labelledby="rag-settings-title">
          <div className={styles.railHeading}><h2 id="rag-settings-title">RAG 设置</h2><span>当前</span></div>
          <label className={styles.retrievalLabel} htmlFor="retrieval-limit"><span>引用片段数</span><output>{retrievalLimit}</output></label>
          <input className={styles.retrievalRange} id="retrieval-limit" type="range" min="1" max="12" value={retrievalLimit} onChange={(event) => setRetrievalLimit(Number(event.target.value))} aria-describedby="retrieval-limit-help" />
          <p className={styles.settingHelp} id="retrieval-limit-help">每次回答最多检索 {retrievalLimit} 个相关资料片段。</p>
          <dl className={styles.settingSummary}>
            <div><dt>检索范围</dt><dd>当前知识库</dd></div>
            <div><dt>回答依据</dt><dd>仅限已索引资料</dd></div>
          </dl>
        </section> : null}

        <div className={styles.accountPanel}>
          <div className={styles.accountIdentity}>
            <span className={styles.accountLabel}>当前用户：</span>
            <strong className={styles.accountName}>{userName}</strong>
          </div>
          <button className={styles.signOutButton} type="button" onClick={() => void onSignOut()} disabled={isStreaming}>退出登录</button>
        </div>
      </aside>

      <main className={styles.main} id="workspace-main">
        {!activeProject && error ? <p className={styles.feedbackError} role="alert">{error}</p> : null}
        {!activeProject && notice ? <p className={styles.feedbackNotice} role="status">{notice}</p> : null}

        {!activeProject && !isLoading ? <section className={styles.welcome} aria-labelledby="welcome-title"><p className={styles.eyebrow}>KNOWTRACE AI</p><h1 id="welcome-title">从一个知识库开始整理资料。</h1><p>每个知识库拥有独立的文件与后续对话范围。先在左侧命名知识库，再上传第一份资料。</p></section> : null}

        {activeProject ? <div className={styles.workspaceGrid}>
          <section className={styles.chatPane} aria-labelledby="project-title">
            <header className={styles.workspaceHeader}>
              <div className={styles.workspaceTitle}>
                <Image className={styles.workspaceMark} src="/knowtrace-mark.svg" width={48} height={48} alt="" priority />
                <div><p className={styles.eyebrow}>当前知识库 {activeConversation ? `· ${activeConversation.title}` : ""}</p><h1 id="project-title">{activeProject.name}</h1></div>
              </div>
              <div className={styles.workspaceFeedback} aria-live="polite">
                {error ? <p className={styles.feedbackError} role="alert">{error}</p> : null}
                {notice ? <p className={styles.feedbackNotice} role="status">{notice}</p> : null}
              </div>
            </header>

            {messages.length ? <div className={styles.messageTimeline} aria-live="polite">
              {messages.map((message) => <article className={`${styles.message} ${message.role === "USER" ? styles.userMessage : styles.assistantMessage}`} key={message.id}>
                <p className={styles.messageRole}>{message.role === "USER" ? "你的问题" : "KnowTrace"}</p>
                <div className={styles.messageContent}>{message.content || "正在基于已检索资料生成回答…"}</div>
                {message.role === "ASSISTANT" ? <Sources sources={message.sources} /> : null}
              </article>)}
            </div> : <div className={styles.conversationPlaceholder}>
              <div className={styles.placeholderGlyph} aria-hidden="true" />
              <h2>{indexedDocuments.length ? activeConversation ? "可以开始提问了。" : "新建一段对话后开始提问。" : "资料准备就绪后，在这里开始对话。"}</h2>
              <p>KnowTrace 只检索当前知识库中的已索引资料，并在回答中附上可回看的原文来源。</p>
              <dl className={styles.workspaceMetrics}><div><dt>已索引文件</dt><dd>{indexedDocuments.length}</dd></div><div><dt>等待处理</dt><dd>{workspace.documents.length - indexedDocuments.length}</dd></div><div><dt>运行任务</dt><dd>{activeTasks.length}</dd></div></dl>
            </div>}

            <form className={styles.composer} onSubmit={handleSend}>
              <label className={styles.srOnly} htmlFor="message">向知识库资料提问</label>
              <textarea id="message" value={question} onChange={(event) => setQuestion(event.target.value)} onKeyDown={handleComposerKeyDown} disabled={!indexedDocuments.length || !conversationId || isStreaming} placeholder={!indexedDocuments.length ? "等待至少一份资料完成索引后即可提问" : !conversationId ? "请先在左侧新建一段对话" : "向当前知识库的资料提问，Enter 发送，Shift+Enter 换行"} rows={1} />
              <button className={styles.iconButton} type="submit" disabled={!isStreaming && (!question.trim() || !indexedDocuments.length || !conversationId)} aria-label={isStreaming ? "停止生成" : "发送问题"}>{isStreaming ? "■" : "↑"}</button>
            </form>
          </section>

          <aside className={styles.filesPane} aria-labelledby="files-title">
            <header className={styles.filesHeader}><div><p className={styles.eyebrow}>知识库资料</p><h2 id="files-title">文件</h2></div><span>{workspace.documents.length}</span></header>
            <form className={`${styles.uploadForm} ${isDraggingFile ? styles.uploadFormDragging : ""}`} onSubmit={handleUpload} onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = "copy"; setIsDraggingFile(true); }} onDragLeave={() => setIsDraggingFile(false)} onDrop={handleFileDrop}>
              <label className={styles.uploadLabel}><span>拖拽文件到这里</span><span>或点击选择文件</span><input ref={uploadInputRef} name="file" type="file" required accept=".txt,.md,.markdown,.csv,.xls,.xlsx,.doc,.docx,.pdf" onChange={(event) => setSelectedUploadFileName(event.target.files?.[0]?.name ?? null)} disabled={isSubmitting} /></label>
              <p className={styles.uploadHint} role={visibleUploadActivity ? "status" : undefined}>{visibleUploadActivity ? <><span className={styles.uploadSpinner} aria-hidden="true" />{visibleUploadActivity.fileName} · {visibleUploadActivity.stage === "UPLOADING" ? "正在上传，请勿关闭页面" : "已上传，正在解析与建立索引"}</> : selectedUploadFileName ?? "支持 TXT、Markdown、CSV、XLS、XLSX、DOC、DOCX、PDF"}</p>
              <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>{isSubmitting ? "正在上传…" : "上传并解析"}</button>
            </form>
            <ul className={styles.documentList}>{workspace.documents.map((document) => <li key={document.id}><span className={styles.fileType}>{document.file_name.split(".").pop()?.toUpperCase() ?? "FILE"}</span><div><strong>{document.file_name}</strong><span>{formatBytes(document.size_bytes)} · {documentStatus(document.status)}</span></div></li>)}{!workspace.documents.length ? <li className={styles.documentEmpty}>尚未上传文件。当前版本支持文本、Markdown、表格、DOC、DOCX 与 PDF 资料。</li> : null}</ul>
            <section className={styles.taskPanel} aria-labelledby="task-title"><div className={styles.taskHeading}><h3 id="task-title">处理状态</h3><span>{activeTasks.length ? "运行中" : "空闲"}</span></div><ul>{workspace.tasks.slice(0, 3).map((task) => <li key={task.id}><span className={`${styles.taskMarker} ${task.status === "SUCCEEDED" ? styles.taskDone : ""}`} /><div><strong>{task.task_type === "GENERATE_EMBEDDINGS" ? "向量索引" : "文件解析"}</strong><span>{taskDetail(task)}</span></div></li>)}{!workspace.tasks.length ? <li className={styles.taskEmpty}>上传文件后，解析和索引任务会显示在这里。</li> : null}</ul></section>
          </aside>
        </div> : null}
      </main>
      {deletionTarget ? <div className={styles.dialogBackdrop} role="presentation">
        <section className={styles.confirmDialog} role="alertdialog" aria-modal="true" aria-labelledby="delete-dialog-title" aria-describedby="delete-dialog-description">
          <p className={styles.eyebrow}>确认操作</p>
          <h2 id="delete-dialog-title">删除{deletionTarget.kind === "workspace" ? "知识库" : "对话"}？</h2>
          <p id="delete-dialog-description">{deletionTarget.kind === "workspace" ? <>“{deletionTarget.workspace.name}”中的文件、索引和全部对话将一并删除，且无法恢复。</> : <>“{deletionTarget.conversation.title}”中的全部消息将被删除，且无法恢复。</>}</p>
          <div className={styles.dialogActions}>
            <button className={styles.secondaryButton} type="button" onClick={() => setDeletionTarget(null)} disabled={isDeleting}>取消</button>
            <button className={styles.dangerButton} type="button" onClick={() => void confirmDeletion()} disabled={isDeleting}>{isDeleting ? "删除中…" : "确认删除"}</button>
          </div>
        </section>
      </div> : null}
    </div>
  );
}
