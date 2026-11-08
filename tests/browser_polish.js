// Interaction acceptance: keyboard, visible loading, health retries, touch targets,
// honest copy. Requires local server and synthetic .tools/precision.pdf only.
// Run: playwright-cli -s=folio-check --raw run-code --filename=tests/browser_polish.js
async (page) => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  await page.setViewportSize({ width: 1440, height: 1000 });

  // 1. Error state: health check must auto-retry while offline, then recover.
  let healthHits = 0;
  await page.route("**/api/health", route => { healthHits += 1; route.fulfill({ status: 503, contentType: "application/json", body: "{}" }); });
  await page.goto("http://127.0.0.1:8000/?interaction-test=1");
  await page.getByText("Server unreachable · Retrying automatically…", { exact: true }).waitFor({ state: "attached" });
  const deadline = Date.now() + 14000;
  while (healthHits < 2 && Date.now() < deadline) await page.waitForTimeout(250);
  assert(healthHits >= 2, `Health check did not auto-retry (hits=${healthHits})`);
  await page.unroute("**/api/health");
  await page.getByText("Web server online · Models checked on request", { exact: true }).waitFor({ timeout: 15000 });
  results.push({ healthAutoRetry: "pass" });

  // 2. Keyboard: skip link is the first tab stop and jumps to main.
  await page.keyboard.press("Tab");
  const firstFocus = await page.evaluate(() => document.activeElement?.className || "");
  assert(firstFocus.includes("skip-link"), `First tab stop is not the skip link (${firstFocus})`);
  await page.keyboard.press("Enter");
  assert(await page.evaluate(() => location.hash) === "#main", "Skip link did not target main");
  results.push({ skipLink: "pass" });

  // 3. Upload + index (synthetic fixture) with a visible document-panel busy state.
  await page.locator("#upload-button:not(:disabled)").waitFor();
  await page.locator("#pdf-input").setInputFiles(".tools/precision.pdf");
  await page.locator("#document-feedback").filter({ hasText: "PDF validated" }).waitFor({ timeout: 60000 });
  await page.locator("#index-button:not(:disabled)").click();
  const busyRing = await page.evaluate(() => getComputedStyle(document.querySelector(".document-panel")).boxShadow);
  assert(busyRing !== "none", "Document panel has no visible busy indicator while indexing");
  await page.locator("#question:not(:disabled)").waitFor({ timeout: 130000 });
  results.push({ indexingBusyState: "pass" });

  // 4. Keyboard: Escape closes delete confirmation and returns focus.
  await page.locator("#delete-button").click();
  assert(await page.locator("#delete-confirmation").isVisible(), "Delete confirmation did not open");
  await page.keyboard.press("Escape");
  assert(!(await page.locator("#delete-confirmation").isVisible()), "Escape did not close delete confirmation");
  assert(await page.evaluate(() => document.activeElement?.id) === "delete-button", "Focus not returned to delete button");
  assert(await page.locator("#delete-button").getAttribute("aria-expanded") === "false", "Delete aria-expanded not reset");
  results.push({ escapeDelete: "pass" });

  // 5. Loading state: pending chat request is visibly busy, then returns to idle.
  await page.locator("#use-history").uncheck();
  let delayPost = false;
  let delayHistory = false;
  await page.route("**/api/chat", async route => {
    const method = route.request().method();
    if ((delayPost && method === "POST") || (delayHistory && method === "GET")) await new Promise(resolve => setTimeout(resolve, 2500));
    await route.continue();
  });
  delayPost = true;
  const idleBorder = await page.evaluate(() => getComputedStyle(document.querySelector(".composer")).borderTopColor);
  await page.locator("#question:not(:disabled)").fill("How many years is the device warranty?");
  await page.locator("#send-question").click();
  await page.waitForTimeout(700);
  const pending = await page.evaluate(() => ({
    ariaBusy: document.getElementById("chat-form").getAttribute("aria-busy"),
    sendText: document.getElementById("send-question").textContent,
    border: getComputedStyle(document.querySelector(".composer")).borderTopColor,
    feedback: document.getElementById("answer-feedback").textContent,
  }));
  assert(pending.ariaBusy === "true", "Chat form aria-busy not set while pending");
  assert(pending.sendText === "…", `Send button has no busy glyph (${pending.sendText})`);
  assert(pending.border !== idleBorder, "Composer border unchanged while pending");
  assert(pending.feedback.includes("Retrieving evidence"), "No visible loading message while pending");
  await page.locator("#question:not(:disabled)").waitFor({ timeout: 130000 });
  delayPost = false;
  assert(await page.evaluate(() => document.getElementById("send-question").textContent) === "↑", "Busy glyph not cleared after answer");
  assert(await page.evaluate(() => document.getElementById("chat-form").getAttribute("aria-busy")) === "false", "aria-busy not cleared after answer");
  results.push({ chatPendingVisual: "pass" });

  // 6. Loading state: history sync shows a loading label instead of a stale count.
  delayHistory = true;
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  let sawLoading = false;
  const syncDeadline = Date.now() + 2400;
  while (Date.now() < syncDeadline) {
    if ((await page.locator("#history-count").textContent()).includes("Loading")) { sawLoading = true; break; }
    await page.waitForTimeout(50);
  }
  assert(sawLoading, "History sync never showed its loading label");
  delayHistory = false;
  await page.locator("#history-count").filter({ hasText: "1/6" }).waitFor({ timeout: 15000 });
  results.push({ historyLoadingLabel: "pass" });

  // 7. Keyboard: Escape closes conversation reset confirmation and returns focus.
  await page.locator("#reset-conversation").click();
  assert(await page.locator("#conversation-reset-confirm").isVisible(), "Reset confirmation did not open");
  assert(await page.locator("#reset-conversation").getAttribute("aria-expanded") === "true", "Reset aria-expanded not true while open");
  await page.keyboard.press("Escape");
  assert(!(await page.locator("#conversation-reset-confirm").isVisible()), "Escape did not close reset confirmation");
  assert(await page.locator("#reset-conversation").getAttribute("aria-expanded") === "false", "Reset aria-expanded not reset");
  assert(await page.evaluate(() => document.activeElement?.id) === "reset-conversation", "Focus not returned to reset button");
  results.push({ escapeReset: "pass" });

  // 8. Source navigation: citation opens its source card and focuses the summary.
  await page.locator("#answer-output .citation-link").first().click();
  const citationFocus = await page.evaluate(() => ({
    tag: document.activeElement?.tagName,
    open: document.activeElement?.closest("details")?.open || false,
  }));
  assert(citationFocus.tag === "SUMMARY" && citationFocus.open, `Citation did not focus an opened source (${JSON.stringify(citationFocus)})`);
  results.push({ citationFocus: "pass" });

  // Quality warnings must remain visible; superseded figures must not reappear.
  const copy = await page.evaluate(() => ({
    banner: document.querySelector(".milestone-banner")?.textContent || "",
    intro: document.querySelector(".campaign-intro")?.textContent || "",
    gate: document.querySelector("#quality-gate")?.textContent || "",
    topbar: document.querySelector(".checkpoint-indicator")?.textContent || "",
    version: document.querySelector(".version-badge")?.textContent || "",
    footnote: document.querySelector(".campaign-footnote")?.textContent || "",
  }));
  const all = copy.banner + copy.intro + copy.gate + copy.topbar + copy.version + copy.footnote;
  assert(!/29\/30|19\/30|(?<!\d)4\/7|(?<!\d)6\/7|06\.1|BUILD 0\.6/.test(all), "Superseded evaluation copy reintroduced");
  assert(copy.gate.includes("has not passed production validation"), "Quality gate lost its honesty caveat");
  assert(copy.version.includes("0.8"), `Version badge not bumped (${copy.version})`);
  results.push({ honestCopy: "pass" });

  // 10. Mobile: touch targets and no horizontal overflow at 375/320.
  await page.setViewportSize({ width: 375, height: 900 });
  await page.waitForTimeout(300);
  const targets = await page.evaluate(() => {
    const pick = selector => { const r = document.querySelector(selector).getBoundingClientRect(); return { w: Math.round(r.width), h: Math.round(r.height) }; };
    return { send: pick("#send-question"), checkbox: pick("#use-history") };
  });
  assert(targets.send.w >= 44 && targets.send.h >= 44, `Send touch target too small at 375 (${JSON.stringify(targets.send)})`);
  assert(targets.checkbox.w >= 16 && targets.checkbox.h >= 16, `Checkbox too small at 375 (${JSON.stringify(targets.checkbox)})`);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Horizontal overflow at 375");
  await page.setViewportSize({ width: 320, height: 800 });
  await page.waitForTimeout(300);
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Horizontal overflow at 320");
  await page.screenshot({ path: ".tools/polish-375.png", fullPage: true });
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.waitForTimeout(300);
  await page.screenshot({ path: ".tools/polish-1440.png", fullPage: true });
  results.push({ mobileTouchTargets: "pass", overflow375: "pass", overflow320: "pass" });

  // Cleanup: leave no test document behind.
  await page.locator("#delete-button").click();
  await page.locator("#confirm-delete").click();
  await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();

  return { results };
}
