import { expect, test } from "@playwright/test";

import { api, dataOf, login, registerTenant, watchFailures } from "./support";

/** An admin sets up attendance from the Attendance settings page and gives a policy to a branch
 * from the policy's own screen, without a detour through Policy Assignments. */
test("assigns an attendance policy to a branch from the policy's own screen", async ({ page }) => {
  const problems = watchFailures(page);
  const tenant = await registerTenant("followers");
  const auth = { token: tenant.token, companyId: tenant.companyId };

  const entity = await api("/v1/legal-entities", { ...auth, body: { name: "Followers Entity" } });
  expect(entity.status).toBe(201);
  const branch = await api("/v1/branches", {
    ...auth,
    body: {
      legal_entity_id: dataOf<{ id: string }>(entity.body).id,
      name: "Pune Office",
      timezone: "Asia/Kolkata",
    },
  });
  expect(branch.status, JSON.stringify(branch.body)).toBe(201);
  const branchId = dataOf<{ id: string }>(branch.body).id;

  const policy = await api("/v1/attendance-policies", { ...auth, body: { name: "Office Hours" } });
  expect(policy.status).toBe(201);
  const policyId = dataOf<{ id: string }>(policy.body).id;
  const draft = await api(`/v1/attendance-policies/${policyId}/versions`, {
    ...auth,
    body: {
      effective_from: "2026-01-01",
      hour_bands: [{ min_minutes: 0, max_minutes: null, result_status: "PRESENT" }],
    },
  });
  expect(draft.status).toBe(201);
  const published = await api(
    `/v1/attendance-policies/${policyId}/versions/${dataOf<{ id: string }>(draft.body).id}/publish`,
    { ...auth, body: {}, ifMatch: "1" },
  );
  expect(published.status, JSON.stringify(published.body)).toBe(200);

  await login(page, tenant.email);
  await page.goto("/app/settings");
  await page.getByRole("link", { name: /^Attendance/ }).click();
  await expect(page).toHaveURL(/\/app\/settings\/attendance$/);
  await expect(page.getByRole("heading", { name: "Who follows which rules" })).toBeVisible();

  await page.getByRole("link", { name: /Attendance Policies/ }).click();
  await page.getByRole("link", { name: "Office Hours", exact: true }).click();
  await page.getByRole("tab", { name: "Who follows this" }).click();
  await expect(page.getByText("Nobody follows this policy yet")).toBeVisible();

  await page.getByRole("button", { name: /Add who follows it/ }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Who").selectOption("BRANCH");
  await dialog.getByLabel(/^Branch/).selectOption(branchId);
  await dialog.getByRole("button", { name: "Assign" }).click();

  await expect(page.getByRole("cell", { name: "Branch: Pune Office" })).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/app/attendance-policies/${policyId}`));

  const assignments = await api(
    `/v1/policy-assignments?policy_kind=ATTENDANCE_POLICY&policy_id=${policyId}`,
    auth,
  );
  expect(assignments.status).toBe(200);
  const rows = dataOf<Array<{ scope_type: string; scope_id: string }>>(assignments.body);
  expect(rows.map((r) => [r.scope_type, r.scope_id])).toEqual([["BRANCH", branchId]]);
  expect(problems).toEqual([]);
});
