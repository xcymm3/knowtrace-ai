"use client";

import { type FormEvent, memo, useEffect, useRef, useState } from "react";
import Markdown from "react-markdown";

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
const activityLabels = { tool_start: "调用", tool_end: "完成", tool_error: "工具错误" };

function inProgress(run: Run | undefined) {
  return !!run && !["SUCCEEDED", "FAILED", "CANCELLED"].includes(run.status);
}

function errorText(error: unknown) {
  return error instanceof Error ? error.message : "Agent 请求失败，请重试。";
}

function Glyph({ name }: { name: "panel" | "plus" | "search" | "folder" | "send" }) {
  return <span className={styles.glyph} data-glyph={name} aria-hidden="true" />;
}

const RunLog = memo(function RunLog({ events, active }: { events: Run["events"]; active: boolean }) {
  const blocks: Run["events"][] = [];
  for (const event of events) {
    const block = blocks.at(-1);
    if (event.kind in activityLabels && block && block[0].kind in activityLabels) block.push(event);
    else blocks.push([event]);
  }
  return blocks.map((block, index) => {
    const [entry] = block;
    if (entry.kind === "message") return (
      <div key={index} className={styles.reply}>
        <Markdown skipHtml disallowedElements={["img"]} components={{
          a: ({ href, children }) => <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>,
        }}>{entry.text}</Markdown>
      </div>
    );
    if (entry.kind === "error") return <p key={index} className={styles.failure}>{entry.text}</p>;
    const hasError = block.some((event) => event.kind === "tool_error");
    return (
      <details key={index} className={styles.activity} open={active || hasError}>
        <summary>工具记录 <span>{block.filter((event) => event.kind === "tool_start").length || block.length}</span></summary>
        <ul>
          {block.map((event, offset) => (
            <li key={offset} data-kind={event.kind}>
              <span>{activityLabels[event.kind as keyof typeof activityLabels]}</span>{event.text}
            </li>
          ))}
        </ul>
      </details>
    );
  });
});

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
        <strong>KnowTrace</strong>
        <span>{permissionLabels[run.permission]} · {statusLabels[run.status]}</span>
        {inProgress(run) && (
          <button type="button" className={styles.lightButton} disabled={busy || run.cancel_requested}
            onClick={() => void onAction(run)}>{run.cancel_requested ? "正在取消" : "取消任务"}</button>
        )}
      </div>
      <RunLog events={run.events} active={inProgress(run)} />
      {approval && (
        <section className={styles.approval} aria-labelledby={`approval-${approval.id}`}>
          <div className={styles.approvalHead}>
            <h3 id={`approval-${approval.id}`}>{approval.path}</h3>
            <span>{approvalLabels[approval.status]}</span>
          </div>
          <pre tabIndex={0} aria-label="变更预览"><code>{approval.diff.split("\n").map((line, index) => (
            <span key={index} data-diff={line.startsWith("+") ? "addition" : line.startsWith("-") ? "deletion" : undefined}>
              {line}{"\n"}
            </span>
          ))}</code></pre>
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
  const [searchOpen, setSearchOpen] = useState(false);
  const [query, setQuery] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const search = useRef<HTMLInputElement>(null);
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
            if (!next || next.revision <= run.revision) incoming.set(run.id, run);
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

  useEffect(() => {
    if (searchOpen && railOpen) search.current?.focus();
  }, [railOpen, searchOpen]);

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

  const project = directory.split(/[\\/]/).filter(Boolean).at(-1) || "本机项目";
  const title = threads.find((entry) => entry.thread_id === thread)?.task || "新会话";
  const visibleThreads = threads.filter((entry) => entry.task.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase()));
  const connected = connection === "本机执行器已连接";
  const toggleRail = () => setRailOpen((open) => !open);

  return (
    <div className={styles.desk} data-rail={railOpen ? "open" : "closed"}>
      <div className={styles.utility} aria-label="工作台快捷操作">
        <button type="button" className={styles.utilityBrand} title="新建会话" aria-label="新建会话" onClick={newThread} disabled={busy}>K</button>
        <button type="button" className={styles.iconButton} title={railOpen ? "收起侧栏" : "展开侧栏"}
          aria-label={railOpen ? "收起侧栏" : "展开侧栏"} aria-expanded={railOpen} aria-controls="agent-sidebar" onClick={toggleRail}>
          <Glyph name="panel" />
        </button>
        <span className={styles.utilityState} title={connection} data-ready={connected} aria-hidden="true" />
      </div>
      <aside id="agent-sidebar" className={styles.rail} aria-label="会话侧栏">
        <div className={styles.railHeader}>
          <span className={styles.brand}>KnowTrace</span>
          <button type="button" className={styles.iconButton} title="搜索会话" aria-label="搜索会话" aria-expanded={searchOpen}
            aria-controls="thread-search" onClick={() => {
              setSearchOpen((open) => !open);
              if (searchOpen) setQuery("");
            }}><Glyph name="search" /></button>
        </div>
        <div className={styles.railActions}>
          <button className={styles.newThread} type="button" onClick={newThread} disabled={busy}><Glyph name="plus" /> 新建会话</button>
          <div id="thread-search" hidden={!searchOpen}>
            <label className={styles.srOnly} htmlFor="thread-query">搜索会话标题</label>
            <input ref={search} id="thread-query" type="search" value={query} placeholder="搜索会话标题" onChange={(event) => setQuery(event.target.value)} />
          </div>
        </div>
        <nav className={styles.threads} aria-labelledby="threads-title">
          <h2 id="threads-title">项目</h2>
          <div className={styles.projectName} title={directory || project}><Glyph name="folder" /><span>{project}</span></div>
          <div className={styles.threadList}>
            {visibleThreads.length === 0 && <p>{query.trim() ? "未找到会话" : "暂无会话"}</p>}
            {visibleThreads.map((entry) => (
              <button key={entry.id} title={entry.task} type="button" disabled={busy}
                aria-current={entry.thread_id === thread ? "page" : undefined} onClick={() => select(entry.thread_id)}>{entry.task}</button>
            ))}
          </div>
        </nav>
        <p className={styles.connection} role="status" data-ready={connected}><span aria-hidden="true" />{connection}</p>
      </aside>

      <main className={styles.workspace}>
        <header className={styles.topbar}>
          <button className={`${styles.iconButton} ${styles.mobileToggle}`} type="button" aria-label={railOpen ? "收起侧栏" : "展开侧栏"}
            aria-expanded={railOpen} aria-controls="agent-sidebar" onClick={toggleRail}><Glyph name="panel" /></button>
          <div className={styles.headerProject} title={directory || project}><Glyph name="folder" /><span>{project}</span></div>
          <span className={styles.headerDivider} aria-hidden="true" />
          {thread ? <h1 className={styles.threadTitle} title={title}>{title}</h1> :
            <p className={styles.threadTitle}>{title}</p>}
        </header>

        <div className={styles.timeline} ref={timeline} onScroll={(event) => {
          const area = event.currentTarget;
          follow.current = area.scrollHeight - area.clientHeight - area.scrollTop < 80;
        }}>
          <div className={styles.column}>
            {!thread && <div className={styles.welcome}>
              <div className={styles.welcomeMark} aria-hidden="true">K</div>
              <h1>交给 KnowTrace 一个任务</h1>
              <p>查看项目、修改文件，或在本机创建目录。</p>
            </div>}
            {thread && runs.length === 0 && <p role="status">正在读取会话…</p>}
            {runs.map((run) => <RunEntry key={run.id} run={run} busy={busy} onAction={action} />)}
          </div>
        </div>

        <div className={styles.composerArea}>
          <form className={styles.composer} onSubmit={start}>
            <label className={styles.srOnly} htmlFor="agent-input">任务描述</label>
            <textarea id="agent-input" ref={input} placeholder={thread ? "继续这段会话…" : "描述你想完成的任务…"}
              rows={2} maxLength={8000} required value={task} onChange={(event) => setTask(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && (event.ctrlKey || event.metaKey) && !event.nativeEvent.isComposing) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }} />
            <div className={styles.composerFooter}>
              <div className={styles.permission} data-full={permission === "full"}>
                <label className={styles.srOnly} htmlFor="permission">文件访问权限</label>
                <select id="permission" value={permission} aria-describedby="permission-help" disabled={busy}
                  onChange={(event) => setPermission(event.target.value as Permission)}>
                  <option value="read_only">只读</option>
                  <option value="project">项目工作树</option>
                  <option value="full">完全访问</option>
                </select>
              </div>
              <div className={styles.sendArea}>
                <kbd aria-hidden="true">Ctrl ↵</kbd>
                <button type="submit" className={styles.send} aria-label="发送任务" aria-keyshortcuts="Control+Enter Meta+Enter" title="发送任务（Ctrl+Enter）"
                  disabled={busy || !directory || !task.trim() || runs.some(inProgress)}><Glyph name="send" /></button>
              </div>
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
