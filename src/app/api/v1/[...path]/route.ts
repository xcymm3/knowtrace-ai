import { NextRequest } from "next/server";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

function apiTarget() {
  return (
    process.env.API_PROXY_TARGET ??
    process.env.NEXT_PUBLIC_API_BASE_URL ??
    "http://localhost:8000"
  ).replace(/\/$/, "");
}

async function proxyToApi(request: NextRequest, { params }: RouteContext) {
  const { path } = await params;
  const target = new URL(
    `${apiTarget()}/api/v1/${path.map((segment) => encodeURIComponent(segment)).join("/")}`,
  );
  target.search = request.nextUrl.search;

  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("transfer-encoding");
  headers.delete("expect");

  try {
    const response = await fetch(target, {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : await request.arrayBuffer(),
      cache: "no-store",
      redirect: "manual",
    });

    const responseHeaders = new Headers(response.headers);
    responseHeaders.delete("content-encoding");
    responseHeaders.delete("transfer-encoding");
    return new Response(response.body, { status: response.status, headers: responseHeaders });
  } catch (error) {
    console.error("FastAPI proxy request failed", { method: request.method, target: target.toString(), error });
    return Response.json(
      {
        error: {
          code: "API_UNAVAILABLE",
          message: "本机 FastAPI 服务不可用，请确认 Docker Compose 已启动。",
        },
      },
      { status: 502 },
    );
  }
}

export const GET = proxyToApi;
export const POST = proxyToApi;
export const PATCH = proxyToApi;
export const DELETE = proxyToApi;
