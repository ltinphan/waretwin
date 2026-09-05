// C6/V1: 3D demo route ("/") renders a non-blank canvas.
// Pixel check: >20 distinct colors in a 32x32 sample grid OR >5% of samples
// differ from the most common color. PNG decoded with playwright-core's
// bundled pngjs — no new dependency.
import { expect, test } from "@playwright/test";
import * as fs from "node:fs";
import { shot } from "./helpers/workspace";

import { PNG } from "playwright-core/lib/utilsBundle";

test("V1 3D demo canvas is non-blank", async ({ page }, testInfo) => {
  test.setTimeout(120_000); // R3F shader compile + screenshot can starve on a loaded host
  test.skip(testInfo.project.name === "mobile", "3D demo gate blocks narrow screens (NarrowScreenGate, width<1024)");
  await page.goto("/");
  const canvas = page.locator("canvas").first();
  await expect(canvas).toBeVisible();
  // R3F: give it time to compile shaders and render frames
  await page.waitForTimeout(3500);
  await page.screenshot({ path: shot("V1_" + testInfo.project.name), animations: "disabled", timeout: 30_000 });

  const buf = fs.readFileSync(shot("V1_" + testInfo.project.name));
  const png = PNG.sync.read(buf);
  const { width, height, data } = png;

  // 32x32 sample grid across the image
  const colors = new Set<string>();
  const counts = new Map<string, number>();
  const N = 32;
  let samples = 0;
  for (let gy = 0; gy < N; gy++) {
    for (let gx = 0; gx < N; gx++) {
      const x = Math.floor((gx + 0.5) * width / N);
      const y = Math.floor((gy + 0.5) * height / N);
      const i = (y * width + x) * 4;
      const a = data[i + 3];
      if (a === 0) continue;
      const key = data[i] + "," + data[i + 1] + "," + data[i + 2];
      colors.add(key);
      counts.set(key, (counts.get(key) ?? 0) + 1);
      samples++;
    }
  }
  expect(samples).toBeGreaterThan(0);
  const modal = Math.max(...counts.values());
  const modalShare = modal / samples;
  const distinct = colors.size;
  // pass if EITHER check holds (robust to solid-color scenes with gradients vs flat scenes)
  expect(
    distinct > 20 || modalShare < 0.95,
    `canvas looks blank: distinct=${distinct} modalShare=${modalShare.toFixed(3)}`
  ).toBeTruthy();
  // hard evidence numbers logged to artifacts
  fs.writeFileSync(
    import.meta.dirname + "/artifacts/V1_stats_" + testInfo.project.name + ".json",
    JSON.stringify({ width, height, distinct, modalShare, samples })
  );
});
