"use client";

import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  knowTraceApi,
  type KnowledgeDocument,
  type ProcessingTask,
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
  return { READY: "已索引", PROCESSING: "处理中", PENDING: "等待处理", FAILED: "处理失败" }[status] ?? status;
}

function taskDetail(task: ProcessingTask) {
  if (task.status === "FAILED") return task.error_message ?? "任务执行失败";
  if (task.status === "SUCCEEDED") return task.task_type === "GENERATE_EMBEDDINGS" ? "向量索引已完成" : "文本解析已完成";
  return `${task.progress}% · ${task.task_type === "GENERATE_EMBEDDINGS" ? "正在建立向量索引" : "正在解析文件"}`;
}

function formatBytes(size: number) {
  return size < 1024 * 1024 ? `${Math.max(1, Math.ceil(size / 1024))} KB` : `${(size / 1024 / 1024).toFixed(1)} MB`;
}

export function WorkspaceClient() {
  const [projects, setProjects] = useState<WorkspaceProject[]>([]);
  const [projectId, setProjectId] = useState<string | null>(null);
  const [workspace, setWorkspace] = useState<WorkspaceData>(emptyWorkspace);
  const [isLoading, setIsLoading] = useState(true);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const activeProject = projects.find((project) => project.id === projectId) ?? null;
  const activeTasks = useMemo(() => workspace.tasks.filter((task) => ["QUEUED", "RUNNING"].includes(task.status)), [workspace.tasks]);
  const indexedDocuments = useMemo(() => workspace.documents.filter((document) => document.status === "READY"), [workspace.documents]);

  const loadWorkspace = useCallback(async (workspaceId: string) => {
    const [documents, tasks] = await Promise.all([knowTraceApi.listDocuments(workspaceId), knowTraceApi.listTasks(workspaceId)]);
    setWorkspace({ documents, tasks });
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
      setIsLoading(true);
      setError(null);
      try {
        await loadWorkspace(projectId);
      } catch (caughtError) {
        setError(readableError(caughtError));
      } finally {
        setIsLoading(false);
      }
    })();
  }, [loadWorkspace, projectId]);

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
              <button className={`${styles.projectItem} ${project.id === projectId ? styles.projectItemActive : ""}`} key={project.id} type="button" onClick={() => setProjectId(project.id)} aria-pressed={project.id === projectId}>
                <span className={styles.projectItemName}>{project.name}</span><span>{workspaceStatus(project.status)}</span>
              </button>
            ))}
            {!projects.length && !isLoading ? <p className={styles.railEmpty}>建立一个项目，将资料和后续对话放在同一范围内。</p> : null}
          </div>
        </section>

        <div className={styles.sidebarFoot}><span className={styles.statusDot} aria-hidden="true" />RAG MVP · Step 2</div>
      </aside>

      <main className={styles.main} id="workspace-main">
        {error ? <p className={styles.feedbackError} role="alert">{error}</p> : null}
        {notice ? <p className={styles.feedbackNotice}>{notice}</p> : null}

        {!activeProject && !isLoading ? (
          <section className={styles.welcome} aria-labelledby="welcome-title">
            <p className={styles.eyebrow}>KNOWTRACE AI</p><h1 id="welcome-title">从一个项目开始整理资料。</h1>
            <p>每个项目拥有独立的文件与后续对话范围。先在左侧命名项目，再上传第一份资料。</p>
          </section>
        ) : null}

        {activeProject ? (
          <div className={styles.workspaceGrid}>
            <section className={styles.chatPane} aria-labelledby="project-title">
              <header className={styles.workspaceHeader}>
                <div><p className={styles.eyebrow}>当前项目</p><h1 id="project-title">{activeProject.name}</h1></div>
                <span className={styles.workspaceState}>{workspaceStatus(activeProject.status)}</span>
              </header>

              <div className={styles.conversationPlaceholder}>
                <div className={styles.placeholderGlyph} aria-hidden="true" />
                <h2>资料准备就绪后，在这里开始对话。</h2>
                <p>KnowTrace 将只检索当前项目中的已索引资料，并在回答中附上可回看的原文来源。</p>
                <dl className={styles.workspaceMetrics}>
                  <div><dt>已索引文件</dt><dd>{indexedDocuments.length}</dd></div>
                  <div><dt>等待处理</dt><dd>{workspace.documents.length - indexedDocuments.length}</dd></div>
                  <div><dt>运行任务</dt><dd>{activeTasks.length}</dd></div>
                </dl>
              </div>

              <form className={styles.composer} onSubmit={(event) => event.preventDefault()}>
                <label className={styles.srOnly} htmlFor="message">向项目资料提问</label>
                <textarea id="message" disabled placeholder="引用式对话将在 RAG 接口完成后开放" rows={1} />
                <button className={styles.iconButton} type="submit" disabled aria-label="发送问题">↑</button>
              </form>
            </section>

            <aside className={styles.filesPane} aria-labelledby="files-title">
              <header className={styles.filesHeader}><div><p className={styles.eyebrow}>项目资料</p><h2 id="files-title">文件</h2></div><span>{workspace.documents.length}</span></header>
              <form className={styles.uploadForm} onSubmit={handleUpload}>
                <label className={styles.uploadLabel}>选择文件<input name="file" type="file" required accept=".txt,.md,.csv,.xlsx,.pdf,.jpg,.jpeg,.png,.webp" /></label>
                <button className={styles.primaryButton} type="submit" disabled={isSubmitting}>上传并解析</button>
              </form>
              <ul className={styles.documentList}>
                {workspace.documents.map((document) => <li key={document.id}><span className={styles.fileType}>{document.file_name.split(".").pop()?.toUpperCase() ?? "FILE"}</span><div><strong>{document.file_name}</strong><span>{formatBytes(document.size_bytes)} · {documentStatus(document.status)}</span></div></li>)}
                {!workspace.documents.length ? <li className={styles.documentEmpty}>尚未上传文件。当前版本可处理文本、表格、PDF 和常见图片资料。</li> : null}
              </ul>
              <section className={styles.taskPanel} aria-labelledby="task-title"><div className={styles.taskHeading}><h3 id="task-title">处理状态</h3><span>{activeTasks.length ? "运行中" : "空闲"}</span></div><ul>{workspace.tasks.slice(0, 3).map((task) => <li key={task.id}><span className={`${styles.taskMarker} ${task.status === "SUCCEEDED" ? styles.taskDone : ""}`} /><div><strong>{task.task_type === "GENERATE_EMBEDDINGS" ? "向量索引" : "文件解析"}</strong><span>{taskDetail(task)}</span></div></li>)}{!workspace.tasks.length ? <li className={styles.taskEmpty}>上传文件后，解析和索引任务会显示在这里。</li> : null}</ul></section>
            </aside>
          </div>
        ) : null}
      </main>
    </div>
  );
}
