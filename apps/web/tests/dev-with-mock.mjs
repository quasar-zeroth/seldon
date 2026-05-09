import { spawn } from "node:child_process";
import { createMockApiServer } from "./mock-api.mjs";

const apiPort = Number(process.env.MOCK_SELDON_API_PORT || 43111);
const webPort = Number(process.env.PLAYWRIGHT_WEB_PORT || 3100);
const api = createMockApiServer();

await new Promise((resolve) => api.listen(apiPort, "127.0.0.1", resolve));
console.log(`Mock Seldon API listening on ${apiPort}`);

const nextBin = process.platform === "win32" ? "next.cmd" : "next";
const next = spawn(nextBin, ["dev", "-p", String(webPort), "-H", "127.0.0.1"], {
  stdio: "inherit",
  shell: process.platform === "win32",
  env: {
    ...process.env,
    NEXT_PUBLIC_SELDON_API_URL: `http://127.0.0.1:${apiPort}`,
    SELDON_API_KEY: "",
    NEXT_PUBLIC_SELDON_API_KEY: "",
  },
});

function shutdown(signal) {
  next.kill(signal);
  api.close(() => process.exit(0));
}
process.on("SIGTERM", () => shutdown("SIGTERM"));
process.on("SIGINT", () => shutdown("SIGINT"));
next.on("exit", (code) => {
  api.close(() => process.exit(code ?? 0));
});
