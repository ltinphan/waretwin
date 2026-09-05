// C15/D1-D14: /workspace editor end-to-end, desktop + mobile viewports.
// Test names mirror the manual protocol IDs in qa-gap-matrix.md.
import { expect, test } from "@playwright/test";
import * as fs from "node:fs";
import { provision, shot, signIn } from "./helpers/workspace";

let provisioned: { token: string; warehouse_id: string; revision_id: string; org: string };

/** Create a warehouse via the dialog with EXPLICIT dimensions (defaults are 60x40x10). */
async function createWarehouse(page: import("@playwright/test").Page, name: string, width = 40, depth = 30, height = 8) {
  await page.getByLabel("New warehouse").click();
  const dialog = page.getByRole("dialog", { name: "New warehouse" });
  await dialog.getByLabel("Name").fill(name);
  const d = dialog.locator('input[type="number"]');
  await d.nth(0).fill(String(width));
  await d.nth(1).fill(String(depth));
  await d.nth(2).fill(String(height));
  await dialog.getByRole("button", { name: "Create warehouse" }).click();
  await expect(page.locator(".wt-plan-area")).toBeVisible();
}

test.beforeAll(async () => {
  provisioned = provision("qa-alpha");
});

test.beforeEach(async ({ page }) => {
  await signIn(page, provisioned.token);
});

test("D1-D2 sign-in gate renders and token sign-in loads workspace", async ({ page }) => {
  // D1: gate renders (fresh context shows login, not workspace data)
  const fresh = await page.context().browser()?.newContext();
  const p2 = await fresh!.newPage();
  await p2.goto("/workspace");
  await expect(p2.locator('input[type="password"]')).toBeVisible();
  await expect(p2.locator(".wt-header")).toBeHidden();
  await p2.close();
  await fresh!.close();
  // D2: already signed in in this context via beforeEach — workspace shell visible
  await expect(page.locator(".wt-header")).toBeVisible();
  await page.screenshot({ path: shot("D2_" + test.info().project.name) });
});

test("D3 create warehouse with dimensions", async ({ page }) => {
  await page.getByLabel("New warehouse").click();
  const dialog = page.getByRole("dialog", { name: "New warehouse" });
  await dialog.getByLabel("Name").fill("QA-Alpha");
  for (const [key, value] of [["width", 40], ["depth", 30], ["height", 8]] as const) {
    await dialog.getByLabel(key + " (m)", { exact: true }).fill(String(value));
  }
  await dialog.getByRole("button", { name: "Create warehouse" }).click();
  await expect(page.locator(".wt-plan-area")).toBeVisible();
  await expect(page.getByText("40 × 30 m")).toBeVisible();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await page.screenshot({ path: shot("D3_" + test.info().project.name) });
});

test("D4-D9 rack lifecycle: add, drag, rotate, duplicate, delete, undo/redo, save", async ({ page }) => {
  await createWarehouse(page, "QA-Lifecycle", 40, 30, 8);

  // D4 add rack — default 4x3 rack at (2,2), depth 1.2
  await page.getByRole("button", { name: "Add rack" }).click();
  const rackRect = page.locator("svg rect:has(title)");
  await expect(rackRect).toHaveCount(1);
  // mobile: shrink the plan so the whole floor fits the 375px viewport before dragging
  if (test.info().project.name === "mobile") {
    await page.getByLabel("Zoom out").click();
    await page.getByLabel("Zoom out").click();
  }
  const box = await rackRect.boundingBox();
  expect(box).not.toBeNull();
  await rackRect.scrollIntoViewIfNeeded(); // mobile: plan svg starts below the fold
  await page.screenshot({ path: shot("D4_" + test.info().project.name) });

  // D5 drag rack to (20,15): grab INSIDE the rack rect, move by (18,13) user units.
  // snap=0.5; pointer position math must match the svg viewBox actually rendered.
  const svg = page.locator("svg[role='img']");
  const svgBox = await svg.boundingBox();
  const vb = { x: -2, y: -2, w: 44, h: 34 }; // -2 -2 (40+4) (30+4)
  // svg uses preserveAspectRatio="meet": viewBox is uniformly scaled + centered, so
  // a per-axis scale (width vb.w, height vb.h) misplaces points. Use uniform scale + offsets.
  const vbScale = Math.min(svgBox!.width / vb.w, svgBox!.height / vb.h);
  const vbOx = svgBox!.x + (svgBox!.width - vb.w * vbScale) / 2;
  const vbOy = svgBox!.y + (svgBox!.height - vb.h * vbScale) / 2;
  const toScreen = (x: number, y: number) => ({
    x: vbOx + (x - vb.x) * vbScale,
    y: vbOy + (y - vb.y) * vbScale,
  });
  // rack rect box on screen: x=2,y=2,w=4,h=1.2 -> center (4, 2.6)
  const start = toScreen(4, 2.6);
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  for (let i = 1; i <= 10; i++) {
    const t = toScreen(4 + 18 * i / 10, 2.6 + 13 * i / 10);
    await page.mouse.move(t.x, t.y, { steps: 1 });
  }
  await page.mouse.up();
  const xInput = page.locator('.wt-properties:has-text("Selection") input[type="number"]').nth(0);
  await expect(xInput).toHaveValue("20");
  const zInput = page.locator('.wt-properties:has-text("Selection") input[type="number"]').nth(1);
  await expect(zInput).toHaveValue("15");
  await expect(page.getByRole("status")).toHaveText("Unsaved changes");
  await page.screenshot({ path: shot("D5_" + test.info().project.name) });

  // D6 rotate via the rotation input (last number input in Selection panel)
  const rotInput = page.locator('.wt-properties:has-text("Selection") input[type="number"]').nth(5);
  await rotInput.fill("90");
  await expect(page.locator("svg rect:has(title)").first()).toHaveAttribute("transform", /rotate\(90/);
  await page.screenshot({ path: shot("D6_" + test.info().project.name) });

  // D7 duplicate
  await page.getByLabel("Duplicate rack").click();
  await expect(page.locator(".wt-object-list button")).toHaveCount(2);
  await page.screenshot({ path: shot("D7_" + test.info().project.name) });

  // D8 undo/redo
  await page.getByLabel("Undo").click();
  await expect(page.locator(".wt-object-list button")).toHaveCount(1);
  await page.getByLabel("Redo").click();
  await expect(page.locator(".wt-object-list button")).toHaveCount(2);
  await page.getByLabel("Duplicate rack").click();
  await expect(page.locator(".wt-object-list button")).toHaveCount(3);
  await page.getByLabel("Undo").click();
  await expect(page.locator(".wt-object-list button")).toHaveCount(2);
  await page.getByLabel("Redo").click();
  await expect(page.locator(".wt-object-list button")).toHaveCount(3);
  await page.screenshot({ path: shot("D8_" + test.info().project.name) });

  // D9 save draft — v1 -> v2
  const rev = page.getByLabel("Revision");
  await expect(rev).toContainText("v1");
  await page.getByLabel("Save draft").click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  await expect(rev).toContainText("v2");
  await page.screenshot({ path: shot("D9_" + test.info().project.name) });
});

test("D10 publish: invalid 422 surfaces in UI, then fix and publish valid", async ({ page }) => {
  await createWarehouse(page, "QA-Publish");

  // Make the layout invalid: shrink building width to 2 while rack sits at x=2 (default rack is 4m wide)
  await page.getByRole("button", { name: "Add rack" }).click();
  await expect(page.locator(".wt-object-list button")).toHaveCount(1);
  const widthInput = page.locator('.wt-properties:has-text("Building") label:has-text("width") input');
  await widthInput.fill("2"); // rack (x=2..6) now outside the 2m building
  // "Check saved geometry" only validates SAVED revision — save first, then publish via API
  await page.getByLabel("Save draft").click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  const revisionId = await page.getByLabel("Revision", { exact: true }).inputValue();
  const warehouseId = await page.getByLabel("Warehouse", { exact: true }).inputValue();
  // Publish via API (no UI publish button — D10 protocol says use the API).
  const pub = await page.request.post(`/api/workspace/warehouses/${warehouseId}/revisions/${revisionId}/publish`, {
    data: { expected_version: 2 },
    headers: { Authorization: "Bearer " + provisioned.token },
  });
  expect(pub.status()).toBe(422);
  const issues = (await pub.json())["detail"]["issues"] as { path: string; code: string }[];
  expect(issues.length).toBeGreaterThan(0);
  // Now surface the 422 in the UI through the validation endpoint (Check saved geometry button)
  await page.getByLabel("Check saved geometry").click();
  await expect(page.locator(".wt-validation")).toBeVisible();
  await expect(page.locator(".wt-validation h2")).toContainText(/geometry issue/i);
  await page.screenshot({ path: shot("D10a_" + test.info().project.name) });

  // Fix: delete rack (select it from object list), save, validate clean, publish OK
  await page.locator(".wt-object-list button").first().click(); // select rack
  await page.getByLabel("Delete rack").click();
  await page.getByLabel("Save draft").click();
  await expect(page.getByRole("status")).toHaveText("Saved");
  const revisionId2 = await page.getByLabel("Revision", { exact: true }).inputValue();
  const pub2 = await page.request.post(`/api/workspace/warehouses/${warehouseId}/revisions/${revisionId2}/publish`, {
    data: { expected_version: 3 },
    headers: { Authorization: "Bearer " + provisioned.token },
  });
  expect(pub2.status()).toBe(201);
  await page.getByLabel("Check saved geometry").click();
  await expect(page.locator(".wt-validation h2")).toContainText(/passed/i);
  await page.screenshot({ path: shot("D10b_" + test.info().project.name) });
});

test("D12 fork alternative draft", async ({ page }) => {
  await createWarehouse(page, "QA-Fork");
  const revBefore = await page.getByLabel("Revision").inputValue();
  await page.getByLabel("Create alternative draft").click();
  const revSelect = page.getByLabel("Revision");
  await expect(revSelect.locator("option")).toHaveCount(2);
  const revAfter = await revSelect.inputValue();
  expect(revAfter).not.toBe(revBefore);
  // fork loads the new draft
  await expect(revSelect).toContainText("draft");
  await page.screenshot({ path: shot("D12_" + test.info().project.name) });
});

test("D13 export layout JSON", async ({ page }) => {
  await createWarehouse(page, "QA-Export");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    page.getByLabel("Export layout JSON").click(),
  ]);
  const p = await download.path();
  const doc = JSON.parse(fs.readFileSync(p!, "utf8"));
  expect(doc.size).toEqual({ width: 40, depth: 30, height: 8 });
  expect(doc.units).toBe("m");
  await page.screenshot({ path: shot("D13_" + test.info().project.name) });
});

test("D14 unsaved-changes guard on sign out", async ({ page }) => {
  await createWarehouse(page, "QA-Guard");
  // make a dirty edit: rotate? simpler — add rack (dirty) then sign out
  await page.getByRole("button", { name: "Add rack" }).click();
  await expect(page.getByRole("status")).toHaveText("Unsaved changes");
  page.once("dialog", (d) => d.dismiss()); // Cancel keeps edits
  await page.getByLabel("Sign out").click();
  await expect(page.locator(".wt-header")).toBeVisible(); // still in editor
  await page.screenshot({ path: shot("D14a_" + test.info().project.name) });
  page.once("dialog", (d) => d.accept()); // OK returns to login
  await page.getByLabel("Sign out").click();
  await expect(page.locator('input[type="password"]')).toBeVisible();
  await page.screenshot({ path: shot("D14b_" + test.info().project.name) });
});
