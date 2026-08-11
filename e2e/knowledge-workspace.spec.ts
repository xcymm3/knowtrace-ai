import { expect, test, type Page, type Route } from "@playwright/test";

const workspaceId = "11111111-1111-4111-8111-111111111111";
const documentId = "22222222-2222-4222-8222-222222222222";
const conversationId = "33333333-3333-4333-8333-333333333333";
const historicalConversationId = "44444444-4444-4444-8444-444444444444";

const workspace = {
  id: workspaceId,
  name: "测试知识库",
  description: null,
  status: "ACTIVE",
  created_at: "2026-08-10T00:00:00Z",
  updated_at: "2026-08-10T00:00:00Z",
};

async function fulfillJson(route: Route, payload: unknown, status = 200) {
  await route.fulfill({ status, contentType: "application/json", body: JSON.stringify(payload) });
}

async function seedE2ESession(page: Page) {
  await page.addInitScript(() => {
    localStorage.setItem("knowtrace-e2e-session", "signed-in");
  });
}

async function mockWorkspaceApi(page: Page) {
  let createdWorkspace = false;
  let uploaded = false;
  let answered = false;
  let conversationCreated = false;
  let conversationDeleted = false;
  let createdConversationTitle = "";

  await page.route("**/api/v1/**", async (route) => {
    const request = route.request();
    const { pathname } = new URL(request.url());
    const method = request.method();

    if (pathname === "/api/v1/workspaces" && method === "GET") {
      return fulfillJson(route, createdWorkspace ? [workspace] : []);
    }
    if (pathname === "/api/v1/workspaces" && method === "POST") {
      createdWorkspace = true;
      return fulfillJson(route, workspace, 201);
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/documents` && method === "GET") {
      return fulfillJson(route, uploaded ? [{
        id: documentId,
        workspace_id: workspaceId,
        kind: "GENERAL",
        file_name: "meeting.txt",
        mime_type: "text/plain",
        size_bytes: 48,
        status: "READY",
        error_message: null,
        metadata: {},
        created_at: "2026-08-10T00:00:00Z",
        updated_at: "2026-08-10T00:00:00Z",
      }] : []);
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/documents` && method === "POST") {
      uploaded = true;
      return fulfillJson(route, {
        id: documentId,
        workspace_id: workspaceId,
        kind: "GENERAL",
        file_name: "meeting.txt",
        status: "PENDING",
        task_id: "55555555-5555-4555-8555-555555555555",
        task_status: "QUEUED",
      }, 201);
    }
    if (pathname === `/api/v1/tasks/workspaces/${workspaceId}` && method === "GET") {
      return fulfillJson(route, []);
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/conversations` && method === "GET") {
      return fulfillJson(route, [
        ...(conversationCreated && !conversationDeleted ? [{
          id: conversationId,
          workspace_id: workspaceId,
          title: createdConversationTitle,
          created_at: "2026-08-10T00:00:00Z",
          updated_at: "2026-08-10T00:00:00Z",
        }] : []),
        {
          id: historicalConversationId,
          workspace_id: workspaceId,
          title: "历史对话",
          created_at: "2026-08-09T00:00:00Z",
          updated_at: "2026-08-09T00:00:00Z",
        },
      ]);
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/conversations` && method === "POST") {
      conversationCreated = true;
      createdConversationTitle = (request.postDataJSON() as { title: string }).title;
      return fulfillJson(route, {
        id: conversationId,
        workspace_id: workspaceId,
        title: createdConversationTitle,
        created_at: "2026-08-10T00:00:00Z",
        updated_at: "2026-08-10T00:00:00Z",
      }, 201);
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/conversations/${historicalConversationId}/messages` && method === "GET") {
      return fulfillJson(route, []);
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages` && method === "GET") {
      return fulfillJson(route, answered ? [
        {
          id: "88888888-8888-4888-8888-888888888888",
          conversation_id: conversationId,
          role: "USER",
          content: "会议结论是什么？",
          sequence: 0,
          created_at: "2026-08-10T00:00:00Z",
          sources: [],
        },
        {
          id: "77777777-7777-4777-8777-777777777777",
          conversation_id: conversationId,
          role: "ASSISTANT",
          content: "会议决定继续推进，由张三负责验证。",
          sequence: 1,
          created_at: "2026-08-10T00:00:01Z",
          sources: [{
            chunk_id: "66666666-6666-4666-8666-666666666666",
            citation: {
              document_id: documentId,
              file_name: "meeting.txt",
              kind: "GENERAL",
              chunk_index: 0,
              start_char: 0,
              end_char: 30,
            },
            excerpt: "会议决定继续推进，并由张三负责验证。",
            score: 0.91,
          }],
        },
      ] : []);
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}/messages/stream` && method === "POST") {
      answered = true;
      const body = [
        `event: retrieval\ndata: ${JSON.stringify({ conversation_id: conversationId, sources: [{ chunk_id: "66666666-6666-4666-8666-666666666666", citation: { document_id: documentId, file_name: "meeting.txt", kind: "GENERAL", chunk_index: 0, start_char: 0, end_char: 30 }, excerpt: "会议决定继续推进，并由张三负责验证。", score: 0.91 }] })}\n\n`,
        `event: token\ndata: ${JSON.stringify({ delta: "会议决定继续推进，" })}\n\n`,
        `event: token\ndata: ${JSON.stringify({ delta: "由张三负责验证。" })}\n\n`,
        `event: complete\ndata: ${JSON.stringify({ message: { id: "77777777-7777-4777-8777-777777777777", conversation_id: conversationId, role: "ASSISTANT", content: "会议决定继续推进，由张三负责验证。", sequence: 1, created_at: "2026-08-10T00:00:01Z" }, sources: [{ chunk_id: "66666666-6666-4666-8666-666666666666", citation: { document_id: documentId, file_name: "meeting.txt", kind: "GENERAL", chunk_index: 0, start_char: 0, end_char: 30 }, excerpt: "会议决定继续推进，并由张三负责验证。", score: 0.91 }] })}\n\n`,
      ].join("");
      return route.fulfill({ status: 200, contentType: "text/event-stream", body });
    }
    if (pathname === `/api/v1/workspaces/${workspaceId}/conversations/${conversationId}` && method === "DELETE") {
      conversationDeleted = true;
      return route.fulfill({ status: 204 });
    }
    return fulfillJson(route, { error: { code: "UNEXPECTED_E2E_REQUEST", message: pathname } }, 500);
  });
}

test("用户可创建知识库、上传已索引资料、获得带引用回答并删除对话", async ({ page }) => {
  await seedE2ESession(page);
  await mockWorkspaceApi(page);

  await page.goto("/");
  await expect(page.getByText("当前用户：")).toBeVisible();
  await expect(page.getByText("e2e-user")).toBeVisible();

  await page.getByPlaceholder("新建知识库").fill("测试知识库");
  await page.getByRole("button", { name: "新建", exact: true }).click();
  await expect(page.getByRole("heading", { name: "测试知识库" })).toBeVisible();
  await expect(page.getByText("历史对话", { exact: true })).toBeVisible();

  await page.locator('input[type="file"]').setInputFiles({
    name: "meeting.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("会议决定继续推进，并由张三负责验证。"),
  });
  await page.getByRole("button", { name: "上传并解析" }).click();
  await expect(page.getByText("meeting.txt", { exact: true })).toBeVisible();
  await expect(page.getByText("1 KB · 已索引", { exact: true })).toBeVisible();

  await expect(page.locator("#message")).toBeEnabled();
  await page.getByRole("button", { name: "新建对话" }).click();
  await page.getByPlaceholder("输入对话名称").fill("会议讨论");
  await page.getByRole("button", { name: "创建", exact: true }).click();
  await expect(page.getByText("会议讨论", { exact: true })).toBeVisible();
  await page.locator("#message").fill("会议结论是什么？");
  await page.getByRole("button", { name: "发送问题" }).click();
  await expect(page.getByText("会议决定继续推进，由张三负责验证。")).toBeVisible();
  await expect(page.getByText("本次引用 1 个资料片段")).toBeVisible();

  await page.getByRole("button", { name: "删除对话 会议讨论" }).click();
  await expect(page.getByRole("alertdialog")).toBeVisible();
  await page.getByRole("button", { name: "确认删除" }).click();
  await expect(page.getByText("对话“会议讨论”已删除。")).toBeVisible();
});

test("注册页展示用户名、确认密码与非阻断式密码强度反馈", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("button", { name: "没有账号？创建一个" }).click();

  await expect(page.getByLabel("用户名")).toBeVisible();
  await expect(page.getByLabel("确认密码")).toBeVisible();
  await page.locator("#password").fill("123");
  await expect(page.getByText("密码强度：")).toBeVisible();
});
