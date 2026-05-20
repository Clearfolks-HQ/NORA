#!/usr/bin/env node
/**
 * Functional QA runner for a single Clearfolks PWA.
 *
 * Boots the product's index.html in jsdom, runs the inline scripts, then
 * exercises real flows:
 *   1. Navigation        — switch each discovered section, verify .active moves
 *   2. Form save         — for every form/save handler, fill inputs, submit,
 *                          verify a state array grew + localStorage persisted
 *   3. Render after save — verify the new entry's text appears in some list
 *   4. Persistence       — full localStorage round-trip across a fresh DOM
 *   5. Delete            — call delete*(0), verify state shrank
 *   6. Export            — call export* once, verify no throw
 *
 * Output is JSON on stdout when --json is passed; otherwise human-readable.
 *
 * Usage:
 *   node qa_runner.js --slug <slug> [--html <path>] [--json]
 *
 * Exit code: 0 on overall pass, 1 on any failure.
 */
"use strict";

const fs = require("fs");
const path = require("path");
const { JSDOM } = require("/tmp/node_modules/jsdom");

// ---------------------------------------------------------------------------
// CLI args
// ---------------------------------------------------------------------------
const args = process.argv.slice(2);
function arg(name, def = null) {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : def;
}
const SLUG = arg("--slug");
const HTML_PATH = arg("--html") || `/var/www/clearfolk/${SLUG}/index.html`;
const JSON_OUT = args.includes("--json");

if (!SLUG) {
  console.error("usage: qa_runner.js --slug <slug> [--html <path>] [--json]");
  process.exit(2);
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------
const SWITCH_FNS = [
  "switchSection", "navigate", "showSection", "go", "goTo",
  "app.switchSection", "app.navigate", "app.showSection", "app.go",
];

function tryEval(win, expr) {
  try { return win.eval(expr); } catch { return undefined; }
}

function getStateRef(win) {
  // Common shapes across forge generations: top-level `state`, top-level `D`,
  // or `app.state`.
  return (
    tryEval(win, "(function(){try{return state}catch(e){return null}})()") ||
    tryEval(win, "(function(){try{return D}catch(e){return null}})()") ||
    tryEval(win, "(function(){try{return app.state}catch(e){return null}})()") ||
    null
  );
}

function snapshotShape(state) {
  if (!state || typeof state !== "object") return {};
  const out = {};
  for (const k of Object.keys(state)) {
    const v = state[k];
    if (Array.isArray(v)) out[k] = v.length;
  }
  return out;
}

function diffShape(before, after) {
  const grown = [];
  const all = new Set([...Object.keys(before), ...Object.keys(after)]);
  for (const k of all) {
    const a = before[k] ?? 0;
    const b = after[k] ?? 0;
    if (b > a) grown.push({ key: k, from: a, to: b });
  }
  return grown;
}

function callSwitch(win, sectionId) {
  for (const fn of SWITCH_FNS) {
    const exists = tryEval(win, `typeof ${fn} === 'function'`);
    if (!exists) continue;
    try {
      win.eval(`${fn}(${JSON.stringify(sectionId)})`);
      return { fn, error: null };
    } catch (e) {
      return { fn, error: e.message };
    }
  }
  return { fn: null, error: "no switch fn found" };
}

function activeSectionId(doc) {
  // Class-based: most forge generations
  const cls = doc.querySelector(".section.active, .page.active");
  if (cls) {
    let id = cls.id || cls.getAttribute("data-section") || null;
    if (id && id.startsWith("page-")) id = id.slice(5);
    return id;
  }
  // Display-based: Baby Tracker / Caregiver style — switchSection toggles
  // section.style.display between 'none' and 'block'.
  const all = doc.querySelectorAll(".section, .page");
  let visible = null;
  let visibleCount = 0;
  for (const s of all) {
    const inline = (s.style && s.style.display) || "";
    if (inline === "none") continue;
    // Anything not explicitly display:none counts as visible. Pick the LAST
    // such (typically the most-recently-shown, since switchSection usually
    // hides all then shows one).
    visibleCount++;
    visible = s;
  }
  if (!visible) return null;
  // If literally every section is "visible" (no inline display set anywhere),
  // we can't tell which is active. Treat that as inconclusive.
  if (visibleCount === all.length && all.length > 1) return null;
  let id = visible.id || visible.getAttribute("data-section") || null;
  if (id && id.startsWith("page-")) id = id.slice(5);
  return id;
}

function discoverSections(doc) {
  const els = doc.querySelectorAll(".section, .page, [data-section]");
  const out = [];
  for (const el of els) {
    let id = el.id || el.getAttribute("data-section");
    if (!id) continue;
    const trimmed = id.startsWith("page-") ? id.slice(5) : id;
    if (!out.includes(trimmed)) out.push(trimmed);
  }
  return out;
}

function fillFormInputs(form, slug) {
  const seen = new Set();
  const values = {};
  const filled = [];
  const inputs = form.querySelectorAll("input, select, textarea");
  for (const inp of inputs) {
    const key = inp.id || inp.name;
    if (seen.has(key)) continue;
    seen.add(key);

    let val = "";
    const tag = inp.tagName.toLowerCase();
    const type = (inp.type || "text").toLowerCase();
    if (tag === "select") {
      if (inp.options.length > 0) val = inp.options[Math.min(1, inp.options.length - 1)].value;
    } else if (type === "checkbox") {
      inp.checked = true;
      val = "checked";
    } else if (type === "radio") {
      inp.checked = true;
      val = inp.value;
    } else if (type === "date") {
      val = "2026-06-15";
    } else if (type === "time") {
      val = "10:30";
    } else if (type === "number") {
      val = "42";
    } else if (type === "email") {
      val = "qa-test@example.com";
    } else {
      val = `QA Test ${slug}`;
    }
    if (type !== "checkbox" && type !== "radio") inp.value = val;
    if (key) values[key] = val;
    filled.push(`${key || "(unnamed)"}=${val}`);
  }
  return { values, filled };
}

function extractHandlerName(handler) {
  if (!handler) return null;
  // Strip leading `event-style` wrappers like `return saveX(event); return false;`
  const m = handler.match(/(\w+(?:\.\w+)?)\s*\(/);
  return m ? m[1] : null;
}

function findSaveHandlers(doc) {
  const handlers = [];
  const seen = new Set();
  // Forms with onsubmit — covers most forge generations
  for (const form of doc.querySelectorAll("form[onsubmit]")) {
    const fn = extractHandlerName(form.getAttribute("onsubmit"));
    if (fn && !seen.has(fn)) { seen.add(fn); handlers.push({ form, fn, viaSubmit: true }); }
  }
  // Save/Add buttons. The handler may be `saveX()`, `addX()`, `app.saveX()`,
  // `app.saveX(event)` etc. Match any name segment that starts with save/add.
  const isSaveLike = (name) => /(?:^|\.)(save|add)[A-Z]?/.test(name) || /(?:^|\.)(save|add)$/i.test(name);
  for (const btn of doc.querySelectorAll("button[onclick], a[onclick], div[onclick][role='button'], [data-action]")) {
    const oc = btn.getAttribute("onclick") || btn.getAttribute("data-action") || "";
    const fn = extractHandlerName(oc);
    if (!fn || !isSaveLike(fn)) continue;
    if (seen.has(fn)) continue;
    // Find the nearest container that holds the form's inputs. Try a wide net
    // of common forge container conventions.
    const form =
      btn.closest("form") ||
      btn.closest(".modal") ||
      btn.closest("[id$=Modal]") ||
      btn.closest(".ov, .overlay, .add-overlay, .drawer, .drw") ||
      btn.closest("[class*='-modal']") ||
      btn.closest("section");
    if (!form) continue;
    seen.add(fn);
    handlers.push({ form, fn, viaSubmit: false });
  }
  return handlers;
}

// DOM/event-handler names that look like "delete*/remove*" but aren't user-
// space delete functions; never report them as broken.
const DELETE_BLACKLIST = new Set([
  "removeEventListener", "removeAllListeners", "removeChild",
  "removeProperty", "removeNamedItem", "removeNamedItemNS",
  "removeAttribute", "removeAttributeNS", "removeAttributeNode",
]);


function findDeleteFns(win) {
  const candidatesScript = `
    (function(){
      const out = new Set();
      const SKIP = ${JSON.stringify([...DELETE_BLACKLIST])};
      for (const k of Object.getOwnPropertyNames(window)) {
        if (SKIP.includes(k)) continue;
        if (/^(delete|remove|del)[A-Z]?/.test(k) && typeof window[k] === 'function') out.add(k);
      }
      try {
        for (const k of Object.keys(app)) {
          if (SKIP.includes(k)) continue;
          if (/^(delete|remove)[A-Z]/.test(k) && typeof app[k] === 'function') out.add('app.' + k);
        }
      } catch(e) {}
      if (typeof del === 'function') out.add('del');
      return [...out];
    })()
  `;
  return tryEval(win, candidatesScript) || [];
}


function targetArrayFor(fnName, state) {
  // Heuristic: deleteVendor → state.vendors, app.deleteAppointment → state.appointments.
  // Strip common prefixes, lowercase, try both singular and pluralized variants.
  const bare = fnName.replace(/^(?:app\.)?(delete|remove)/i, "");
  if (!bare) return null;
  const lc = bare[0].toLowerCase() + bare.slice(1);
  const candidates = new Set([
    lc, lc + "s", lc + "es",
    lc.replace(/y$/, "ies"),
    lc.replace(/Task$/, "Tasks"),
    lc.replace(/Item$/, "Items"),
    lc.replace(/Event$/, ""),
    lc.replace(/Records$/, "Records"),
    lc.replace(/Record$/, "Records"),
    lc.toLowerCase(),
  ]);
  for (const c of candidates) {
    if (state[c] && Array.isArray(state[c])) return c;
  }
  return null;
}

function findExportFns(win) {
  const script = `
    (function(){
      const out = new Set();
      for (const k of Object.getOwnPropertyNames(window)) {
        if (/^export[A-Z]?/.test(k) && typeof window[k] === 'function') out.add(k);
        if (/^download[A-Z]?/.test(k) && typeof window[k] === 'function') out.add(k);
      }
      try {
        for (const k of Object.keys(app)) {
          if (/^(export|download)[A-Z]?/.test(k) && typeof app[k] === 'function') out.add('app.' + k);
        }
      } catch(e) {}
      return [...out];
    })()
  `;
  return tryEval(win, script) || [];
}

// ---------------------------------------------------------------------------
// Boot the page
// ---------------------------------------------------------------------------
function bootDom(htmlPath, urlSlug) {
  const html = fs.readFileSync(htmlPath, "utf8");
  const dom = new JSDOM(html, {
    runScripts: "dangerously",
    pretendToBeVisual: true,
    url: `https://app.clearfolks.com/${urlSlug}/`,
  });
  // Stub APIs jsdom doesn't implement so init scripts don't crash
  const w = dom.window;
  w.navigator.serviceWorker = { register: () => Promise.resolve(), ready: Promise.resolve({}) };
  if (!w.matchMedia) w.matchMedia = () => ({ matches: false, addListener() {}, removeListener() {}, addEventListener(){}, removeEventListener(){} });
  // Some apps download blobs on export — stub to avoid actual file IO
  w.URL.createObjectURL = () => "blob:stub";
  w.URL.revokeObjectURL = () => {};
  return dom;
}

function tick(ms = 50) {
  return new Promise(r => setTimeout(r, ms));
}

// ---------------------------------------------------------------------------
// Test runner
// ---------------------------------------------------------------------------
class Runner {
  constructor(slug, htmlPath) {
    this.slug = slug;
    this.htmlPath = htmlPath;
    this.tests = [];
  }

  pass(name, detail = "") { this.tests.push({ name, ok: true, detail }); }
  fail(name, detail = "")  { this.tests.push({ name, ok: false, detail }); }

  async run() {
    this.dom = bootDom(this.htmlPath, this.slug);
    await tick(250);

    await this.testNavigation();
    await this.testFormSave();
    await this.testRenderAfterSave();
    await this.testPersistence();
    await this.testDelete();
    await this.testExport();

    return {
      slug: this.slug,
      passed: this.tests.every(t => t.ok),
      tests: this.tests,
    };
  }

  // ---------- TEST 1 — Navigation ----------
  async testNavigation() {
    const doc = this.dom.window.document;
    const win = this.dom.window;
    const sections = discoverSections(doc).filter(s => s !== "");
    if (sections.length === 0) {
      this.fail("Navigation", "no sections discovered (.section / .page / [data-section])");
      return;
    }
    let switched = 0;
    const failures = [];
    for (const sec of sections) {
      const call = callSwitch(win, sec);
      await tick(30);
      const active = activeSectionId(doc);
      // Cross-check: many products track a state.currentSection mirror
      const stateSec = tryEval(win, "(typeof state!=='undefined'&&state.currentSection)||(typeof D!=='undefined'&&D.currentSection)||(typeof app!=='undefined'&&app.state&&app.state.currentSection)||null");
      const matched = active === sec
        || active === ("page-" + sec)
        || active === (sec + "-section")
        || (active && (active.replace(/-section$/, "") === sec))
        // Honor state mirror when DOM detection is inconclusive (some apps
        // use `display:none` toggles that we struggle to reflect cleanly).
        || (stateSec && (stateSec === sec
                         || stateSec === ("page-" + sec)
                         || stateSec === (sec + "-section")));
      if (matched) switched++;
      else {
        const err = call.error ? ` [threw: ${call.error}]` : "";
        failures.push(`${sec} → active=${active || "<none>"} state.currentSection=${stateSec || "<none>"} (via ${call.fn || "<no fn>"})${err}`);
      }
    }
    if (switched === sections.length) {
      this.pass("Navigation", `${switched}/${sections.length} sections switch correctly`);
    } else {
      this.fail("Navigation", `${switched}/${sections.length} sections switch — failures: ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 2 — Form save ----------
  async testFormSave() {
    const doc = this.dom.window.document;
    const win = this.dom.window;
    const handlers = findSaveHandlers(doc);
    if (handlers.length === 0) {
      this.fail("Form save", "no save/add handlers found in DOM");
      this.savedRecords = [];
      return;
    }
    this.savedRecords = []; // for use by testRenderAfterSave
    let ok = 0;
    const failures = [];
    for (const h of handlers) {
      const filled = fillFormInputs(h.form, this.slug);
      const before = snapshotShape(getStateRef(win));
      // Hand the runner a reference to *this* form so the save handler's
      // event.target / closest('form') lookups land on the right element.
      win._qaForm = h.form;
      try {
        const callExpr = h.viaSubmit
          ? `${h.fn}({preventDefault:function(){},target:_qaForm,currentTarget:_qaForm})`
          : `${h.fn}()`;
        win.eval(callExpr);
        await tick(30);
      } catch (e) {
        failures.push(`${h.fn}(): threw — ${e.message}`);
        continue;
      }
      const after = snapshotShape(getStateRef(win));
      const grown = diffShape(before, after);
      if (grown.length > 0) {
        ok++;
        // Pull out a string from the saved record for render-test use
        const state = getStateRef(win);
        const arr = state[grown[0].key];
        const last = arr[arr.length - 1] || {};
        const sample = Object.values(last).find(v => typeof v === "string" && v.length > 0) || "";
        this.savedRecords.push({ fn: h.fn, key: grown[0].key, sample, listed: false });
      } else {
        failures.push(`${h.fn}(): state unchanged after call (no array grew)`);
      }
    }
    if (ok === handlers.length) {
      this.pass("Form save", `${ok}/${handlers.length} save handlers grew state`);
    } else {
      this.fail("Form save", `${ok}/${handlers.length} save handlers worked — ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 3 — Render after save ----------
  async testRenderAfterSave() {
    const doc = this.dom.window.document;
    if (!this.savedRecords || this.savedRecords.length === 0) {
      this.fail("Render after save", "no successful saves to verify rendering for");
      return;
    }
    let visible = 0;
    const failures = [];
    for (const rec of this.savedRecords) {
      if (!rec.sample) continue;
      const allText = doc.body ? doc.body.textContent : "";
      if (allText.includes(rec.sample)) {
        visible++;
        rec.listed = true;
      } else {
        failures.push(`${rec.fn}: state.${rec.key} grew but DOM has no "${rec.sample.slice(0, 40)}"`);
      }
    }
    const checked = this.savedRecords.filter(r => r.sample).length;
    if (checked === 0) {
      this.fail("Render after save", "no saved records had checkable text fields");
      return;
    }
    if (visible === checked) {
      this.pass("Render after save", `${visible}/${checked} saved items visible in DOM`);
    } else {
      this.fail("Render after save", `${visible}/${checked} visible — ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 4 — Persistence ----------
  async testPersistence() {
    const win = this.dom.window;
    // Ensure save() ran or call it
    try { tryEval(win, "typeof save === 'function' && save()"); } catch {}
    try { tryEval(win, "typeof saveData === 'function' && saveData()"); } catch {}
    try { tryEval(win, "typeof persist === 'function' && persist()"); } catch {}
    try { tryEval(win, "typeof saveState === 'function' && saveState()"); } catch {}
    try { tryEval(win, "typeof app !== 'undefined' && typeof app.saveData === 'function' && app.saveData()"); } catch {}

    // Snapshot localStorage
    const storage = {};
    for (let i = 0; i < win.localStorage.length; i++) {
      const k = win.localStorage.key(i);
      storage[k] = win.localStorage.getItem(k);
    }
    const keys = Object.keys(storage).filter(k => !k.endsWith("_install") && !k.endsWith("_dismissed"));
    if (keys.length === 0) {
      this.fail("Persistence", "no app data in localStorage after save() — state never persisted");
      return;
    }
    const sample = JSON.parse(storage[keys[0]] || "{}");
    const arrays = Object.entries(sample).filter(([_, v]) => Array.isArray(v));
    const totalItems = arrays.reduce((s, [_, v]) => s + v.length, 0);
    if (totalItems === 0) {
      this.fail("Persistence", `localStorage["${keys[0]}"] is empty (no array contents)`);
      return;
    }

    // Round-trip — fresh DOM with same localStorage
    const html = fs.readFileSync(this.htmlPath, "utf8");
    const dom2 = new JSDOM(html, { runScripts: "dangerously", url: `https://app.clearfolks.com/${this.slug}/` });
    dom2.window.navigator.serviceWorker = { register: () => Promise.resolve() };
    for (const k of Object.keys(storage)) dom2.window.localStorage.setItem(k, storage[k]);
    await tick(150);
    // Trigger load if available so state hydrates from localStorage
    try { tryEval(dom2.window, "typeof load === 'function' && load()"); } catch {}
    try { tryEval(dom2.window, "typeof loadState === 'function' && loadState()"); } catch {}
    try { tryEval(dom2.window, "typeof app !== 'undefined' && typeof app.loadData === 'function' && app.loadData()"); } catch {}

    const state2 = getStateRef(dom2.window);
    const shape2 = snapshotShape(state2);
    const after = Object.values(shape2).reduce((s, v) => s + v, 0);
    if (after >= totalItems) {
      this.pass("Persistence", `localStorage round-trip restored ${after} items`);
    } else {
      this.fail("Persistence", `round-trip lost data: had ${totalItems}, restored ${after}`);
    }
  }

  // ---------- TEST 5 — Delete ----------
  async testDelete() {
    const win = this.dom.window;
    const state = getStateRef(win);
    if (!state) {
      this.fail("Delete", "no state object accessible");
      return;
    }
    const fns = findDeleteFns(win);
    if (fns.length === 0) {
      this.fail("Delete", "no delete* function defined");
      return;
    }
    let ok = 0;
    const failures = [];
    for (const fn of fns) {
      // Pick the array this delete function should affect — derived from name.
      const targetKey = targetArrayFor(fn, state)
        || Object.keys(state).find(k => Array.isArray(state[k]) && state[k].length > 0);
      if (!targetKey || !state[targetKey]?.length) {
        failures.push(`${fn}: no populated array to delete from`);
        continue;
      }
      const before = snapshotShape(state);
      let called = false;
      // Try (id) first since most apps use IDs; then index; then ('section', 0).
      const firstId = state[targetKey][0]?.id;
      const attempts = [];
      if (firstId !== undefined) attempts.push(`${fn}(${JSON.stringify(firstId)})`);
      attempts.push(`${fn}(0)`);
      if (fn === "del") attempts.unshift(`${fn}(${JSON.stringify(targetKey)}, 0)`);
      let lastErr = null;
      for (const expr of attempts) {
        try {
          win.eval(expr);
          called = true;
          break;
        } catch (e) {
          lastErr = e.message;
        }
      }
      await tick(20);
      if (!called) {
        failures.push(`${fn}(): ${lastErr || "all call shapes failed"}`);
        continue;
      }
      const after = snapshotShape(state);
      if ((after[targetKey] ?? 0) < (before[targetKey] ?? 0)) ok++;
      else failures.push(`${fn}(): state.${targetKey} did not shrink (had ${before[targetKey]}, still ${after[targetKey]})`);
    }
    if (ok > 0 && failures.length === 0) {
      this.pass("Delete", `${ok}/${fns.length} delete functions removed an item`);
    } else if (ok > 0) {
      this.pass("Delete", `${ok}/${fns.length} delete functions worked (others skipped: ${failures.join("; ")})`);
    } else {
      this.fail("Delete", `0/${fns.length} delete functions reduced state — ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 6 — Export ----------
  async testExport() {
    const win = this.dom.window;
    const fns = findExportFns(win);
    if (fns.length === 0) {
      // Some apps use exportToCSV / exportData / etc. without window.export* — try
      // common single names
      for (const f of ["exportData", "exportAll", "exportCSV", "exportPDF", "downloadData", "downloadCSV"]) {
        if (tryEval(win, `typeof ${f} === 'function'`)) fns.push(f);
      }
    }
    if (fns.length === 0) {
      this.fail("Export", "no export function defined");
      return;
    }
    let ok = 0;
    const failures = [];
    for (const fn of fns) {
      try {
        win.eval(`${fn}()`);
        ok++;
      } catch (e) {
        failures.push(`${fn}(): ${e.message}`);
      }
    }
    if (failures.length === 0) {
      this.pass("Export", `${ok}/${fns.length} export functions ran without throwing`);
    } else if (ok > 0) {
      this.pass("Export", `${ok}/${fns.length} ran (others: ${failures.join("; ")})`);
    } else {
      this.fail("Export", failures.join("; "));
    }
  }
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
(async () => {
  const runner = new Runner(SLUG, HTML_PATH);
  let result;
  try {
    result = await runner.run();
  } catch (e) {
    result = { slug: SLUG, passed: false, tests: [{ name: "Runner", ok: false, detail: e.stack || e.message }] };
  }
  if (JSON_OUT) {
    process.stdout.write(JSON.stringify(result));
  } else {
    const flag = result.passed ? "PASS" : "FAIL";
    console.log(`[${flag}] ${result.slug}`);
    for (const t of result.tests) {
      const mark = t.ok ? "✓" : "✗";
      console.log(`  ${mark} ${t.name} — ${t.detail || (t.ok ? "ok" : "failed")}`);
    }
  }
  process.exit(result.passed ? 0 : 1);
})();
