"use client";

import { type FormEvent, useEffect, useRef, useState } from "react";

import { api, type Permission, type Run, type RunSummary, type Status } from "./api";
import styles from "./agent-desk.module.css";

const permissionLabels: Record<Permission, string> = { read_only: "只读", project: "项目工作树", full: "完全访问" };
const statusLabels: Record<Status, string> = {
  QUEUED: "排队中", RUNNING: "执行中", WAITING_APPROVAL: "等待确认", APPLYING: "写入中",
  SUCCEEDED: "已完成", FAILED: "失败", CANCELLED: "已取消",
};
const approvalLabels = {
  pending: "等待确认", approved: "已确认", rejected: "已拒绝", applying: "写入中",
  applied: "已写入", failed: "写入失败", cancelled: "已取消",
};

function inProgress(run: Run | undefined) {
  return !!run && !["SUCCEEDED", "FAILED", "CANCELLED"].includes(run.status);
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Agent 请求失败，请重试。";
}

function RunEntry({ run, busy, onAction }: {
  run: Run;
  busy: boolean;
  onAction: (run: Run, approved?: boolean) => Promise<void>;
}) {
  const approval = run.approval;
  return (
    <article className={styles.turn}>
      <p className={styles.prompt}>{run.task}</p>
      <div className={styles.turnHeader}>
        <span className={styles.agentStamp} aria-hidden="true">K</span>
        <strong>Agent</strong>
        <span>{permissionLabels[run.permission]} · {statusLabels[run.status]}</span>
        {inProgress(run) && (
          <button type="button" className={styles.lightButton} disabled={busy || run.cancel_requested}
            onClick={() => void onAction(run)}>{run.cancel_requested ? "正在取消" : "取消任务"}</button>
        )}
      </div>
      {run.events.length > 0 && (
        <ol className={styles.log} aria-label="执行记录">
          {run.events.map((event, index) => (
            <li key={index} data-kind={event.kind}>
              {event.kind === "tool_start" && <span className={styles.eventLabel}>调用</span>}
              {event.kind === "tool_end" && <span className={styles.eventLabel}>完成</span>}
              {event.kind === "tool_error" && <span className={styles.eventLabel}>工具错误</span>}
              <span>{event.text}</span>
            </li>
          ))}
        </ol>
      )}
      {approval && (
        <section className={styles.approval} aria-labelledby={`approval-${approval.id}`}>
          <div className={styles.approvalHead}>
            <h3 id={`approval-${approval.id}`}>{approval.path}</h3>
            <span>{approvalLabels[approval.status]}</span>
          </div>
          <pre tabIndex={0} aria-label="变更预览"><code>{approval.diff}</code></pre>
          {approval.error && <p className={styles.alert}>{approval.error}</p>}
          {approval.change_id && <p className={styles.receipt}>回退 ID <code>{approval.change_id}</code></p>}
          {approval.status === "pending" && (
            <div className={styles.buttons}>
              <button type="button" className={styles.lightButton} disabled={busy} onClick={() => void onAction(run, false)}>拒绝变更</button>
              <button type="button" className={styles.primary} disabled={busy} onClick={() => void onAction(run, true)}>确认写入</button>
            </div>
          )}
        </section>
      )}
    </article>
  );
}

export function AgentDesk() {
  const [directory, setDirectory] = useState("");
  const [threads, setThreads] = useState<RunSummary[]>([]);
  const [thread, setThread] = useState("");
  const [runs, setRuns] = useState<Run[]>([]);
  const [task, setTask] = useState("");
  const [permission, setPermission] = useState<Permission>("project");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [connection, setConnection] = useState("连接本机执行器…");
  const [railOpen, setRailOpen] = useState(true);
  const input = useRef<HTMLTextAreaElement>(null);
  const timeline = useRef<HTMLDivElement>(null);
  const follow = useRef(true);
  const selected = useRef("");
  const pending = useRef<Parameters<typeof api.start>[0] | null>(null);
  const lastRun = runs.at(-1);
  const lastRunId = lastRun?.id;
  const lastRevision = lastRun?.revision;

  function select(id: string) {
    selected.current = id;
    setThread(id);
    setRuns([]);
    setError("");
    follow.current = true;
    const url = new URL(window.location.href);
    url.search = "";
    if (id) url.searchParams.set("thread", id);
    history.replaceState(null, "", url);
  }

  useEffect(() => {
    const controller = new AbortController();
    void Promise.all([api.config(controller.signal), api.threads(controller.signal)]).then(([config, items]) => {
      if (controller.signal.aborted) return;
      setDirectory(config.directory);
      setThreads(items);
      setConnection("本机执行器已连接");
      const saved = new URL(window.location.href).searchParams.get("thread");
      if (saved && items.some((item) => item.thread_id === saved)) select(saved);
    }).catch((caught) => {
      if (controller.signal.aborted) return;
      setConnection("本机执行器未连接");
      setError(errorText(caught));
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    if (!thread) return;
    const controller = new AbortController();
    let timer: number | undefined;
    async function load() {
      try {
        const items = await api.thread(thread, controller.signal);
        if (controller.signal.aborted) return;
        setRuns((old) => {
          const incoming = new Map(items.map((run) => [run.id, run]));
          for (const run of old) {
            const next = incoming.get(run.id);
            if (!next || next.revision < run.revision) incoming.set(run.id, run);
          }
          return [...incoming.values()].slice(-60);
        });
        setConnection("本机执行器已连接");
        if (!items.some(inProgress)) return;
      } catch {
        if (!controller.signal.aborted) setConnection("正在重新连接…");
      }
      if (!controller.signal.aborted) timer = window.setTimeout(load, 850);
    }
    void load();
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [thread, lastRunId]);

  useEffect(() => {
    if (timeline.current && follow.current) timeline.current.scrollTop = timeline.current.scrollHeight;
  }, [lastRunId, lastRevision]);

  function apply(run: Run) {
    if (run.thread_id !== selected.current) return;
    setRuns((old) => {
      if (!old.some((entry) => entry.id === run.id)) return [...old, run];
      return old.map((entry) => entry.id === run.id && entry.revision <= run.revision ? run : entry);
    });
  }

  async function start(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const body = task.trim();
    if (!body || busy || !directory || runs.some(inProgress)) return;
    if (pending.current?.task !== body || pending.current.permission !== permission ||
      (thread ? pending.current.thread_id !== thread : pending.current.thread_id !== pending.current.id)) {
      const id = crypto.randomUUID();
      pending.current = { id, thread_id: thread || id, task: body, permission };
    }
    setBusy(true);
    setError("");
    try {
      const run = await api.start(pending.current);
      pending.current = null;
      if (!thread) {
        setThreads((old) => [run, ...old.filter((entry) => entry.id !== run.id)]);
        select(run.thread_id);
      }
      apply(run);
      follow.current = true;
      setTask("");
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  async function action(run: Run, approved?: boolean) {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      apply(approved !== undefined && run.approval
        ? await api.decide(run.id, run.approval.id, approved) : await api.cancel(run.id));
    } catch (caught) {
      setError(errorText(caught));
    } finally {
      setBusy(false);
    }
  }

  function newThread() {
    select("");
    pending.current = null;
    setTask("");
    setPermission("project");
    input.current?.focus();
  }

  return (
    <div className={styles.desk} data-rail={railOpen ? "open" : "closed"}>
      <aside id="agent-sidebar" className={styles.rail} aria-label="会话侧栏">
        <div className={styles.brand}><span className={styles.wordmark} aria-hidden="true">K</span>KnowTrace</div>
        <button className={styles.newThread} type="button" onClick={newThread} disabled={busy}><span aria-hidden="true">＋</span> 新建会话</button>
        <nav className={styles.threads} aria-labelledby="threads-title">
          <h2 id="threads-title">会话记录</h2>
          {threads.length === 0 && <p>暂无会话</p>}
          {threads.map((entry) => (
            <button key={entry.id} title={entry.task} type="button" disabled={busy}
              aria-current={entry.thread_id === thread ? "page" : undefined} onClick={() => select(entry.thread_id)}>
              <span aria-hidden="true" className={styles.threadIcon} />{entry.task}
            </button>
          ))}
        </nav>
        <p className={styles.connection} role="status" data-ready={connection === "本机执行器已连接"}><span aria-hidden="true" />{connection}</p>
      </aside>

      <main className={styles.workspace}>
        <header className={styles.topbar}>
          <button className={styles.railToggle} type="button" aria-label={railOpen ? "收起侧栏" : "展开侧栏"}
            aria-expanded={railOpen} aria-controls="agent-sidebar" onClick={() => setRailOpen((open) => !open)}>☰</button>
          <span>Agent <span aria-hidden="true">/</span> {thread ? "会话" : "新任务"}</span>
          {directory && <span className={styles.directory} title={directory}>{directory}</span>}
        </header>

        <div className={styles.timeline} ref={timeline} onScroll={(event) => {
          const area = event.currentTarget;
          follow.current = area.scrollHeight - area.clientHeight - area.scrollTop < 80;
        }}>
          <div className={styles.column}>
            {!thread && <div className={styles.welcome}>
              <div className={styles.welcomeMark} aria-hidden="true">K<span>›</span></div>
              <h1>今天要做什么？</h1>
              <p>描述任务，Agent 会在所选权限下读取文件、提出变更并执行。</p>
            </div>}
            {thread && runs.length === 0 && <p role="status">正在读取会话…</p>}
            {runs.map((run) => <RunEntry key={run.id} run={run} busy={busy} onAction={action} />)}
          </div>
        </div>

        <div className={styles.composerArea}>
          <form className={styles.composer} onSubmit={start}>
            <label className={styles.srOnly} htmlFor="agent-input">任务描述</label>
            <textarea id="agent-input" ref={input} placeholder={thread ? "继续这个会话…" : "输入任务，例如：在 D 盘创建一个空文件夹"}
              rows={3} maxLength={8000} required value={task} onChange={(event) => setTask(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }} />
            <div className={styles.composerFooter}>
              <div className={styles.permission} data-full={permission === "full"}>
                <label htmlFor="permission">权限</label>
                <select id="permission" value={permission} aria-describedby="permission-help" disabled={busy}
                  onChange={(event) => setPermission(event.target.value as Permission)}>
                  <option value="read_only">只读</option>
                  <option value="project">项目工作树</option>
                  <option value="full">完全访问</option>
                </select>
              </div>
              <button type="submit" className={styles.send} aria-label="发送任务" title="发送任务（Ctrl+Enter）"
                disabled={busy || !directory || !task.trim() || runs.some(inProgress)}><span aria-hidden="true">↑</span></button>
            </div>
          </form>
          <p id="permission-help" className={styles.hint} data-full={permission === "full"}>
            {permission === "full" ? "允许访问当前账户可用的本机路径。文件内容可能传给模型，写入需确认。" :
              permission === "read_only" ? "只读取项目目录内的文件。" : "在隔离的 Git 工作树内修改。写入需确认。"}
          </p>
          {error && <p className={styles.alert} role="alert">{error}</p>}
        </div>
      </main>
    </div>
  );
}
