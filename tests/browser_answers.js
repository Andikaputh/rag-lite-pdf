// Opt-in real local RAG smoke. Requires .tools/warranty.pdf and both Ollama models.
async (page) => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/");
    await page.locator("#upload-button:not(:disabled)").waitFor();
    assert(await page.locator("#question").isDisabled(), "Question enabled without index");
    await page.locator("#pdf-input").setInputFiles(".tools/warranty.pdf");
    await page.locator("#index-button:not(:disabled)").click();
    await page.locator("#question:not(:disabled)").waitFor({ timeout: 130000 });
    await page.route("**/api/chat", route => route.fulfill({ status: 503, contentType: "application/json",
      body: JSON.stringify({ error: { message: "Local answer model unavailable (test simulation)." } }) }));
    await page.locator("#question").fill("Berapa lama masa garansi perangkat?");
    await page.locator("#send-question").click();
    await page.locator("#answer-feedback.is-error").filter({ hasText: "unavailable" }).waitFor();
    assert(!(await page.locator("#answer-output").isVisible()), "Error displayed as successful answer");
    await page.unroute("**/api/chat");
    await page.locator("#send-question:not(:disabled)").click();
    await page.locator("#answer-output").waitFor({ state: "visible", timeout: 130000 });
    assert((await page.locator("#answer-text").textContent()).includes("24"), "Wrong warranty answer");
    await page.locator(".citation-link").first().click();
    assert((await page.locator(".source-card blockquote").first().textContent()).includes("24 bulan"), "Citation not supported by fixture");
    assert((await page.locator(".source-card summary").first().textContent()).includes("Page 1"), "Page missing");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Answer overflow at ${width}`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `.tools/answer-${width}.png`, fullPage: true });
    await page.locator("#use-history").uncheck();
    await page.locator("#question:not(:disabled)").fill("Siapa juara Piala Dunia sepak bola tahun 2022?");
    await page.locator("#send-question").click();
    await page.locator("#answer-kind").filter({ hasText: "INSUFFICIENT EVIDENCE" }).waitFor({ timeout: 130000 });
    assert(await page.locator("#answer-sources .source-card").count() === 0, "Abstention retained old sources as current evidence");
    await page.reload();
    await page.locator("#question:not(:disabled)").waitFor();
    assert(await page.locator(".conversation-turn").count() === 2, "History did not restore after reload");
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    assert(await page.locator("#question").isDisabled(), "Deleted document left question enabled");
    results.push({ width, realAnswer: "pass", sourceQuote: "pass", abstention: "pass", modelError: "pass", reloadHistory: "pass", deleteReset: "pass" });
  }
  return { results, model: "qwen2.5:1.5b-instruct" };
}
