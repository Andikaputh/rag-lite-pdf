// Opt-in local-model conversation smoke. Requires synthetic PDFs and Ollama.
async (page) => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/");
    await page.locator("#upload-button:not(:disabled)").waitFor();
    await page.locator("#pdf-input").setInputFiles(".tools/warranty.pdf");
    await page.locator("#index-button:not(:disabled)").click();
    await page.locator("#question:not(:disabled)").waitFor({ timeout: 130000 });
    await page.locator("#question").fill("Berapa lama masa garansi perangkat?");
    await page.locator("#send-question").click();
    await page.locator("#history-count").filter({ hasText: "1/6" }).waitFor({ timeout: 130000 });
    await page.locator("#question:not(:disabled)").fill("Bisa ulangi berapa bulan?");
    await page.locator("#send-question").click();
    await page.locator("#history-count").filter({ hasText: "2/6" }).waitFor({ timeout: 130000 });
    assert((await page.locator("#answer-text").textContent()).includes("24"), "Follow-up not answered from evidence");
    assert(await page.locator("#answer-output [data-role=resolved]").isVisible(), "Resolved question not shown");
    await page.reload();
    await page.locator("#question:not(:disabled)").waitFor();
    assert(await page.locator(".conversation-turn").count() === 2, "Reload lost conversation");
    await page.locator("#answer-output .citation-link").first().click();
    assert((await page.locator("#answer-output blockquote").first().textContent()).includes("24 bulan"), "Follow-up citation mismatch");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `History overflow at ${width}`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `.tools/conversation-${width}.png`, fullPage: true });
    await page.locator("#reset-conversation:not(:disabled)").click();
    await page.locator("#cancel-reset-conversation").click();
    assert(await page.locator(".conversation-turn").count() === 2, "Cancel reset cleared history");
    await page.locator("#reset-conversation").click();
    await page.locator("#confirm-reset-conversation").click();
    await page.locator("#history-count").filter({ hasText: "0/6" }).waitFor();
    await page.locator("#question:not(:disabled)").waitFor();
    assert(await page.locator("#index-status").textContent() === "Index ready", "Reset removed index");
    await page.locator("#use-history").uncheck();
    await page.locator("#question").fill("Berapa lama masa garansi perangkat?");
    await page.locator("#send-question").click();
    await page.locator("#history-count").filter({ hasText: "1/6" }).waitFor({ timeout: 130000 });
    assert(!(await page.locator("#answer-output [data-role=resolved]").isVisible()), "Opt-out used context");
    // Transport-only safety simulation: history text must never become HTML.
    const unsafe = await (await page.request.get("http://127.0.0.1:8000/api/chat")).json();
    unsafe.turns[0].response.claims[0].text = '<img src=x onerror="window.folioXss=1">';
    unsafe.turns[0].response.sources[0].quote = "<script>window.folioXss=1</script>";
    await page.route("**/api/chat", route => route.request().method() === "GET"
      ? route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(unsafe) }) : route.continue());
    await page.reload();
    await page.locator("#answer-text").filter({ hasText: "<img" }).waitFor();
    assert(await page.locator("#conversation-turns img, #conversation-turns script").count() === 0, "Unsafe history rendered as HTML");
    assert(await page.evaluate(() => window.folioXss === undefined), "Unsafe history executed");
    await page.unroute("**/api/chat");
    await page.locator("#pdf-input").setInputFiles(".tools/valid.pdf");
    await page.locator("#history-count").filter({ hasText: "0/6" }).waitFor();
    assert(await page.locator(".conversation-turn").count() === 0, "Replacement retained old conversation");
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    results.push({ width, followup: "pass", reload: "pass", citation: "pass", resetAndCancel: "pass", contextOptOut: "pass", safeHistoryText: "pass", replacementIsolation: "pass" });
  }
  return { results };
}
