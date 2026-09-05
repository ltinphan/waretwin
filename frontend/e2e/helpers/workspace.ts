// Shared helpers for the workspace e2e specs.
import { execSync } from "node:child_process";
import { expect } from "@playwright/test";
import * as path from "node:path";

const REPO = path.resolve(import.meta.dirname, "../../..");
const PY = path.join(REPO, "backend/.venv311/bin/python");
const PROVISION = path.join(REPO, "frontend/e2e/helpers/provision.py");

export interface Provisioned {
  token: string;
  warehouse_id: string;
  revision_id: string;
  org: string;
}

/** Provision org + token + warehouse via backend venv python. */
export function provision(org: string): Provisioned {
  const out = execSync(`"${PY}" "${PROVISION}" --org ${JSON.stringify(org)}`).toString();
  return JSON.parse(out) as Provisioned;
}

/** Revoke a token (isolation spec T5). */
export function revoke(token: string): void {
  execSync(`"${PY}" "${PROVISION}" --revoke ${JSON.stringify(token)}`);
}

export const shot = (name: string) => path.join(import.meta.dirname, "..", "artifacts", name + ".png");

/** Sign in with a provisioned token; asserts the workspace shell loads. */
export async function signIn(page: import("@playwright/test").Page, token: string) {
  await page.goto("/workspace");
  const input = page.locator('input[type="password"]');
  await expect(input).toBeVisible();
  await input.fill(token);
  await expect(input).toHaveValue(token); // fill() can race React controlled input re-render
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.locator(".wt-header")).toBeVisible();
}
