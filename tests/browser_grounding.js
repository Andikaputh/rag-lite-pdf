// Real local evidence-selection smoke; requires .tools/grounding-repair.pdf.
async (page) => {
  const assert = (value, message) => { if (!value) throw new Error(message); };
  const results = [];
  await page.context().clearCookies();
  for (const width of [1440, 375]) {
    await page.setViewportSize({ width, height: 1000 });
    await page.goto("http://127.0.0.1:8000/");
    await page.locator("#upload-button:not(:disabled)").waitFor();
    await page.locator("#pdf-input").setInputFiles(".tools/grounding-repair.pdf");
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
    const covered = await ask("Apakah kerusakan akibat air ditanggung garansi?");
    assert(covered.status === "answered" && covered.answer_mode === "extractive", "Negative fact was not answered extractively");
    assert(covered.claims.every((c, i) => c.text === covered.sources[i].quote), "Claim is not source text");
    assert((await page.locator("#answer-kind").textContent()).includes("EXTRACTIVE"), "Extractive mode hidden from user");
    const price = await ask("Berapa harga jual perangkat tersebut?");
    assert(price.status === "abstained" && price.reason === "no_relevant_evidence", "Absent price got unrelated evidence");
    assert(await page.locator("#answer-sources .source-card").count() === 0, "Absent fact has fake source");
    const conversion = await ask("Berapa tahun masa garansi perangkat yang tertulis dalam bulan?");
    assert(conversion.status === "answered" && conversion.answer_mode === "derived" && conversion.answer.includes("2.5"), "Exact source-based conversion missing");
    assert(await page.locator("#answer-output .derivation-proof").count() === 1, "Conversion proof hidden");
    const unsupported = await ask("Berapa hari masa garansi perangkat tanpa tanggal mulai?");
    assert(unsupported.status === "abstained" && unsupported.reason === "unsupported_calculation", "Calendar conversion guessed");
    assert((await page.locator("#answer-output [data-role=reason]").textContent()).includes("calculation"), "Abstention cause hidden");
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), `Grounding UI overflow at ${width}`);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: `.tools/grounding-${width}.png`, fullPage: true });
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    results.push({ width, negation: "pass", extractiveClaim: "pass", absentPrice: "pass", exactConversion: "pass", unsupportedCalendar: "pass", visibleReason: "pass" });
  }
  return { results };
}
