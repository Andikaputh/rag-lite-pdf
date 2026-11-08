// Run with: playwright-cli -s=folio-check run-code --filename=tests/browser_smoke.js
// Prerequisite: local server at http://127.0.0.1:8000 and .tools/ output directory.
async (page) => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  for (const width of [1440, 768, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/");
    await page.getByText("Web server online · Models checked on request", { exact: true }).waitFor({ state: "attached" });
    assert(await page.locator("#workspace-view").isVisible(), "Workspace not visible");
    await page.locator("#upload-button:not(:disabled)").waitFor();
    assert(await page.locator("#upload-button").isEnabled(), "Upload must be available after session initialization");
    assert(await page.locator("#question").isDisabled(), "Chat must remain disabled");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Horizontal overflow at ${width}px`);
    await page.screenshot({ path: `.tools/folio-${width}.png`, fullPage: true });
    await page.locator('nav [data-view="campaign"]').click();
    await page.locator("#campaign-view").waitFor({ state: "visible" });
    assert(!(await page.locator("#workspace-view").isVisible()), "Workspace still visible in campaign");
    assert(await page.locator(".checkpoint-card").count() === 8, "Expected eight checkpoints");
    assert(await page.locator(".checkpoint-done").count() === 8, "Expected all eight checkpoints cleared");
    assert((await page.locator("#quality-gate").textContent()).includes("has not passed production validation"), "Evaluation failures hidden from campaign");
    assert(await page.locator(".checkpoint-next").count() === 0, "Campaign finished: no next quest may remain");
    assert(await page.locator(".checkpoint-card").filter({ hasText: "Retrieval connected to local Ollama" }).count() === 1, "Campaign must target self-hosted Ollama");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Campaign overflow at ${width}px`);
    await page.screenshot({ path: `.tools/campaign-${width}.png`, fullPage: true });
    await page.goBack();
    await page.locator("#workspace-view").waitFor({ state: "visible" });
    results.push({ width, workspace: "pass", navigation: "pass", campaign: "pass", overflow: false });
  }
  await page.route("**/api/health", route => route.abort());
  await page.reload();
  await page.getByText("Server unreachable · Retrying automatically…", { exact: true }).waitFor({ state: "attached" });
  await page.unroute("**/api/health");
  await page.goto("http://127.0.0.1:8000/#campaign");
  await page.locator("#campaign-view").waitFor({ state: "visible" });
  assert(await page.title() === "Build campaign · Folio", "Deep-link title incorrect");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto("http://127.0.0.1:8000/");
  return { results, healthFailureState: "pass", campaignDeepLink: "pass" };
}
