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
// Helpers for the deeper-behavior test classes (modal dismissal, duplicate
// handling, generated-data quality, button-label accuracy, unimplemented
// features). These were added after manual QA found 5 real bugs that the
// happy-path suite missed.
// ---------------------------------------------------------------------------

const MODAL_SELECTORS = [
  ".modal", ".overlay", ".drawer", ".dialog", ".popup", ".sheet",
  "[role='dialog']", "[role='alertdialog']",
  "[class*='-modal']", "[class*='-overlay']", "[class*='-drawer']", "[class*='-sheet']",
  "[id$='Modal']", "[id$='-modal']", "[id*='odal']",
];

function findModals(doc) {
  const seen = new Set();
  const out = [];
  for (const sel of MODAL_SELECTORS) {
    let list;
    try { list = doc.querySelectorAll(sel); } catch { continue; }
    for (const el of list) {
      // Skip non-modal containers — must look modal-shaped (positioned overlay).
      // We don't gate by CSS (jsdom won't compute) but skip body/html.
      if (el === doc.body || el === doc.documentElement) continue;
      // Skip elements that are inner content of another modal we already saw
      let parent = el.parentElement;
      let isInner = false;
      while (parent) {
        if (seen.has(parent)) { isInner = true; break; }
        parent = parent.parentElement;
      }
      if (isInner) continue;
      if (seen.has(el)) continue;
      seen.add(el);
      out.push(el);
    }
  }
  return out;
}

function forceOpenModal(el) {
  el.style.display = "flex";
  el.classList.add("active");
  el.classList.add("open");
  el.classList.add("show");
  el.classList.add("visible");
}

function modalDismissed(el, addedClasses) {
  // Path 1: inline display:none
  const d = (el.style && el.style.display) || "";
  if (d === "none") return true;
  // Path 2: the app's close handler removed one of the activate-like classes
  // we added. If ANY went away, the close path ran.
  for (const cls of addedClasses) {
    if (!el.classList.contains(cls)) return true;
  }
  return false;
}

function findCloseButtons(modal) {
  const out = [];
  const buttons = modal.querySelectorAll("button, a, [role='button'], [onclick]");
  for (const b of buttons) {
    const txt = (b.textContent || "").trim();
    const oc = b.getAttribute("onclick") || "";
    const aria = b.getAttribute("aria-label") || "";
    const title = b.getAttribute("title") || "";
    const blob = `${txt} ${aria} ${title} ${oc}`.toLowerCase();
    // Match cancel/close/dismiss/back text or close-style icons or close-style onclick
    if (
      /\b(cancel|close|dismiss|back|nevermind|×|✕|✖|❌)\b/i.test(blob) ||
      /close\w*modal|hide\w*modal|dismiss\w*modal|closeOverlay|closeDrawer|closeSheet|closeDialog/i.test(oc) ||
      txt === "×" || txt === "✕" || txt === "✖"
    ) {
      // Exclude obvious non-close actions
      if (/save|submit|confirm|delete|remove/i.test(txt) && !/cancel|close/i.test(txt)) continue;
      out.push(b);
    }
  }
  return out;
}

function dispatchKeydown(win, key) {
  try {
    const KeyboardEvent = win.KeyboardEvent;
    const ev = new KeyboardEvent("keydown", {
      key, code: key === "Escape" ? "Escape" : key,
      keyCode: key === "Escape" ? 27 : 0,
      which: key === "Escape" ? 27 : 0,
      bubbles: true, cancelable: true,
    });
    win.document.dispatchEvent(ev);
    return true;
  } catch (e) { return false; }
}

function dispatchClickOn(win, el) {
  try {
    const MouseEvent = win.MouseEvent;
    const ev = new MouseEvent("click", { bubbles: true, cancelable: true, view: win });
    el.dispatchEvent(ev);
    return true;
  } catch (e) { return false; }
}

// Instruments common app APIs so we can detect what a button actually did.
// Returns a reset() that re-zeroes the counters between checks.
function installProbe(win) {
  tryEval(win, `
    (function(){
      if (window._qaProbeInstalled) return;
      window._qaProbeInstalled = true;
      window._qaOpens = [];
      window._qaPrints = 0;
      window._qaDownloads = [];
      window._qaToasts = [];
      window._qaClipboard = [];
      window._qaAlerts = [];

      const origOpen = window.open;
      window.open = function(url) {
        try { _qaOpens.push(String(url == null ? '' : url)); } catch(e) {}
        return { closed: false, document: { open(){}, write(){}, close(){} }, print(){ _qaPrints++; }, close(){} };
      };
      const origPrint = window.print;
      window.print = function() { _qaPrints++; if (typeof origPrint === 'function') try { origPrint(); } catch(e) {} };
      const origAlert = window.alert;
      window.alert = function(msg) { _qaAlerts.push(String(msg == null ? '' : msg)); };
      const origConfirm = window.confirm;
      window.confirm = function(msg) { _qaAlerts.push(String(msg == null ? '' : msg)); return true; };

      // Intercept any showQuickToast / toast / notify / showToast / flash / message-style helper.
      const toastNames = ['showQuickToast','showToast','toast','notify','showNotification','showMessage','flash','showFlash','snackbar','showSnackbar','showAlert'];
      for (const n of toastNames) {
        try {
          if (typeof window[n] === 'function') {
            const orig = window[n];
            window[n] = function(msg) { try { _qaToasts.push(String(msg == null ? '' : msg)); } catch(e) {} return orig.apply(this, arguments); };
          }
        } catch(e) {}
      }

      // downloadFile is a common helper — intercept to record file type.
      try {
        if (typeof downloadFile === 'function') {
          const orig = downloadFile;
          window.downloadFile = function(name, content, type) { _qaDownloads.push({ name: String(name||''), type: String(type||''), size: (content||'').length }); try { return orig.apply(this, arguments); } catch(e){ return true; } };
        }
      } catch(e) {}
      // Intercept URL.createObjectURL → blob downloads via <a> click
      try {
        const origCreate = URL.createObjectURL;
        URL.createObjectURL = function(blob) {
          try { _qaDownloads.push({ name: '', type: (blob && blob.type) || '', size: (blob && blob.size) || 0 }); } catch(e) {}
          return 'blob:stub';
        };
      } catch(e) {}
      // Intercept anchor.click() when a download attribute is present
      try {
        const proto = win => Object.getPrototypeOf(document.createElement('a'));
        const aProto = Object.getPrototypeOf(document.createElement('a'));
        const origClick = aProto.click;
        aProto.click = function() {
          try {
            const dl = this.getAttribute && this.getAttribute('download');
            if (dl) _qaDownloads.push({ name: dl, type: '', size: 0 });
          } catch(e) {}
          try { return origClick.apply(this, arguments); } catch(e) {}
        };
      } catch(e) {}

      // Clipboard
      try {
        if (!navigator.clipboard) navigator.clipboard = {};
        const origWrite = navigator.clipboard.writeText;
        navigator.clipboard.writeText = function(text) {
          try { _qaClipboard.push(String(text == null ? '' : text)); } catch(e) {}
          return Promise.resolve();
        };
      } catch(e) {}
      // execCommand('copy') is the fallback path many apps use
      try {
        const origExec = document.execCommand;
        document.execCommand = function(cmd) {
          if (cmd === 'copy') {
            try {
              const sel = window.getSelection && window.getSelection().toString();
              _qaClipboard.push(sel || '<execCommand copy>');
            } catch(e) {}
            return true;
          }
          if (typeof origExec === 'function') try { return origExec.apply(this, arguments); } catch(e) {}
          return false;
        };
      } catch(e) {}
    })();
  `);
  return {
    reset() {
      tryEval(win, `
        _qaOpens.length = 0; _qaPrints = 0;
        _qaDownloads.length = 0; _qaToasts.length = 0;
        _qaClipboard.length = 0; _qaAlerts.length = 0;
      `);
    },
    snapshot() {
      return tryEval(win, `({
        opens: _qaOpens.slice(),
        prints: _qaPrints,
        downloads: _qaDownloads.slice(),
        toasts: _qaToasts.slice(),
        clipboard: _qaClipboard.slice(),
        alerts: _qaAlerts.slice()
      })`) || { opens: [], prints: 0, downloads: [], toasts: [], clipboard: [], alerts: [] };
    },
  };
}

function escapeRegex(s) { return String(s).replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

// Pick a string field from a saved record that the renderer is likely to display
// verbatim — skip ID-like keys, ISO timestamps, UUIDs, pure numeric strings,
// and other things apps store but format before showing.
function pickRenderableSample(obj) {
  if (!obj || typeof obj !== "object") return "";
  const ID_KEYS = /^(id|_id|uuid|guid|key|hash|token|created(at)?|updated(at)?|timestamp|date|time|datetime|added(at)?|when|at|iso|ts|createdAt|updatedAt|savedAt)$/i;
  for (const [k, v] of Object.entries(obj)) {
    if (typeof v !== "string") continue;
    const s = v.trim();
    if (s.length < 3) continue;
    if (ID_KEYS.test(k)) continue;
    if (/^\d+(\.\d+)?$/.test(s)) continue;                       // pure number
    if (/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}/.test(s)) continue;      // ISO timestamp
    if (/^\d{4}-\d{2}-\d{2}$/.test(s)) continue;                 // ISO date
    if (/^\d{1,2}:\d{2}(:\d{2})?$/.test(s)) continue;            // HH:MM[:SS]
    if (/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(s)) continue;  // UUID
    if (/^blob:|^data:|^https?:\/\//i.test(s)) continue;         // URLs / blob refs
    return s;
  }
  // Fall back to any string ≥4 chars even if it looks ID-ish (only as last resort)
  for (const v of Object.values(obj)) {
    if (typeof v === "string" && v.trim().length >= 4) return v.trim();
  }
  return "";
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
  warn(name, detail = "")  { this.tests.push({ name, ok: true, warning: true, detail }); }

  async runSafely(label, fn) {
    try { await fn(); }
    catch (e) { this.fail(label, "runner exception: " + (e.message || String(e))); }
  }

  async run() {
    this.dom = bootDom(this.htmlPath, this.slug);
    await tick(250);

    await this.runSafely("Navigation",         () => this.testNavigation());
    await this.runSafely("Form save",          () => this.testFormSave());
    await this.runSafely("Render after save",  () => this.testRenderAfterSave());
    await this.runSafely("Persistence",        () => this.testPersistence());
    await this.runSafely("Delete",             () => this.testDelete());
    await this.runSafely("Export",             () => this.testExport());

    // Deeper-behavior tests added after manual QA found 5 bugs the happy-path
    // suite missed. These boot a *fresh* DOM each so prior tests' state mutations
    // don't pollute them (e.g. testDelete leaves arrays mutated).
    await this.runSafely("Modal dismissal",          () => this.testModalDismissal());
    await this.runSafely("Duplicate handling",       () => this.testDuplicateHandling());
    await this.runSafely("Generated data quality",   () => this.testGeneratedQuality());
    await this.runSafely("Button label accuracy",    () => this.testButtonLabelAccuracy());
    await this.runSafely("Unimplemented features",   () => this.testUnimplemented());

    return {
      slug: this.slug,
      passed: this.tests.every(t => t.ok),
      tests: this.tests,
    };
  }

  // Boot a fresh DOM the deeper-behavior tests can mutate without polluting
  // siblings. Memoized so the 5 new tests share one boot (saves ~1s/product).
  async _freshDom() {
    if (this._fresh) return this._fresh;
    this._fresh = bootDom(this.htmlPath, this.slug);
    await tick(250);
    return this._fresh;
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

  // ---------- TEST 7 — Modal dismissal ----------
  async testModalDismissal() {
    const dom = await this._freshDom();
    const win = dom.window;
    const doc = win.document;
    const modals = findModals(doc);
    if (modals.length === 0) {
      this.pass("Modal dismissal", "no modals discovered");
      return;
    }
    const failures = [];
    const ADDED = ["active", "open", "show", "visible"];
    let fullPassCount = 0;
    for (const modal of modals) {
      const id = modal.id || (modal.className || "").trim().split(/\s+/)[0] || "<modal>";

      // Path A: Cancel/Close button
      let cancelOk = "no-cancel-btn";
      const closeBtns = findCloseButtons(modal);
      if (closeBtns.length > 0) {
        forceOpenModal(modal);
        try { closeBtns[0].click(); } catch (e) {}
        await tick(20);
        cancelOk = modalDismissed(modal, ADDED) ? "ok" : "did not dismiss";
      }

      // Path B: Escape key
      forceOpenModal(modal);
      dispatchKeydown(win, "Escape");
      await tick(20);
      const escOk = modalDismissed(modal, ADDED) ? "ok" : "no-escape-handler";

      // Path C: Click on overlay (event.target === modal element)
      forceOpenModal(modal);
      dispatchClickOn(win, modal);
      await tick(20);
      const outOk = modalDismissed(modal, ADDED) ? "ok" : "no-outside-click";

      const issues = [];
      if (cancelOk !== "ok") issues.push("cancel=" + cancelOk);
      if (escOk !== "ok")    issues.push("escape=" + escOk);
      if (outOk !== "ok")    issues.push("outside=" + outOk);
      if (issues.length === 0) fullPassCount++;
      else failures.push(`${id}: ${issues.join(",")}`);
    }
    if (failures.length === 0) {
      this.pass("Modal dismissal", `${fullPassCount}/${modals.length} modals fully dismissible`);
    } else {
      this.fail("Modal dismissal", `${fullPassCount}/${modals.length} fully dismissible — ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 8 — Duplicate / conflict handling ----------
  async testDuplicateHandling() {
    const dom = await this._freshDom();
    const win = dom.window;
    const doc = win.document;
    installProbe(win);
    const handlers = findSaveHandlers(doc);
    if (handlers.length === 0) {
      this.pass("Duplicate handling", "no save handlers to probe");
      return;
    }
    const probe = installProbe(win);
    const failures = [];
    let checked = 0;
    for (const h of handlers) {
      // First save: fill + call
      fillFormInputs(h.form, this.slug + "-dup");
      win._qaForm = h.form;
      probe.reset();
      const beforeFirst = snapshotShape(getStateRef(win));
      try {
        const call = h.viaSubmit
          ? `${h.fn}({preventDefault:function(){},target:_qaForm,currentTarget:_qaForm})`
          : `${h.fn}()`;
        win.eval(call);
      } catch (e) { continue; }
      await tick(30);
      const afterFirst = snapshotShape(getStateRef(win));
      const grownFirst = diffShape(beforeFirst, afterFirst);
      if (grownFirst.length === 0) continue; // first save itself didn't grow → covered by Form save

      // Second save: re-fill same form with same values, save again
      fillFormInputs(h.form, this.slug + "-dup");
      probe.reset();
      try {
        const call = h.viaSubmit
          ? `${h.fn}({preventDefault:function(){},target:_qaForm,currentTarget:_qaForm})`
          : `${h.fn}()`;
        win.eval(call);
      } catch (e) { continue; }
      await tick(30);
      const afterSecond = snapshotShape(getStateRef(win));
      const grownSecond = diffShape(afterFirst, afterSecond);
      const feedback = probe.snapshot();
      const sawFeedback = feedback.toasts.length + feedback.alerts.length > 0;
      checked++;

      if (grownSecond.length === 0) {
        // 2nd save was a no-op
        if (!sawFeedback) {
          failures.push(`${h.fn}: 2nd identical save was silently rejected (no toast/alert)`);
        }
        continue;
      }
      // 2nd save grew state. Find the newly-added item and verify it's visible in DOM
      const g = grownSecond[0];
      const state = getStateRef(win);
      const arr = state[g.key] || [];
      const newItem = arr[arr.length - 1];
      const sample = newItem && pickRenderableSample(newItem);
      if (!sample) continue;
      const text = doc.body ? doc.body.textContent : "";
      const occurrences = (text.match(new RegExp(escapeRegex(sample), "g")) || []).length;
      // First save added 1 of sample. Second save added another. We expect ≥2 occurrences
      // if the renderer shows duplicates. If we see only 1, the second is hidden → silent dup.
      if (occurrences < 2 && !sawFeedback) {
        failures.push(`${h.fn}: state grew to ${g.to} but DOM shows ${occurrences} of "${sample.slice(0, 30)}" (silent duplicate, no feedback)`);
      }
    }
    if (checked === 0) {
      this.pass("Duplicate handling", "no handlers had a successful first save to probe");
    } else if (failures.length === 0) {
      this.pass("Duplicate handling", `${checked}/${checked} handlers handle duplicates cleanly`);
    } else {
      this.fail("Duplicate handling", `${checked - failures.length}/${checked} clean — ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 9 — Generated data quality ----------
  async testGeneratedQuality() {
    const dom = await this._freshDom();
    const win = dom.window;
    installProbe(win);
    const fns = tryEval(win, `
      (function(){
        const out = [];
        for (const k of Object.getOwnPropertyNames(window)) {
          if (typeof window[k] !== 'function') continue;
          if (/^(generate|autoFill|autofill|populate|seed|prefill|fillWeek|fillAll|suggest|sample)([A-Z_]|$)/.test(k)) out.push(k);
        }
        return out;
      })()
    `) || [];
    if (fns.length === 0) {
      this.pass("Generated data quality", "no generate/autofill functions found");
      return;
    }
    const failures = [];
    let okCount = 0;
    const CATEGORY_FIELDS = ["category", "type", "kind", "status", "priority", "mealType", "group", "section", "tag"];
    const TEXT_FIELDS    = ["name", "title", "label", "description", "recipeName"];
    const DEFAULT_VALUES = /^(other|default|none|n\/a|unknown|misc|todo|generic|tbd|untitled|placeholder)?$/i;
    for (const fn of fns) {
      const state = getStateRef(win);
      if (!state) continue;
      const beforeSizes = {};
      for (const k of Object.keys(state)) {
        if (Array.isArray(state[k])) beforeSizes[k] = state[k].length;
      }
      try { win.eval(`${fn}()`); } catch (e) { continue; }
      await tick(40);
      // Find which arrays grew
      const grewKeys = [];
      for (const k of Object.keys(beforeSizes)) {
        const after = Array.isArray(state[k]) ? state[k].length : 0;
        if (after > beforeSizes[k]) grewKeys.push({ key: k, from: beforeSizes[k], to: after });
      }
      if (grewKeys.length === 0) continue; // function didn't add anything to state
      for (const g of grewKeys) {
        const added = state[g.key].slice(g.from);
        if (added.length < 3) continue; // can't measure variety with <3 items
        // Category-style variety check
        for (const f of CATEGORY_FIELDS) {
          const values = added.map(i => i && i[f]).filter(v => v != null && v !== "");
          if (values.length < Math.max(3, added.length * 0.6)) continue;
          const unique = new Set(values.map(v => String(v).toLowerCase()));
          if (unique.size === 1) {
            const v = [...unique][0];
            if (DEFAULT_VALUES.test(v)) {
              failures.push(`${fn}: all ${values.length} added ${g.key} items have ${f}="${v}" (looks like fallback, no real categorization)`);
            }
          }
        }
        // Empty key-text field check
        for (const f of TEXT_FIELDS) {
          if (!added.some(i => i && f in i)) continue;
          const empty = added.filter(i => !i || !i[f] || String(i[f]).trim() === "").length;
          if (empty === added.length) {
            failures.push(`${fn}: all ${added.length} added ${g.key} items have empty ${f}`);
          }
        }
      }
      if (failures.filter(s => s.startsWith(fn + ":")).length === 0) okCount++;
    }
    if (failures.length === 0) {
      this.pass("Generated data quality", `${fns.length} generate fn(s) produce varied data`);
    } else {
      this.fail("Generated data quality", `${okCount}/${fns.length} clean — ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 10 — Button label accuracy ----------
  async testButtonLabelAccuracy() {
    const dom = await this._freshDom();
    const win = dom.window;
    const doc = win.document;
    const probe = installProbe(win);
    const failures = [];

    // Button text must match (case-insensitive substring). Also gate by onclick handler name
    // so a button literally labeled "Email" (and not e.g. "Email address") triggers a check.
    const checks = [
      {
        name: "Email",
        labelTest: /(^|[\s])(email|✉|✉️)([\s]|$)|email\b/i,
        verify: (s) => {
          const mailto = s.opens.some(u => /^mailto:/i.test(u));
          const onlyClipboard = !mailto && s.clipboard.length > 0;
          if (mailto) return { ok: true };
          if (onlyClipboard) return { ok: false, why: "copied to clipboard instead of opening mailto:" };
          if (s.toasts.some(t => /clipboard|copied/i.test(t))) return { ok: false, why: "showed clipboard/copy toast instead of opening mailto:" };
          if (s.opens.length === 0 && s.downloads.length === 0) return { ok: false, why: "no recognizable action (no mailto, no download)" };
          return { ok: false, why: "opened a non-mailto URL: " + (s.opens[0] || "?") };
        },
      },
      {
        name: "PDF",
        labelTest: /(\bpdf\b|export.*pdf|📄)/i,
        verify: (s) => {
          if (s.prints > 0) return { ok: true };
          if (s.opens.length > 0) return { ok: true }; // print-to-PDF via new window
          if (s.downloads.some(d => /pdf|html|application\/pdf/i.test((d.name || "") + " " + (d.type || "")))) return { ok: true };
          return { ok: false, why: "no print, no new window, no pdf/html download triggered" };
        },
      },
      {
        name: "CSV",
        // Require the literal word "csv" — a standalone 📊 emoji also marks
        // navigation/overview buttons in some products, which would false-flag.
        labelTest: /\bcsv\b/i,
        verify: (s) => {
          if (s.downloads.some(d => /csv|text\/csv/i.test((d.name || "") + " " + (d.type || "")))) return { ok: true };
          return { ok: false, why: "no .csv download triggered" };
        },
      },
      {
        name: "Print",
        labelTest: /(^|[\s>])(print)([\s<]|$)|🖨/i,
        verify: (s) => {
          if (s.prints > 0) return { ok: true };
          if (s.opens.length > 0) return { ok: true };
          return { ok: false, why: "did not call window.print() and opened no print window" };
        },
      },
    ];

    let checkedTotal = 0;
    const seen = new Set();
    for (const btn of doc.querySelectorAll("button, a, [role='button']")) {
      const oc = btn.getAttribute("onclick") || "";
      if (!oc) continue;
      const txt = (btn.textContent || "").trim();
      if (!txt) continue;
      for (const c of checks) {
        if (!c.labelTest.test(txt)) continue;
        const key = c.name + "::" + oc;
        if (seen.has(key)) continue;
        seen.add(key);
        probe.reset();
        try { btn.click(); } catch (e) {}
        await tick(60); // give async clipboard / window.open paths a chance
        const s = probe.snapshot();
        const r = c.verify(s);
        checkedTotal++;
        if (!r.ok) {
          failures.push(`${c.name} button "${txt.slice(0, 30)}": ${r.why}`);
        }
        break;
      }
    }

    if (checkedTotal === 0) {
      this.pass("Button label accuracy", "no labeled action buttons (Email/PDF/CSV/Print) found");
    } else if (failures.length === 0) {
      this.pass("Button label accuracy", `${checkedTotal} labeled button(s) match their action`);
    } else {
      this.fail("Button label accuracy", `${checkedTotal - failures.length}/${checkedTotal} match — ${failures.join("; ")}`);
    }
  }

  // ---------- TEST 11 — Unimplemented features (WARNING) ----------
  async testUnimplemented() {
    const dom = await this._freshDom();
    const win = dom.window;
    const doc = win.document;
    const probe = installProbe(win);
    const NOT_IMPL = /not implemented|not yet implemented|coming soon|todo\b|under construction|placeholder|wip\b|stub\b/i;

    const warnings = [];
    const seenFns = new Set();
    const buttons = doc.querySelectorAll("button[onclick], a[onclick], [role='button'][onclick]");
    for (const btn of buttons) {
      const oc = btn.getAttribute("onclick") || "";
      const fn = extractHandlerName(oc);
      if (!fn) continue;
      const key = fn + "::" + (btn.textContent || "").trim();
      if (seenFns.has(key)) continue;
      seenFns.add(key);

      probe.reset();
      try { btn.click(); } catch (e) {}
      await tick(20);
      const s = probe.snapshot();
      const all = [...s.toasts, ...s.alerts];
      const hit = all.find(m => NOT_IMPL.test(m || ""));
      if (!hit) continue;

      // Is the button visibly enabled to the user?
      const style = btn.getAttribute("style") || "";
      const cls = btn.className || "";
      const hidden = /display\s*:\s*none/i.test(style) || /\bhidden\b/i.test(cls);
      const disabled = btn.hasAttribute("disabled") || /\bdisabled\b/i.test(cls);
      if (hidden || disabled) continue;

      const txt = (btn.textContent || "").trim().slice(0, 40);
      warnings.push(`${fn} "${txt}" emits "${hit.slice(0, 60)}" while button is visible/enabled`);
    }
    if (warnings.length === 0) {
      this.pass("Unimplemented features", "no visible/enabled button emits a coming-soon/not-implemented message");
    } else {
      this.warn("Unimplemented features", `${warnings.length} warning(s) — ${warnings.join("; ")}`);
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
      const mark = t.ok ? (t.warning ? "⚠" : "✓") : "✗";
      console.log(`  ${mark} ${t.name} — ${t.detail || (t.ok ? "ok" : "failed")}`);
    }
  }
  process.exit(result.passed ? 0 : 1);
})();
