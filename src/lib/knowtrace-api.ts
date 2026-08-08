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

function parseSseBlock(block: string): RagStreamEvent | null {
  const event = block.match(/^event:\s*(.+)$/m)?.[1];
  const data = block
    .split(/\r?\n/)
    .filter((line) => line.startsWith("data:"))
    .map((line) => line.slice(5).trimStart())
    .join("\n");
  if (!event || !data) return null;
  return { event, data: JSON.parse(data) } as RagStreamEvent;
}

async function streamRagAnswer(
  workspaceId: string,
  conversationId: string,
  question: string,
  onEvent: (event: RagStreamEvent) => void,
  signal?: AbortSignal,
) {
  let response: Response;
  try {
    response = await fetch(`/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError("无法连接后端服务，请检查 API 地址与部署状态。");
  }
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { error?: { code?: string; message?: string } } | null;
    throw new ApiError(payload?.error?.message ?? "提问失败，请稍后重试。", payload?.error?.code);
  }
  if (!response.body) throw new ApiError("服务未返回可读取的回答流。");

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  const consume = (raw: string) => {
    const event = parseSseBlock(raw);
    if (!event) return;
    if (event.event === "error") throw new ApiError(event.data.message ?? "回答生成中断，请稍后重试。", event.data.code);
    onEvent(event);
  };

  while (true) {
    const { done, value } = await reader.read();
    buffer += decoder.decode(value, { stream: !done });
    const blocks = buffer.split(/\r?\n\r?\n/);
    buffer = blocks.pop() ?? "";
    blocks.forEach(consume);
    if (done) break;
  }
  if (buffer.trim()) consume(buffer);
}

export const knowTraceApi = {
  listWorkspaces: () => request<WorkspaceProject[]>("/api/v1/workspaces"),
  createWorkspace: (name: string) =>
    request<WorkspaceProject>("/api/v1/workspaces", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),
  deleteWorkspace: (workspaceId: string) =>
    request<void>(`/api/v1/workspaces/${workspaceId}`, { method: "DELETE" }),
  listDocuments: (workspaceId: string) => request<KnowledgeDocument[]>(`/api/v1/workspaces/${workspaceId}/documents`),
  listTasks: (workspaceId: string) => request<ProcessingTask[]>(`/api/v1/tasks/workspaces/${workspaceId}`),
  uploadDocument: (workspaceId: string, formData: FormData) =>
    request<DocumentUploadResponse>(`/api/v1/workspaces/${workspaceId}/documents`, { method: "POST", body: formData }),
  taskEvents: (taskId: string) => new EventSource(`/api/v1/tasks/${taskId}/events`),
  listConversations: (workspaceId: string) => request<Conversation[]>(`/api/v1/workspaces/${workspaceId}/conversations`),
  createConversation: (workspaceId: string, title: string) =>
    request<Conversation>(`/api/v1/workspaces/${workspaceId}/conversations`, {
      method: "POST",
      body: JSON.stringify({ title }),
    }),
  deleteConversation: (workspaceId: string, conversationId: string) =>
    request<void>(`/api/v1/workspaces/${workspaceId}/conversations/${conversationId}`, { method: "DELETE" }),
  listMessages: (workspaceId: string, conversationId: string) =>
    request<ConversationMessage[]>(`/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages`),
  streamRagAnswer,
};
