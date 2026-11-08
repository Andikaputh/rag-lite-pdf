// Real local policy-v3 smoke. Requires synthetic .tools/precision.pdf.
async (page) => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/");
    await page.locator("#upload-button:not(:disabled)").waitFor();
    await page.locator("#pdf-input").setInputFiles(".tools/precision.pdf");
    await page.locator("#index-button:not(:disabled)").click();
    await page.locator("#question:not(:disabled)").waitFor({ timeout: 130000 });
    await page.locator("#use-history").uncheck();
    async function ask(question) {
      await page.locator("#question:not(:disabled)").fill(question);
      const [response] = await Promise.all([
        page.waitForResponse(r => r.url().endsWith("/api/chat") && r.request().method() === "POST", { timeout: 130000 }),
        page.locator("#send-question").click(),
      ]);
      const data = await response.json();
      await page.locator("#question:not(:disabled)").waitFor();
      return data;
    }
    const converted = await ask("How many years is the device warranty?");
    assert(converted.status === "answered" && converted.answer_mode === "derived", "Missing derived answer");
    assert(converted.answer.includes("2.25 years"), "Wrong exact conversion");
    assert(converted.sources[0].quote.includes("27 months"), "Cited input is wrong");
    assert(converted.claims[0].derivation.rule === "exact_duration_ratio_v1", "Missing auditable rule");
    assert(await page.locator("#answer-output .derivation-proof").isVisible(), "Calculation not shown");
    await page.locator("#answer-output .citation-link").click();
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `.tools/precision-${width}.png`, fullPage: true });
    const focus = await ask("For how many days are readings stored?");
    assert(focus.status === "answered" && focus.answer.includes("28"), "Retention answer wrong");
    assert(!/calibration|6 days/i.test(focus.answer), "Off-topic evidence retained");
    await page.locator("#use-history").check();
    const original = "Could you repeat how long those readings are stored?";
    const followup = await ask(original);
    assert(followup.status === "answered" && followup.used_history, "Follow-up failed");
    assert(followup.resolved_question.startsWith(original), "Original English question changed");
    assert(!/calibration|6 days/i.test(followup.answer), "Follow-up evidence off-topic");
    await page.locator("#use-history").uncheck();
    const unsupported = await ask("Exactly how many days is the warranty without a start date?");
    assert(unsupported.status === "abstained" && unsupported.reason === "unsupported_calculation", "Ambiguous calendar math guessed");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Precision UI overflow at ${width}`);
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    results.push({ width, exactConversion: "pass", inputCitation: "pass", proofVisible: "pass", focus: "pass", languagePrefix: "pass", calendarRefusal: "pass" });
  }
  return { results };
}
