import { spawn } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..", "..");
const dataDir = fs.mkdtempSync(path.join(os.tmpdir(), "it-e2e-"));
const port = process.env.E2E_PORT || "8765";
const python =
  process.platform === "win32"
    ? fs.existsSync(path.join(repoRoot, "venv", "Scripts", "python.exe"))
      ? path.join(repoRoot, "venv", "Scripts", "python.exe")
      : "python"
    : fs.existsSync(path.join(repoRoot, "venv", "bin", "python3"))
      ? path.join(repoRoot, "venv", "bin", "python3")
      : "python3";
const claude =
  process.platform === "win32"
    ? path.join(repoRoot, "tests", "e2e", "fixtures", "fake_claude.cmd")
    : path.join(repoRoot, "tests", "e2e", "fixtures", "fake_claude");

const child = spawn(
  python,
  [path.join(repoRoot, "tests", "e2e_server.py"), "--port", port],
  {
    cwd: repoRoot,
    env: {
      ...process.env,
      INTERVIEW_TRACKER_E2E_DATA_DIR: dataDir,
      CLAUDE_BIN: claude,
      E2E_PORT: port,
      PYTHONPATH: path.join(repoRoot, "bin"),
    },
    stdio: "inherit",
  },
);

const shutdown = () => {
  child.kill("SIGTERM");
  fs.rmSync(dataDir, { recursive: true, force: true });
};

process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
process.on("exit", shutdown);

child.on("exit", (code) => process.exit(code ?? 0));
