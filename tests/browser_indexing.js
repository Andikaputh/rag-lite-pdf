// Explicit local-model browser smoke. Requires bge-m3 installed and .tools/valid.pdf.
async (page) => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/");
    await page.locator("#upload-button:not(:disabled)").waitFor();
    await page.locator("#pdf-input").setInputFiles(".tools/valid.pdf");
    await page.locator("#document-details").waitFor({ state: "visible" });
    await page.route("**/api/documents/index", route => route.fulfill({
      status: 503, contentType: "application/json",
      body: JSON.stringify({ error: { code: "embedding_unavailable", message: "Local Ollama unavailable (test simulation)." } }),
    }));
    await page.locator("#index-button").click();
    await page.locator("#document-feedback.is-error").filter({ hasText: "Local Ollama unavailable" }).waitFor();
    assert(await page.locator("#index-status").textContent() !== "Index ready", "Failure falsely marked ready");
    await page.unroute("**/api/documents/index");
    await page.locator("#index-button:not(:disabled)").click();
    await page.locator('#index-status[data-state="ready"]').waitFor({ timeout: 130000 });
    assert((await page.locator("#index-summary").textContent()).includes("1024 dimensions"), "Wrong embedding dimensions");
    await page.locator("#question:not(:disabled)").waitFor();
    await page.reload();
    await page.locator('#index-status[data-state="ready"]').waitFor();
    await page.locator("#index-button:not(:disabled)").click();
    await page.getByText("Saved index reused without recomputing embeddings.", { exact: true }).waitFor();
    await page.locator("#pdf-input").setInputFiles(".tools/valid.pdf");
    await page.getByText("PDF validated. Build its local index before asking questions.", { exact: true }).waitFor();
    assert(await page.locator("#index-status").textContent() === "Index ready", "Identical reupload lost index");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Index layout overflow at ${width}`);
    await page.screenshot({ path: `.tools/index-ready-${width}.png`, fullPage: true });
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    await page.locator("#pdf-input").setInputFiles(".tools/valid.pdf");
    await page.locator("#document-details").waitFor({ state: "visible" });
    assert(await page.locator("#index-status").textContent() === "Not indexed", "Deleted index was resurrected");
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    results.push({ width, modelFailure: "pass", realLocalIndex: "pass", reload: "pass", reuse: "pass", identicalReupload: "pass", deleteReset: "pass" });
  }
  return { results, model: "bge-m3:latest", chatEnabledAfterIndex: true };
}
