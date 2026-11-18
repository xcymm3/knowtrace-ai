import { expect, test } from "@playwright/test";

test("serves the standalone desk and checks local API origin", async ({ request }) => {
  const home = await request.get("/");
  expect(home.ok()).toBeTruthy();
  const body = await home.text();
  expect(body).toContain("新建会话");
  expect(body).toContain("完全访问");
  expect(body).not.toContain("新建知识库");
  expect((await request.get("/api/v1/agent/config")).ok()).toBeTruthy();
  expect((await request.get("/api/v1/workspaces")).status()).toBe(404);

  const crossOrigin = await request.post("/api/v1/agent/runs", {
    headers: { Origin: "https://example.test", "Sec-Fetch-Site": "cross-site" },
    data: {},
  });
  expect(crossOrigin.status()).toBe(403);
  const direct = await request.get("http://127.0.0.1:8000/api/v1/agent/threads");
  expect(direct.status()).toBe(403);
});
