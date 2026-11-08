// Generate synthetic fixtures with tests.pdf_fixtures; run against localhost:8000.
async (page) => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/");
    await page.locator("#upload-button:not(:disabled)").waitFor();
    await page.locator("#pdf-input").setInputFiles({
      name: "invalid.pdf", mimeType: "application/pdf", buffer: Buffer.from("not a PDF"),
    });
    await page.locator("#document-feedback.is-error").filter({ hasText: "not a valid PDF" }).waitFor();
    assert(await page.locator("#document-count").textContent() === "0", "Rejected file became active");
    await page.locator("#pdf-input").setInputFiles(".tools/valid.pdf");
    await page.locator("#document-details").waitFor({ state: "visible" });
    assert(await page.locator("#document-name").textContent() === "valid.pdf", "Wrong filename");
    assert(await page.locator("#document-pages").textContent() === "2", "Wrong page count");
    assert(await page.locator("#question").isDisabled(), "Validated is not RAG ready");
    assert(await page.locator("#document-warning").isVisible(), "Partial empty-page warning missing");
    await page.reload();
    await page.locator("#document-details").waitFor({ state: "visible" });
    await page.locator("#pdf-input").setInputFiles(".tools/blank.pdf");
    await page.locator("#document-feedback.is-error").filter({ hasText: "OCR" }).waitFor();
    assert(await page.locator("#document-name").textContent() === "valid.pdf", "Failed replacement did not retain old document");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Overflow at ${width}`);
    await page.screenshot({ path: `.tools/document-${width}.png`, fullPage: true });
    await page.locator("#delete-button").click();
    await page.locator("#cancel-delete").click();
    assert(await page.locator("#document-details").isVisible(), "Cancelled deletion removed document");
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    assert(await page.locator("#document-count").textContent() === "0", "Delete left document active");
    results.push({ width, upload: "pass", reload: "pass", invalidReplacement: "pass", deletion: "pass" });
  }
  await page.route("**/api/documents", route => route.abort());
  await page.reload();
  await page.locator("#session-retry").waitFor({ state: "visible" });
  assert(await page.locator("#upload-button").isDisabled(), "Disconnected upload not disabled");
  await page.unroute("**/api/documents");
  await page.locator("#session-retry").click();
  await page.locator("#upload-button:not(:disabled)").waitFor();
  return { results, sessionFailureAndRetry: "pass" };
}
