import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";

export default async function globalSetup(): Promise<void> {
  const api = process.env.E2E_API_URL;
  const web = process.env.E2E_WEB_URL;
  const run = process.env.E2E_RUN_ID;
  const artifacts = process.env.E2E_ARTIFACTS;
  const stack = process.env.E2E_STACK;
  if (!api || !web || !run || !artifacts || !stack) {
    throw new Error(
      "Browser tests need the disposable stack. Run docs/testing/qa_harness/browser_stack.sh " +
        "(up, prove, migrate, serve, e2e). Refusing to start without E2E_API_URL, E2E_WEB_URL, " +
        "E2E_RUN_ID, E2E_ARTIFACTS and E2E_STACK.",
    );
  }
  if (!run.startsWith("browser-")) {
    throw new Error(`E2E_RUN_ID ${run} is not a browser stack run`);
  }
  const proofPath = path.join(artifacts, "isolation.json");
  const proof = JSON.parse(readFileSync(proofPath, "utf8")) as {
    all_ok?: boolean;
    run?: string;
    database?: string;
    database_port?: number;
    shared_dev_database?: boolean;
  };
  if (proof.all_ok !== true || proof.run !== run || proof.shared_dev_database !== false) {
    throw new Error("Isolation proof is missing or failed. Run browser_stack.sh prove before the tests.");
  }
  if (!proof.database?.startsWith("hrms_browser_") || proof.database.includes("hrms_dev")) {
    throw new Error(`Isolation proof names database ${proof.database}`);
  }
  if (proof.database_port !== 15433) {
    throw new Error(`Isolation proof uses port ${proof.database_port}, not the disposable port`);
  }
  execFileSync(stack, ["prove", run], { stdio: "inherit" });

  const ready = await fetch(`${api}/health/ready`);
  if (!ready.ok) {
    throw new Error(`API readiness returned ${ready.status}. The disposable API is not available.`);
  }
  const body = (await ready.json()) as { data?: { ready?: boolean; database?: string } };
  if (body.data?.ready !== true || body.data.database !== "ok") {
    throw new Error("API is up but its database check is not ok.");
  }
  const login = await fetch(web + "/login");
  if (!login.ok) {
    throw new Error(`Web login page returned ${login.status}. The disposable web app is not available.`);
  }
}
