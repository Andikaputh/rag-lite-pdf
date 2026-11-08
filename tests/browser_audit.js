// Accessibility audit: axe-core (WCAG A/AA and best practices), computed
// contrast, focus visibility, and touch targets. Uses a synthetic PDF,
// deleted at the end of the run.
// Requires: server 127.0.0.1:8000, .tools/precision.pdf,
//           .tools/axe.min.js (install axe-core and copy axe.min.js to .tools/)
// Run: playwright-cli -s=folio-check --raw run-code --filename=tests/browser_audit.js
async (page) => {
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const results = [];
  const record = {};
  let step = "init";

  const axeFn = async () => {
    const res = await axe.run(document, {
      runOnly: { type: "tag", values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "best-practice"] },
    });
    const isWcag = v => (v.tags || []).some(t => t.startsWith("wcag"));
    return {
      version: axe.version,
      wcag: res.violations.filter(isWcag).map(v => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, target: (v.nodes[0] && v.nodes[0].target.join(" ")) || "" })),
      bestPractice: res.violations.filter(v => !isWcag(v)).map(v => ({ id: v.id, nodes: v.nodes.length, target: (v.nodes[0] && v.nodes[0].target.join(" ")) || "" })),
      incomplete: res.incomplete.map(v => ({ id: v.id, target: (v.nodes[0] && v.nodes[0].target.join(" ")) || "" })),
      passes: res.passes.length,
    };
  };

  const sweepFn = () => {
    const parse = c => {
      const m = (c || "").match(/rgba?\(([^)]+)\)/);
      if (!m) return null;
      const p = m[1].split(",").map(s => parseFloat(s));
      return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
    };
    const blend = (fg, bg) => ({ r: fg.r * fg.a + bg.r * (1 - fg.a), g: fg.g * fg.a + bg.g * (1 - fg.a), b: fg.b * fg.a + bg.b * (1 - fg.a), a: 1 });
    const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); const hi = Math.max(l1, l2), lo = Math.min(l1, l2); return (hi + 0.05) / (lo + 0.05); };
    const effBg = el => {
      const stack = [];
      const gradients = [];
      let nonGradient = false;
      let node = el;
      while (node) {
        const cs = getComputedStyle(node);
        if (cs.backgroundImage && cs.backgroundImage !== "none") {
          if (cs.backgroundImage.indexOf("gradient(") !== -1) gradients.push(cs.backgroundImage);
          else nonGradient = true;
        }
        const c = parse(cs.backgroundColor);
        if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break; }
        node = node.parentElement;
      }
      let base = { r: 255, g: 255, b: 255, a: 1 };
      for (let i = stack.length - 1; i >= 0; i--) base = blend(stack[i], base);
      return { color: base, gradients, nonGradient };
    };
    const sel = el => {
      if (el.id) return el.tagName.toLowerCase() + "#" + el.id;
      const parts = [];
      let node = el;
      while (node && node !== document.body && parts.length < 3) {
        let part = node.tagName.toLowerCase();
        if (node.classList.length) part += "." + Array.from(node.classList).slice(0, 2).join(".");
        parts.unshift(part);
        node = node.parentElement;
      }
      return parts.join(" > ");
    };
    const out = { checked: 0, failures: [], exempt: [], skipped: [], lowest: [] };
    for (const el of document.querySelectorAll("body *")) {
      const text = Array.from(el.childNodes).filter(n => n.nodeType === 3).map(n => n.textContent).join(" ").replace(/\s+/g, " ").trim();
      if (!text || !el.getClientRects().length) continue;
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none") continue;
      if (el.closest('[aria-hidden="true"]') || el.classList.contains("sr-only")) continue;
      out.checked++;
      const bgInfo = effBg(el);
      if (bgInfo.nonGradient) { out.skipped.push({ sel: sel(el), why: "background-image" }); continue; }
      let fg = parse(cs.color);
      if (fg.a < 1) fg = blend(fg, bgInfo.color);
      const size = parseFloat(cs.fontSize);
      const weight = parseInt(cs.fontWeight, 10) || 400;
      const need = (size >= 24 || (size >= 18.66 && weight >= 700)) ? 3 : 4.5;
      // Gradient backgrounds: measure against every parsed stop and keep the
      // worst ratio (conservative, since a stop's exact position under the
      // glyph is unknown).
      const candidates = [];
      if (bgInfo.gradients.length) {
        for (const g of bgInfo.gradients) {
          const cols = (g.match(/rgba?\([^)]+\)|#[0-9a-fA-F]{3,8}|\b(?:white|black)\b/gi) || [])
            .map(x => /^white$/i.test(x) ? { r: 255, g: 255, b: 255, a: 1 } : /^black$/i.test(x) ? { r: 0, g: 0, b: 0, a: 1 } : parse(x))
            .filter(Boolean);
          for (const c of cols) candidates.push(c.a < 1 ? blend(c, bgInfo.color) : c);
        }
      }
      if (!candidates.length) candidates.push(bgInfo.color);
      let r = Infinity;
      for (const bg of candidates) r = Math.min(r, ratio(fg, bg));
      const item = { sel: sel(el), ratio: Math.round(r * 100) / 100, need, size, text: text.slice(0, 44) };
      if (candidates.length > 1) item.via = "gradient-worst-stop";
      if (el.matches(":disabled") || el.closest(':disabled,[aria-disabled="true"]')) { out.exempt.push(Object.assign({ why: "disabled" }, item)); continue; }
      if (el.classList.contains("brand-dot") || el.closest(".brand")) { out.exempt.push(Object.assign({ why: "logotype" }, item)); continue; }
      if (r + 0.005 < need) out.failures.push(item);
      out.lowest.push(item);
    }
    for (const inp of document.querySelectorAll("input[placeholder],textarea[placeholder]")) {
      if (!inp.getClientRects().length) continue;
      const pc = parse(getComputedStyle(inp, "::placeholder").color);
      const bgInfo = effBg(inp);
      const fg = pc.a < 1 ? blend(pc, bgInfo.color) : pc;
      const r = ratio(fg, bgInfo.color);
      const item = { sel: sel(inp) + "::placeholder", ratio: Math.round(r * 100) / 100, need: 4.5 };
      if (r + 0.005 < 4.5) out.failures.push(item);
      out.lowest.push(Object.assign({ text: "(placeholder)" }, item));
    }
    out.lowest.sort((a, b) => a.ratio - b.ratio);
    out.lowest = out.lowest.slice(0, 8);
    return out;
  };

  const focusCollectFn = () => {
    const els = Array.from(document.querySelectorAll('a[href],button,input,summary,textarea,select,[tabindex]:not([tabindex="-1"])'))
      .filter(el => !el.disabled && el.getClientRects().length > 0);
    els.forEach((el, i) => el.setAttribute("data-audit-focus", String(i)));
    return els.length;
  };
  const focusReadFn = () => {
    const el = document.activeElement;
    if (!el || el === document.body || !el.hasAttribute("data-audit-focus")) return { end: true };
    const cs = getComputedStyle(el);
    const ow = parseFloat(cs.outlineWidth) || 0;
    return {
      idx: Number(el.getAttribute("data-audit-focus")),
      fv: el.matches(":focus-visible"),
      visible: cs.outlineStyle !== "none" && ow >= 2,
      outline: cs.outline,
      ring: cs.outlineColor,
      sel: el.id ? el.tagName.toLowerCase() + "#" + el.id : el.tagName.toLowerCase() + "." + Array.from(el.classList).slice(0, 2).join("."),
    };
  };

  const uiFn = (ringColor) => {
    const parse = c => { const m = (c || "").match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(",").map(s => parseFloat(s)); return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 }; };
    const lum = c => { const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const ratio = (a, b) => { const l1 = lum(a), l2 = lum(b); const hi = Math.max(l1, l2), lo = Math.min(l1, l2); return (hi + 0.05) / (lo + 0.05); };
    const effBg = el => { const stack = []; let node = el; while (node) { const c = parse(getComputedStyle(node).backgroundColor); if (c && c.a > 0) { stack.push(c); if (c.a >= 1) break; } node = node.parentElement; } let base = { r: 255, g: 255, b: 255, a: 1 }; for (let i = stack.length - 1; i >= 0; i--) { const s = stack[i]; base = { r: s.r * s.a + base.r * (1 - s.a), g: s.g * s.a + base.g * (1 - s.a), b: s.b * s.a + base.b * (1 - s.a), a: 1 }; } return base; };
    const round = x => Math.round(x * 100) / 100;
    const css = c => "rgb(" + Math.round(c.r) + "," + Math.round(c.g) + "," + Math.round(c.b) + ")";
    const items = [];
    const compare = (label, fgRaw, el) => {
      const fg = parse(fgRaw); if (!fg) return;
      const bg = effBg(el);
      items.push({ item: label, ratio: round(ratio(fg, bg)), fg: fgRaw, bg: css(bg) });
    };
    const composer = document.querySelector(".composer");
    if (composer) compare("composer border vs panel", getComputedStyle(composer).borderTopColor, composer.parentElement);
    const check = document.getElementById("use-history");
    if (check) compare("checkbox border vs panel", getComputedStyle(check).borderTopColor, check.parentElement);
    for (const [label, sel] of [["health status dot", ".server-status .status-dot"], ["local dot", ".local-dot"], ["checkpoint dot", ".checkpoint-indicator > span"]]) {
      const el = document.querySelector(sel);
      if (el) compare(label + " vs its bg", getComputedStyle(el).backgroundColor, el.parentElement);
    }
    // Ring color captured during the real Tab traversal above; bare focus()
    // does not reliably match :focus-visible in headless Chrome.
    if (ringColor) {
      const body = effBg(document.body);
      const fg = parse(ringColor);
      if (fg) items.push({ item: "focus ring vs page canvas", ratio: round(ratio(fg, body)), fg: ringColor, bg: css(body), from: "tab-traversal" });
    }
    return { items, need: 3 };
  };

  const touchFn = () => {
    const sel = el => (el.id ? el.tagName.toLowerCase() + "#" + el.id : el.tagName.toLowerCase() + "." + Array.from(el.classList).slice(0, 2).join("."));
    const els = Array.from(document.querySelectorAll('a[href],button,input,summary,textarea,select')).filter(el => !el.disabled && el.getClientRects().length > 0);
    const data = els.map(el => {
      const r = el.getBoundingClientRect();
      return { el, r, cx: r.left + r.width / 2, cy: r.top + r.height / 2, sel: sel(el) };
    });
    const distPointRect = (px, py, r) => {
      const dx = Math.max(r.left - px, 0, px - r.right);
      const dy = Math.max(r.top - py, 0, py - r.bottom);
      return Math.hypot(dx, dy);
    };
    const small = [];
    for (const t of data) {
      if (t.r.width >= 24 && t.r.height >= 24) continue;
      const inProse = t.el.tagName === "A" && !!t.el.closest("p,li,td,.answer-text,.page-description,.campaign-intro,.campaign-footnote,.privacy-note");
      // WCAG 2.2 2.5.8 spacing exception: a 24px circle centered on the target
      // must not intersect another target or that target's 24px circle.
      let obstructed = null;
      for (const o of data) {
        if (o === t) continue;
        const dRect = distPointRect(t.cx, t.cy, o.r);
        const dCenters = Math.hypot(t.cx - o.cx, t.cy - o.cy);
        if (dRect < 12 || dCenters < 24) {
          if (!obstructed || dRect < obstructed.dRect) obstructed = { sel: o.sel, dRect: Math.round(dRect), dCenters: Math.round(dCenters) };
        }
      }
      small.push({ sel: t.sel, w: Math.round(t.r.width), h: Math.round(t.r.height), inlineProse: inProse, spacingOk: obstructed === null, obstructedBy: obstructed });
    }
    return { total: data.length, small, hard: small.filter(s => !s.inlineProse && !s.spacingOk) };
  };

  const sweepSummary = s => ({ checked: s.checked, failures: s.failures, exempt: s.exempt, skipped: s.skipped, lowest: s.lowest });
  const assertAxe = (a, label) => assert(a.wcag.length === 0, `axe WCAG violations at ${label}: ${JSON.stringify(a.wcag)}`);
  const assertSweep = (s, label) => assert(s.failures.length === 0, `contrast failures at ${label}: ${JSON.stringify(s.failures.slice(0, 12))}`);

  try {
    await page.context().clearCookies();
    await page.setViewportSize({ width: 1440, height: 1000 });
    // Static CSS has no Cache-Control; heuristic caching would hide edits
    // from the audit. Disable the HTTP cache for this run.
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Network.setCacheDisabled", { cacheDisabled: true });

    step = "goto";
    await page.goto("http://127.0.0.1:8000/?qaaudit=1");
    await page.locator("#workspace-view").waitFor({ state: "visible" });
    await page.locator("#health-label").waitFor();
    await page.waitForTimeout(700);

    step = "inject-axe";
    // CSP script-src 'self' blocks addScriptTag; addInitScript runs via CDP.
    await page.addInitScript({ path: ".tools/axe.min.js" });
    await page.reload();
    await page.locator("#workspace-view").waitFor({ state: "visible" });
    await page.locator("#health-label").waitFor();
    await page.waitForTimeout(700);
    record.axeVersion = await page.evaluate(() => axe.version);

    step = "state-empty";
    const axeA = await page.evaluate(axeFn);
    assertAxe(axeA, "workspace-empty");
    const sweepA = await page.evaluate(sweepFn);
    assertSweep(sweepA, "workspace-empty");
    record.workspaceEmpty = { axe: axeA, sweep: sweepSummary(sweepA) };
    results.push({ axeEmpty: "pass", contrastEmpty: "pass" });

    step = "upload";
    await page.locator("#upload-button:not(:disabled)").waitFor();
    await page.locator("#pdf-input").setInputFiles(".tools/precision.pdf");
    await page.locator("#document-feedback").filter({ hasText: "PDF validated" }).waitFor({ timeout: 60000 });
    await page.locator("#index-button:not(:disabled)").click();
    await page.locator("#question:not(:disabled)").waitFor({ timeout: 130000 });

    step = "ask";
    await page.locator("#use-history").uncheck();
    await page.locator("#question:not(:disabled)").fill("How many years is the device warranty?");
    await page.locator("#send-question").click();
    await page.locator("#answer-output .citation-link").first().waitFor({ timeout: 130000 });
    await page.waitForTimeout(400);

    step = "state-full";
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: ".tools/audit-1440.png", fullPage: true });
    const axeB = await page.evaluate(axeFn);
    assertAxe(axeB, "workspace-full");
    const sweepB = await page.evaluate(sweepFn);
    assertSweep(sweepB, "workspace-full");
    // Real keyboard traversal: guarantees :focus-visible modality.
    const focusTotal = await page.evaluate(focusCollectFn);
    const focusSeen = new Set();
    const focusBad = [];
    let ringColor = null;
    let endStreak = 0;
    for (let i = 0; i < focusTotal + 4; i++) {
      await page.keyboard.press("Tab");
      const f = await page.evaluate(focusReadFn);
      if (f.end) { endStreak += 1; if (endStreak > 2) break; continue; }
      endStreak = 0;
      const revisited = focusSeen.has(f.idx);
      focusSeen.add(f.idx);
      if (!ringColor) ringColor = f.ring;
      if (!f.fv || !f.visible) focusBad.push({ sel: f.sel, focusVisible: f.fv, outline: f.outline });
      if (revisited && focusSeen.size >= focusTotal) break;
    }
    await page.evaluate(() => {
      document.querySelectorAll("[data-audit-focus]").forEach(el => el.removeAttribute("data-audit-focus"));
      if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    });
    const focusB = { total: focusTotal, coverage: focusSeen.size, bad: focusBad };
    assert(focusB.bad.length === 0 && focusB.coverage === focusB.total,
      `focus audit failed: ${JSON.stringify({ bad: focusBad.slice(0, 8), coverage: focusB.coverage, total: focusB.total })}`);
    const uiB = await page.evaluate(uiFn, ringColor);
    const uiFail = uiB.items.filter(i => i.ratio < uiB.need);
    assert(uiFail.length === 0, `UI component contrast below ${uiB.need}:1: ${JSON.stringify(uiFail)}`);
    record.workspaceFull = { axe: axeB, sweep: sweepSummary(sweepB), focus: focusB, uiContrast: uiB };
    results.push({ axeFull: "pass", contrastFull: "pass", focusVisibility: "pass", uiContrast: "pass" });

    step = "campaign-1440";
    await page.locator('nav [data-view="campaign"]').click();
    await page.locator("#campaign-view").waitFor({ state: "visible" });
    await page.waitForTimeout(400);
    const axeC = await page.evaluate(axeFn);
    assertAxe(axeC, "campaign-1440");
    const sweepC = await page.evaluate(sweepFn);
    assertSweep(sweepC, "campaign-1440");
    record.campaign1440 = { axe: axeC, sweep: sweepSummary(sweepC) };
    results.push({ axeCampaign1440: "pass", contrastCampaign1440: "pass" });

    step = "mobile-375";
    await page.setViewportSize({ width: 375, height: 900 });
    await page.waitForTimeout(400);
    const axeCM = await page.evaluate(axeFn);
    assertAxe(axeCM, "campaign-375");
    const sweepCM = await page.evaluate(sweepFn);
    assertSweep(sweepCM, "campaign-375");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: ".tools/audit-campaign-375.png", fullPage: true });
    await page.locator('nav [data-view="workspace"]').click();
    await page.locator("#workspace-view").waitFor({ state: "visible" });
    await page.waitForTimeout(400);
    const axeWM = await page.evaluate(axeFn);
    assertAxe(axeWM, "workspace-375");
    const sweepWM = await page.evaluate(sweepFn);
    assertSweep(sweepWM, "workspace-375");
    const touchM = await page.evaluate(touchFn);
    assert(touchM.hard.length === 0, `touch targets below 24px without WCAG 2.2 spacing/inline exception at 375: ${JSON.stringify(touchM.hard)}`);
    const overflow375 = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
    assert(overflow375, "horizontal overflow at 375");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: ".tools/audit-375.png", fullPage: true });
    await page.setViewportSize({ width: 320, height: 800 });
    await page.waitForTimeout(300);
    const overflow320 = await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth);
    assert(overflow320, "horizontal overflow at 320");
    record.mobile375 = { axeCampaign: axeCM, sweepCampaign: sweepSummary(sweepCM), axeWorkspace: axeWM, sweepWorkspace: sweepSummary(sweepWM), touch: touchM, overflow375, overflow320 };
    results.push({ axeCampaign375: "pass", contrastCampaign375: "pass", axeWorkspace375: "pass", contrastWorkspace375: "pass", touchTargets: "pass", overflow: "pass" });

    step = "cleanup";
    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.locator("#delete-button").click();
    await page.locator("#confirm-delete").click();
    await page.getByText("Document and extracted text deleted.", { exact: true }).waitFor();
    results.push({ cleanup: "pass" });

    return { results, record };
  } catch (error) {
    return { error: `audit failed at step ${step}: ${error.message}`, results, record };
  }
}
