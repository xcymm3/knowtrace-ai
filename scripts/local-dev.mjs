import { spawn } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repo = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const apiPort = "8000";
const webPort = "3001";
const address = "127.0.0.1";
const children = new Set();
let stopping = false;

function stop(code) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  for (const child of children) {
    if (child.pid && process.platform === "win32") {
      spawn("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], {
        windowsHide: true,
        stdio: "ignore",
      }).on("error", () => child.kill());
    } else {
      child.kill("SIGTERM");
    }
  }
}

function start(command, args, cwd, extraEnv) {
  const child = spawn(command, args, { cwd, env: { ...process.env, ...extraEnv }, stdio: "inherit" });
  children.add(child);
  child.once("error", (error) => {
    children.delete(child);
    console.error(error.message);
    stop(1);
  });
  child.once("exit", (code) => {
    children.delete(child);
    stop(code ?? 0);
  });
}

process.once("SIGINT", () => stop(0));
process.once("SIGTERM", () => stop(0));

start("uv", [
  "run", "--locked", "python", "-m", "uvicorn", "app.main:app", "--host", address, "--port", apiPort,
], join(repo, "backend"), {
  TASK_EXECUTION_MODE: "inline",
  LOCAL_AGENT_ROOT: resolve(process.env.LOCAL_AGENT_ROOT || repo),
});
start(process.execPath, [
  join(repo, "node_modules", "next", "dist", "bin", "next"), "dev",
  "--hostname", address, "--port", webPort,
], repo, {
  API_PROXY_TARGET: `http://${address}:${apiPort}`,
  KNOWTRACE_LOCAL_WEB: "1",
});
console.log(`KnowTrace 本地工作台 http://${address}:${webPort}`);
