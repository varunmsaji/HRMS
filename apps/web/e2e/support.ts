import { execFileSync } from "node:child_process";

import type { Page, Response } from "@playwright/test";

export const API = process.env.E2E_API_URL ?? "";
export const PASSWORD = "CorrectHorse9";

const stack = process.env.E2E_STACK ?? "";
const run = process.env.E2E_RUN_ID ?? "";

export function stackCmd(command: string, ...args: string[]): string {
  if (!stack || !run) throw new Error("E2E stack is not configured");
  return execFileSync(stack, [command, run, ...args], { encoding: "utf8" });
}

export interface Hashes {
  [table: string]: { count: number; md5: string };
}

export function rowHashes(companyId: string): Hashes {
  return JSON.parse(stackCmd("hash", companyId)) as Hashes;
}

export async function api(
  path: string,
  options: {
    method?: string;
    token: string;
    companyId: string;
    body?: unknown;
    ifMatch?: string;
    idempotencyKey?: string;
  },
): Promise<{ status: number; body: Record<string, unknown> }> {
  const headers: Record<string, string> = {
    Authorization: `Bearer ${options.token}`,
    "X-Company-Id": options.companyId,
    Accept: "application/json",
  };
  if (options.body !== undefined) headers["Content-Type"] = "application/json";
  if (options.ifMatch) headers["If-Match"] = options.ifMatch;
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;
  const response = await fetch(`${API}${path}`, {
    method: options.method ?? (options.body === undefined ? "GET" : "POST"),
    headers,
    body: options.body === undefined ? undefined : JSON.stringify(options.body),
  });
  const text = await response.text();
  const body = text ? (JSON.parse(text) as Record<string, unknown>) : {};
  return { status: response.status, body };
}

export function dataOf<T>(body: Record<string, unknown>): T {
  return body.data as T;
}

export async function registerTenant(label: string): Promise<{
  email: string;
  token: string;
  companyId: string;
}> {
  const email = `${label}-${Date.now()}-${Math.floor(Math.random() * 1000)}@example.com`;
  const response = await fetch(`${API}/v1/companies/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({
      name: `Browser Calendar ${label}`,
      country_code: "IN",
      currency: "INR",
      timezone: "Asia/Kolkata",
      admin_first_name: "Browser",
      admin_last_name: "Admin",
      admin_email: email,
      admin_password: PASSWORD,
    }),
  });
  if (response.status !== 201) {
    throw new Error(`Registration failed (${response.status}): ${await response.text()}`);
  }
  const payload = (await response.json()) as {
    data: { access_token: string; company_id: string };
  };
  const verified = stackCmd("verify-email", email);
  if (!verified.includes("verified_rows=1")) {
    throw new Error(`Email verification did not update a row: ${verified}`);
  }
  return { email, token: payload.data.access_token, companyId: payload.data.company_id };
}

export async function login(page: Page, email: string): Promise<void> {
  await page.goto("/login");
  await page.locator("#email").fill(email);
  await page.locator("#password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForURL(/\/app(\/|$)/);
}

export function watchFailures(page: Page): string[] {
  const problems: string[] = [];
  page.on("pageerror", (error) => {
    problems.push(`pageerror: ${error.message}`);
  });
  page.on("response", (response: Response) => {
    const status = response.status();
    if (status < 500) return;
    let pathname = response.url();
    try {
      pathname = new URL(response.url()).pathname;
    } catch {
      pathname = "unparsed";
    }
    problems.push(`http ${status} ${pathname}`);
  });
  return problems;
}

export async function createEmployeeWorld(
  token: string,
  companyId: string,
): Promise<{ employeeId: string; legalEntityId: string; leaveTypeId: string }> {
  const employee = await api("/v1/employees", {
    token,
    companyId,
    body: { first_name: "Asha" },
  });
  if (employee.status !== 201) throw new Error(`employee create ${employee.status}`);
  const employeeId = dataOf<{ id: string }>(employee.body).id;
  const entity = await api("/v1/legal-entities", {
    token,
    companyId,
    body: { name: "Browser Entity" },
  });
  if (entity.status !== 201) throw new Error(`legal entity ${entity.status}`);
  const legalEntityId = dataOf<{ id: string }>(entity.body).id;
  const employment = await api(`/v1/employees/${employeeId}/employments`, {
    token,
    companyId,
    body: { legal_entity_id: legalEntityId, joining_date: "2024-01-01" },
  });
  if (employment.status !== 201) throw new Error(`employment ${employment.status} ${JSON.stringify(employment.body)}`);
  const leaveType = await api("/v1/leave-types", {
    token,
    companyId,
    body: { code: "EL", name: "Earned Leave" },
  });
  if (leaveType.status !== 201) throw new Error(`leave type ${leaveType.status}`);
  const leaveTypeId = dataOf<{ id: string }>(leaveType.body).id;
  const policy = await api("/v1/leave-policies", {
    token,
    companyId,
    body: { name: "Standard EL Policy", leave_type_id: leaveTypeId },
  });
  if (policy.status !== 201) throw new Error(`leave policy ${policy.status}`);
  const policyId = dataOf<{ id: string }>(policy.body).id;
  const draft = await api(`/v1/leave-policies/${policyId}/versions`, {
    token,
    companyId,
    body: {
      effective_from: "2024-01-01",
      approval_chain: "AUTO",
      half_day_allowed: true,
      sandwich_rule_enabled: true,
      reason_required: false,
    },
  });
  if (draft.status !== 201) throw new Error(`leave version ${draft.status} ${JSON.stringify(draft.body)}`);
  const versionId = dataOf<{ id: string }>(draft.body).id;
  const published = await api(`/v1/leave-policies/${policyId}/versions/${versionId}/publish`, {
    method: "POST",
    token,
    companyId,
    ifMatch: "1",
    body: {},
  });
  if (published.status !== 200) throw new Error(`publish ${published.status} ${JSON.stringify(published.body)}`);
  const assignment = await api("/v1/policy-assignments", {
    token,
    companyId,
    body: {
      policy_kind: "LEAVE_POLICY",
      policy_id: policyId,
      leave_type_id: leaveTypeId,
      scope_type: "COMPANY",
      effective_from: "2024-01-01",
    },
  });
  if (assignment.status !== 201) {
    throw new Error(`leave assignment ${assignment.status} ${JSON.stringify(assignment.body)}`);
  }
  const balance = await api("/v1/leave-ledger/adjustments", {
    token,
    companyId,
    idempotencyKey: crypto.randomUUID(),
    body: {
      employee_id: employeeId,
      leave_type_id: leaveTypeId,
      amount: "20.00",
      effective_date: "2026-01-01",
      reason: "Opening balance for test",
    },
  });
  if (balance.status !== 201) throw new Error(`balance ${balance.status} ${JSON.stringify(balance.body)}`);
  return { employeeId, legalEntityId, leaveTypeId };
}

export async function submitLeave(
  token: string,
  companyId: string,
  employeeId: string,
  leaveTypeId: string,
  day: string,
): Promise<void> {
  const response = await api("/v1/leave-applications", {
    token,
    companyId,
    idempotencyKey: crypto.randomUUID(),
    body: {
      employee_id: employeeId,
      leave_type_id: leaveTypeId,
      start_date: day,
      end_date: day,
      reason: "private medical detail",
    },
  });
  if (response.status !== 201) {
    throw new Error(`leave submit ${day} ${response.status} ${JSON.stringify(response.body)}`);
  }
}
