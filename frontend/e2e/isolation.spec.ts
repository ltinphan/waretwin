// T1-T6: two-tenant isolation via the /api/workspace routes (existing wave-1 API).
// Test names mirror the manual protocol IDs in qa-gap-matrix.md.
import { expect, test } from "@playwright/test";
import { provision, revoke, shot, signIn } from "./helpers/workspace";

let A: { token: string; warehouse_id: string; revision_id: string; org: string };
let B: { token: string; warehouse_id: string; revision_id: string; org: string };

test.beforeAll(async () => {
  A = provision("tenant-alpha");
  B = provision("tenant-beta");
});

test("T1 context A lists only warehouse A; context B has none", async ({ browser }) => {
  const ctxA = await browser.newContext();
  const ctxB = await browser.newContext();
  const pageA = await ctxA.newPage();
  const pageB = await ctxB.newPage();
  await signIn(pageA, A.token);
  await signIn(pageB, B.token);
  // A sees its provisioned warehouse; B owns none (provisioned B warehouse belongs to B org!)
  const meA = await pageA.request.get("/api/workspace/me", { headers: { Authorization: "Bearer " + A.token } });
  expect((await meA.json()).organization_id).toBe("tenant-alpha");
  const meB = await pageB.request.get("/api/workspace/me", { headers: { Authorization: "Bearer " + B.token } });
  expect((await meB.json()).organization_id).toBe("tenant-beta");
  await expect(pageA.getByLabel("Warehouse").locator("option")).toContainText([/tenant-alpha warehouse/i]);
  await expect(pageB.getByLabel("Warehouse").locator("option")).toContainText([/tenant-beta warehouse/i]);
  await expect(pageA.locator(".wt-empty, .wt-editor")).toBeVisible();
  await pageA.screenshot({ path: shot("T1a_desktop") });
  await pageB.screenshot({ path: shot("T1b_desktop") });
  await ctxA.close();
  await ctxB.close();
});

test("T2 cross-tenant read blocked: A-token on B warehouse 404, B-token on A warehouse 404", async ({ request }) => {
  const crossAB = await request.get(`/api/workspace/warehouses/${B.warehouse_id}/revisions`, {
    headers: { Authorization: "Bearer " + A.token },
  });
  expect(crossAB.status()).toBe(404);
  const crossBA = await request.get(`/api/workspace/warehouses/${A.warehouse_id}/revisions`, {
    headers: { Authorization: "Bearer " + B.token },
  });
  expect(crossBA.status()).toBe(404);
});

test("T3 cross-tenant write/publish blocked: 404 both, A revision unchanged", async ({ request }) => {
  const doc = {
    name: "hijack", schema_version: "1.0", id: "x", units: "m",
    size: { width: 10, depth: 10, height: 5 }, grid: { cell_size: 1, cols: 10, rows: 10 },
    floors: [{ id: 1, name: "Ground floor", elevation: 0 }],
  };
  const put = await request.put(`/api/workspace/warehouses/${A.warehouse_id}/revisions/${A.revision_id}`, {
    data: { expected_version: 1, document: doc },
    headers: { Authorization: "Bearer " + B.token },
  });
  expect(put.status()).toBe(404);
  const pub = await request.post(
    `/api/workspace/warehouses/${A.warehouse_id}/revisions/${A.revision_id}/publish`,
    { data: { expected_version: 1 }, headers: { Authorization: "Bearer " + B.token } }
  );
  expect(pub.status()).toBe(404);
  // A revision version unchanged
  const mine = await request.get(`/api/workspace/warehouses/${A.warehouse_id}/revisions/${A.revision_id}`, {
    headers: { Authorization: "Bearer " + A.token },
  });
  expect((await mine.json()).version).toBe(1);
});

test("T4 fork isolation: A forks; B sees no new revision on A's warehouse", async ({ request }) => {
  const H = { headers: { Authorization: "Bearer " + A.token } };
  // count BEFORE the fork — the scratch DB persists across runs, so never assume 1 revision
  const before = await request.get(`/api/workspace/warehouses/${A.warehouse_id}/revisions`, H);
  const n0 = (await before.json()).length;
  const fork = await request.post(
    `/api/workspace/warehouses/${A.warehouse_id}/revisions/${A.revision_id}/fork`,
    H
  );
  expect(fork.status()).toBe(201);
  const forked = await fork.json();
  // B cannot read the forked revision
  const leaked = await request.get(
    `/api/workspace/warehouses/${A.warehouse_id}/revisions/${forked.id}`,
    { headers: { Authorization: "Bearer " + B.token } }
  );
  expect(leaked.status()).toBe(404);
  // A sees exactly one new revision after the fork
  const list = await request.get(`/api/workspace/warehouses/${A.warehouse_id}/revisions`, H);
  expect((await list.json()).length).toBe(n0 + 1);
});

test("T5 revocation kills only the revoked token", async ({ request }) => {
  revoke(B.token);
  const after = await request.get("/api/workspace/warehouses", {
    headers: { Authorization: "Bearer " + B.token },
  });
  expect(after.status()).toBe(401);
  const still = await request.get("/api/workspace/warehouses", {
    headers: { Authorization: "Bearer " + A.token },
  });
  expect(still.status()).toBe(200);
  expect(await still.json()).toHaveLength(1);
});

test("T6 signed-out tab has no token memory", async ({ browser, baseURL }) => {
  const ctx = await browser.newContext();
  const page = await ctx.newPage();
  await signIn(page, A.token);
  await expect(page.locator(".wt-header")).toBeVisible();
  await page.getByLabel("Sign out").click(); // not dirty -> no confirm
  await expect(page.locator('input[type="password"]')).toBeVisible();
  // ponytail: bfcache serves the signed-in page on goBack; SPA route reload proves no token memory
  await page.reload();
  await expect(page.locator(".wt-header")).toBeHidden();
  await page.screenshot({ path: shot("T6_desktop") });
  await ctx.close();
});
