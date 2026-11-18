export type WorkspaceStatus = "DRAFT" | "ACTIVE" | "ARCHIVED";
export type TaskStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED" | "CANCELLED";

export interface WorkspaceProject {
  id: string;
  name: string;
  description: string | null;
  status: WorkspaceStatus;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeDocument {
  id: string;
  workspace_id: string;
  kind: string;
  file_name: string;
  mime_type: string;
  size_bytes: number;
  status: string;
  error_message: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DocumentUploadResponse {
  id: string;
  workspace_id: string;
  kind: string;
  file_name: string;
  status: string;
  task_id: string;
  task_status: string;
}

export interface ProcessingTask {
  id: string;
  workspace_id: string;
  document_id: string | null;
  task_type: string;
  status: TaskStatus;
  progress: number;
  attempt_count: number;
  max_attempts: number;
  output_payload: Record<string, unknown>;
  error_message: string | null;
  started_at: string | null;
  completed_at: string | null;
}

export interface WorkspaceOverview {
  documents: KnowledgeDocument[];
  tasks: ProcessingTask[];
  conversations: Conversation[];
}

export interface Conversation {
  id: string;
  workspace_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface SourceCitation {
  document_id: string;
  file_name: string;
  kind: string;
  chunk_index: number;
  start_char: number | null;
  end_char: number | null;
}

export interface RagSource {
  chunk_id: string;
  citation: SourceCitation;
  excerpt: string;
  score: number | null;
}

export interface ConversationMessage {
  id: string;
  conversation_id: string;
  role: "USER" | "ASSISTANT" | "SYSTEM";
  content: string;
  sequence: number;
  created_at: string;
  sources: RagSource[];
}

export interface UsernameSignInSession {
  access_token: string;
  refresh_token: string;
  expires_in: number;
  token_type: string;
}

export interface UsernameAvailability {
  available: boolean;
}

export type AgentRunStatus = TaskStatus | "WAITING_APPROVAL" | "APPLYING";
export type AgentRunConfig = { mode: "local"; directory: string } | { mode: "remote" };

export interface AgentRunSummary {
  id: string;
  executor_id: string;
  task: string;
  status: AgentRunStatus;
  revision: number;
  created_at: string;
}

export interface AgentRunSnapshot extends AgentRunSummary {
  cancel_requested: boolean;
  approval: {
    id: string;
    path: string;
    diff: string;
    status: "pending" | "approved" | "rejected" | "applying" | "applied" | "failed" | "cancelled";
    change_id: string | null;
    error: string | null;
  } | null;
  events: { kind: "tool_start" | "tool_end" | "tool_error" | "message" | "error"; text: string }[];
}

type RagStreamEvent =
  | { event: "retrieval"; data: { conversation_id: string; sources: RagSource[] } }
  | { event: "token"; data: { delta: string } }
  | { event: "complete"; data: { message: Omit<ConversationMessage, "sources">; sources: RagSource[] } }
  | { event: "error"; data: { code?: string; message?: string } };

export class ApiError extends Error {
  constructor(message: string, public readonly code?: string) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  const accessToken = await getAccessToken();
  if (!accessToken) throw new ApiError("登录已失效，请重新登录。", "AUTHENTICATION_REQUIRED");
  headers.set("Authorization", `Bearer ${accessToken}`);
  if (init?.body && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError("无法连接后端服务，请检查 API 地址与部署状态。");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? "请求失败，请稍后重试。", payload?.error?.code);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

async function signInWithIdentity(identity: string, password: string): Promise<UsernameSignInSession> {
  let response: Response;
  try {
    response = await fetch("/api/v1/auth/sign-in", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ identity, password }),
    });
  } catch {
    throw new ApiError("无法连接登录服务，请检查 API 地址与部署状态。");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? "登录失败，请稍后重试。", payload?.error?.code);
  }
  return response.json() as Promise<UsernameSignInSession>;
}

async function signUpWithUsername(username: string, password: string): Promise<UsernameSignInSession> {
  let response: Response;
  try {
    response = await fetch("/api/v1/auth/sign-up", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
  } catch {
    throw new ApiError("无法连接注册服务，请检查 API 地址与部署状态。");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? "账号创建失败，请稍后重试。", payload?.error?.code);
  }
  return response.json() as Promise<UsernameSignInSession>;
}

async function checkUsernameAvailability(username: string): Promise<UsernameAvailability> {
  let response: Response;
  try {
    response = await fetch(`/api/v1/auth/username-availability?username=${encodeURIComponent(username)}`);
  } catch {
    throw new ApiError("暂时无法检查用户名，请稍后重试。", "USERNAME_CHECK_UNAVAILABLE");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? "暂时无法检查用户名，请稍后重试。", payload?.error?.code);
  }
  return response.json() as Promise<UsernameAvailability>;
}

function parseSseBlock(block: string): { event: string; data: unknown } | null {
  const event = block.match(/^event:\s*(.+)$/m)?.[1];
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!event || !data) return null;
  return { event, data: JSON.parse(data) };
}

async function readSse(response: Response, onFrame: (frame: NonNullable<ReturnType<typeof parseSseBlock>>) => void) {
  if (!response.body) throw new ApiError("服务未返回可读取的事件流。");
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  try {
    while (true) {
      const { done, value } = await reader.read();
      buffer += decoder.decode(value, { stream: !done });
      const blocks = buffer.split(/\r?\n\r?\n/);
      buffer = blocks.pop() ?? "";
      for (const block of blocks) {
        const frame = parseSseBlock(block);
        if (frame) onFrame(frame);
      }
      if (done) break;
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
}

function agentPath(workspaceId: string, runId?: string) {
  const root = `/api/v1/workspaces/${workspaceId}/agent/runs`;
  return runId ? `${root}/${runId}` : root;
}

async function streamAgentRun(
  workspaceId: string, runId: string, after: number,
  onSnapshot: (snapshot: AgentRunSnapshot) => void, signal: AbortSignal,
) {
  const accessToken = await getAccessToken();
  if (!accessToken) throw new ApiError("登录已失效，请重新登录。", "AUTHENTICATION_REQUIRED");
  const response = await fetch(`${agentPath(workspaceId, runId)}/events?after=${after}`, {
    headers: { Authorization: `Bearer ${accessToken}` },
    signal,
    cache: "no-store",
  });
  if (!response.ok) throw new ApiError("任务更新连接中断。");
  await readSse(response, (frame) => {
    if (frame.event === "snapshot") onSnapshot(frame.data as AgentRunSnapshot);
  });
}

async function streamRagAnswer(
  workspaceId: string,
  conversationId: string,
  question: string,
  retrievalLimit: number,
  onEvent: (event: RagStreamEvent) => void,
  signal?: AbortSignal,
) {
  let response: Response;
  try {
    const accessToken = await getAccessToken();
    if (!accessToken) throw new ApiError("登录已失效，请重新登录。", "AUTHENTICATION_REQUIRED");
    response = await fetch(`/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${accessToken}` },
      body: JSON.stringify({ question, retrieval_limit: retrievalLimit }),
      signal,
    });
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("无法连接后端服务，请检查 API 地址与部署状态。");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? "提问失败，请稍后重试。", payload?.error?.code);
  }
  await readSse(response, (frame) => {
    const event = frame as RagStreamEvent;
    if (event.event === "error") throw new ApiError(event.data.message ?? "回答生成中断，请稍后重试。", event.data.code);
    onEvent(event);
  });
}

export const knowTraceApi = {
  signInWithIdentity,
  signUpWithUsername,
  checkUsernameAvailability,
  listWorkspaces: () => request<WorkspaceProject[]>("/api/v1/workspaces"),
  createWorkspace: (name: string) =>
    request<WorkspaceProject>("/api/v1/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  deleteWorkspace: (workspaceId: string) =>
    request<void>(`/api/v1/workspaces/${workspaceId}`, { method: "DELETE" }),
  getWorkspaceOverview: (workspaceId: string) =>
    request<WorkspaceOverview>(`/api/v1/workspaces/${workspaceId}/overview`),
  listDocuments: (workspaceId: string) => request<KnowledgeDocument[]>(`/api/v1/workspaces/${workspaceId}/documents`),
  listTasks: (workspaceId: string) => request<ProcessingTask[]>(`/api/v1/tasks/workspaces/${workspaceId}`),
  uploadDocument: (workspaceId: string, formData: FormData) =>
    request<DocumentUploadResponse>(`/api/v1/workspaces/${workspaceId}/documents`, { method: "POST", body: formData }),
  deleteDocument: (workspaceId: string, documentId: string) =>
    request<void>(`/api/v1/workspaces/${workspaceId}/documents/${documentId}`, { method: "DELETE" }),
  listConversations: (workspaceId: string) => request<Conversation[]>(`/api/v1/workspaces/${workspaceId}/conversations`),
  createConversation: (workspaceId: string, title: string) =>
    request<Conversation>(`/api/v1/workspaces/${workspaceId}/conversations`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (workspaceId: string, conversationId: string) =>
    request<void>(`/api/v1/workspaces/${workspaceId}/conversations/${conversationId}`, { method: "DELETE" }),
  retryTask: (taskId: string) => request<ProcessingTask>(`/api/v1/tasks/${taskId}/retry`, { method: "POST" }),
  cancelTask: (taskId: string) => request<ProcessingTask>(`/api/v1/tasks/${taskId}/cancel`, { method: "POST" }),
  listMessages: (workspaceId: string, conversationId: string) =>
    request<ConversationMessage[]>(`/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`),
  streamRagAnswer,
  listAgentRuns: (workspaceId: string, signal?: AbortSignal) =>
    request<AgentRunSummary[]>(agentPath(workspaceId), { signal, cache: "no-store" }),
  getAgentRunConfig: (workspaceId: string, signal?: AbortSignal) =>
    request<AgentRunConfig>(`${agentPath(workspaceId)}/config`, { signal, cache: "no-store" }),
  getAgentRun: (workspaceId: string, runId: string, signal?: AbortSignal) =>
    request<AgentRunSnapshot>(agentPath(workspaceId, runId), { signal, cache: "no-store" }),
  createAgentRun: (workspaceId: string, id: string, executorId: string | null, task: string) =>
    request<AgentRunSnapshot>(agentPath(workspaceId), {
      method: "POST",
      body: JSON.stringify({ id, executor_id: executorId, task }),
    }),
  decideAgentRun: (workspaceId: string, runId: string, approvalId: string, approved: boolean) =>
    request<AgentRunSnapshot>(`${agentPath(workspaceId, runId)}/decision`, {
      method: "POST",
      body: JSON.stringify({ approval_id: approvalId, approved }),
    }),
  cancelAgentRun: (workspaceId: string, runId: string) =>
    request<AgentRunSnapshot>(`${agentPath(workspaceId, runId)}/cancel`, { method: "POST" }),
  streamAgentRun,
};
import { getAccessToken } from "@/lib/supabase-browser";
