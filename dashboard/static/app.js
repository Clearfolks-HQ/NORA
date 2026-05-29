"use strict";

const $ = (sel) => document.querySelector(sel);

function fmtDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  if (isNaN(d)) return iso;
  return d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

function fmtRelative(iso) {
  if (!iso) return "never";
  const then = new Date(iso);
  const now = new Date();
  const diffMin = Math.round((now - then) / 60000);
  if (diffMin < 1) return "just now";
  if (diffMin < 60) return diffMin + "m ago";
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return diffH + "h ago";
  const diffD = Math.round(diffH / 24);
  return diffD + "d ago";
}

function escapeHtml(s) {
  if (s == null) return "";
  return String(s)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(url + " → " + r.status);
  return r.json();
}

// ───────────── Signals ─────────────
async function loadSignals() {
  const target = $("#signals-list");
  target.innerHTML = '<div class="empty">Loading signals…</div>';
  try {
    const data = await getJSON("/api/signals");
    $("#signals-meta").textContent =
      data.count + " signal" + (data.count === 1 ? "" : "s") + " · " + data.date;
    if (!data.count) {
      target.innerHTML = '<div class="empty">No signals for today yet — Pulse runs at 7am.</div>';
      return;
    }
    target.innerHTML = data.signals.map(renderSignal).join("");
    target.querySelectorAll(".act-btn").forEach((b) => {
      b.addEventListener("click", () => onAction(b.dataset.id, b.dataset.action));
    });
  } catch (e) {
    target.innerHTML = '<div class="empty">Error loading signals: ' + escapeHtml(e.message) + "</div>";
  }
}

function renderSignal(s) {
  const status = s.status || "pending";
  const score = s.score != null ? '<span class="score-pill">' + s.score + "/10</span>" : "";
  const badge = '<span class="badge badge-' + status + '">' + status + "</span>";
  return (
    '<div class="signal signal-' + status + '" id="sig-' + escapeHtml(s.id) + '">' +
      '<div class="signal-head">' +
        '<div>' +
          '<span class="signal-sub">' + escapeHtml(s.subreddit || "") + "</span>" + score +
        "</div>" + badge +
      "</div>" +
      '<div class="signal-title">' +
        (s.post_url
          ? '<a href="' + escapeHtml(s.post_url) + '" target="_blank" rel="noopener">' + escapeHtml(s.post_title) + "</a>"
          : escapeHtml(s.post_title)) +
      "</div>" +
      (s.pain_point ? '<p class="signal-pain">' + escapeHtml(s.pain_point) + "</p>" : "") +
      (s.suggested_reply ? '<div class="signal-reply">' + escapeHtml(s.suggested_reply) + "</div>" : "") +
      '<div class="signal-actions">' +
        '<button class="act-btn posted"  data-id="' + escapeHtml(s.id) + '" data-action="posted">✅ Mark Posted</button>' +
        '<button class="act-btn skipped" data-id="' + escapeHtml(s.id) + '" data-action="skipped">⏭ Skip</button>' +
        '<button class="act-btn remind"  data-id="' + escapeHtml(s.id) + '" data-action="remind">🔁 Remind Tomorrow</button>' +
      "</div>" +
    "</div>"
  );
}

async function onAction(sid, action) {
  try {
    const r = await fetch("/api/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ signal_id: sid, action: action }),
    });
    if (!r.ok) throw new Error("status " + r.status);
    await loadSignals();
    await loadTracker();
  } catch (e) {
    alert("Failed to record action: " + e.message);
  }
}

// ───────────── Pipeline ─────────────
async function loadPipeline() {
  const target = $("#pipeline-table");
  target.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const data = await getJSON("/api/pipeline");
    target.innerHTML = data.agents.map((a) => (
      '<div class="pipeline-row">' +
        '<div class="pipe-name">' + escapeHtml(a.label) + "</div>" +
        '<div class="pipe-sched">' + escapeHtml(a.schedule) + "</div>" +
        '<div class="pipe-line">Last: <b>' + escapeHtml(fmtRelative(a.last_run)) + "</b>" +
          (a.last_run ? ' <span class="list-meta">(' + escapeHtml(fmtDate(a.last_run)) + ")</span>" : "") +
        "</div>" +
        '<div class="pipe-line">Next: <b>' + escapeHtml(fmtDate(a.next_run)) + "</b></div>" +
      "</div>"
    )).join("");
  } catch (e) {
    target.innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + "</div>";
  }
}

// ───────────── Pinterest ─────────────
async function loadPinterest() {
  const list = $("#pinterest-list");
  list.innerHTML = '<li class="empty">Loading…</li>';
  try {
    const data = await getJSON("/api/pinterest-today");
    $("#pinterest-meta").textContent =
      data.pins.length + " pin" + (data.pins.length === 1 ? "" : "s") + " scheduled today";
    if (!data.pins.length) {
      list.innerHTML = '<li class="empty">No pins scheduled for today.</li>';
      return;
    }
    list.innerHTML = data.pins.map((p) => (
      "<li><b>" + escapeHtml(p.board) + "</b>" +
        '<span class="list-meta">→ ' + escapeHtml(p.scheduled_at) + "</span></li>"
    )).join("");
  } catch (e) {
    list.innerHTML = '<li class="empty">Error: ' + escapeHtml(e.message) + "</li>";
  }
}

// ───────────── Blog ─────────────
async function loadBlog() {
  const list = $("#blog-list");
  list.innerHTML = '<li class="empty">Loading…</li>';
  try {
    const data = await getJSON("/api/blog-week");
    $("#blog-meta").textContent =
      data.posts.length + " post" + (data.posts.length === 1 ? "" : "s") + " published in last 7 days";
    if (!data.posts.length) {
      list.innerHTML = '<li class="empty">No posts in the last 7 days.</li>';
      return;
    }
    list.innerHTML = data.posts.map((p) => (
      '<li><a href="' + escapeHtml(p.url) + '" target="_blank" rel="noopener">' +
        escapeHtml(p.title) + "</a>" +
        '<span class="list-meta">' + escapeHtml(p.date) + "</span></li>"
    )).join("");
  } catch (e) {
    list.innerHTML = '<li class="empty">Error: ' + escapeHtml(e.message) + "</li>";
  }
}

// ───────────── Tracker ─────────────
async function loadTracker() {
  const target = $("#tracker-grid");
  target.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const t = await getJSON("/api/actions");
    $("#tracker-meta").textContent = "Week of " + t.week_start;
    const cells = [
      ["Reddit posted",  t.reddit_posted],
      ["Reddit skipped", t.reddit_skipped],
      ["Reddit pending today", t.reddit_pending],
      ["Pinterest pins", t.pinterest_pins],
      ["Blog posts",     t.blog_posts],
      ["Quora answers",  t.quora_answers],
    ];
    target.innerHTML = cells.map(([label, value]) => (
      '<div class="stat-cell">' +
        '<div class="stat-value">' + value + "</div>" +
        '<div class="stat-label">' + escapeHtml(label) + "</div>" +
      "</div>"
    )).join("");
  } catch (e) {
    target.innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + "</div>";
  }
}

// ───────────── Stats ─────────────
async function loadStats() {
  const target = $("#stats-grid");
  target.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const s = await getJSON("/api/stats");
    const cells = [
      ["Products (total)", s.products_total],
      ["Products live",    s.products_live],
      ["Live on Etsy",     s.etsy_live],
      ["Blog posts",       s.blog_posts],
      ["Pinterest boards", s.pinterest_boards],
      ["Subreddits",       s.subreddits],
    ];
    target.innerHTML = cells.map(([label, value]) => (
      '<div class="stat-cell">' +
        '<div class="stat-value">' + value + "</div>" +
        '<div class="stat-label">' + escapeHtml(label) + "</div>" +
      "</div>"
    )).join("");
  } catch (e) {
    target.innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + "</div>";
  }
}

// ───────────── Reddit posts ─────────────
let _redditCache = null;
let _redditTab = "drafts";

async function loadReddit() {
  const target = $("#reddit-content");
  target.innerHTML = '<div class="empty">Loading…</div>';
  try {
    _redditCache = await getJSON("/api/reddit-posts");
    const c = _redditCache.counts;
    $("#reddit-meta").textContent =
      `${c.draft} draft · ${c.posted} posted · ${c.skipped} skipped`;
    renderReddit();
  } catch (e) {
    target.innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + "</div>";
  }
}

function renderReddit() {
  const target = $("#reddit-content");
  if (!_redditCache) { target.innerHTML = '<div class="empty">No data.</div>'; return; }

  if (_redditTab === "history") {
    const rows = _redditCache.history.slice().reverse();
    if (!rows.length) {
      target.innerHTML = '<div class="empty">No actions yet. Drafts get generated Sunday 7am.</div>';
      return;
    }
    target.innerHTML = rows.map((h) => (
      '<div class="r-history-row">' +
        '<span class="r-history-action ' + escapeHtml(h.action || "") + '">' + escapeHtml(h.action || "") + "</span>" +
        '<span><b>' + escapeHtml(h.title || h.draft_id || "") + "</b></span>" +
        '<span class="r-cat">[' + escapeHtml(h.type || "") + " · " + escapeHtml(h.category || "") + "]</span>" +
        '<span class="r-history-when">' + escapeHtml(fmtDate(h.ts)) + "</span>" +
      "</div>"
    )).join("");
    return;
  }

  const statusFilter =
    _redditTab === "drafts"  ? (d) => d.status === "draft" :
    _redditTab === "posted"  ? (d) => d.status === "posted" :
    _redditTab === "skipped" ? (d) => d.status === "skipped" :
    () => true;
  const list = (_redditCache.drafts || []).filter(statusFilter);

  if (!list.length) {
    target.innerHTML = '<div class="empty">Nothing here yet.</div>';
    return;
  }

  target.innerHTML = list.map(renderDraft).join("");
  target.querySelectorAll(".r-act-btn").forEach((b) => {
    b.addEventListener("click", () => onRedditAction(b.dataset.id, b.dataset.action));
  });
}

function renderDraft(d) {
  const isBlog = d.type === "blog_link";
  const status = d.status || "draft";
  const body   = isBlog ? (d.intro + "\n\n" + (d.blog_url || "")) : (d.body || "");
  const subs   = (d.subreddits || []).join(", ");
  const actions = status === "draft"
    ? (
      '<button class="act-btn posted r-act-btn"  data-id="' + escapeHtml(d.id) + '" data-action="posted">✅ Mark Posted</button>' +
      '<button class="act-btn skipped r-act-btn" data-id="' + escapeHtml(d.id) + '" data-action="skipped">⏭ Skip</button>'
    )
    : '<span class="badge badge-' + (status === "posted" ? "posted" : "skipped") + '">' + status + "</span>";

  return (
    '<div class="reddit-draft r-' + status + '">' +
      '<div class="reddit-draft-head">' +
        "<div>" +
          '<span class="r-type-pill ' + escapeHtml(d.type) + '">' + (isBlog ? "blog link" : "value") + "</span> " +
          '<span class="r-cat">' + escapeHtml(d.category || "") + " · " + escapeHtml(d.created || "").slice(0, 10) + "</span>" +
        "</div>" +
        '<span class="badge badge-' + (status === "draft" ? "pending" : status) + '">' + status + "</span>" +
      "</div>" +
      '<div class="r-title">' + escapeHtml(d.title || "") + "</div>" +
      '<div class="r-body">' + escapeHtml(body) + "</div>" +
      '<div class="r-subs">' + escapeHtml(subs) + "</div>" +
      '<div class="signal-actions">' + actions + "</div>" +
    "</div>"
  );
}

async function onRedditAction(did, action) {
  try {
    const r = await fetch("/api/reddit-action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft_id: did, action: action }),
    });
    if (!r.ok) throw new Error("status " + r.status);
    await loadReddit();
  } catch (e) {
    alert("Failed to record action: " + e.message);
  }
}

function wireRedditTabs() {
  document.querySelectorAll(".reddit-tab").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".reddit-tab").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      _redditTab = b.dataset.tab;
      renderReddit();
    });
  });
}

// ───────────── Content Backlog ─────────────
let _backlogCache = null;
let _backlogTab = "value";

async function loadBacklog() {
  const target = $("#backlog-content");
  target.innerHTML = '<div class="empty">Loading…</div>';
  try {
    _backlogCache = await getJSON("/api/content-backlog");
    const c = _backlogCache;
    $("#backlog-meta").textContent =
      `${c.value_posts.length} value · ${c.problem_posts.length} problem · ${c.blog_posts.length} blog link · ${c.pinterest.length} pinterest · ${c.blog_published.length} blog`;
    renderBacklog();
  } catch (e) {
    target.innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + "</div>";
  }
}

function renderBacklog() {
  const target = $("#backlog-content");
  if (!_backlogCache) { target.innerHTML = '<div class="empty">No data.</div>'; return; }

  const tab = _backlogTab;
  if (tab === "value")     { renderBacklogList(_backlogCache.value_posts,   "value_post");   return; }
  if (tab === "problem")   { renderBacklogList(_backlogCache.problem_posts, "problem_post"); return; }
  if (tab === "bloglink")  { renderBacklogList(_backlogCache.blog_posts,    "blog_link");    return; }
  if (tab === "pinterest") { renderPinterestQueue(_backlogCache.pinterest);                   return; }
  if (tab === "blog")      { renderBlogTab(_backlogCache.blog_published, _backlogCache.blog_outlines); return; }
}

function renderBacklogList(items, kind) {
  const target = $("#backlog-content");
  if (!items || !items.length) {
    target.innerHTML = '<div class="empty">No drafts in this category yet.</div>';
    return;
  }
  target.innerHTML = items.map((it) => renderBacklogCard(it, kind)).join("");
  target.querySelectorAll(".bk-copy-btn").forEach((b) => {
    b.addEventListener("click", () => onBacklogCopy(b.dataset.file, kind));
  });
  target.querySelectorAll(".bk-act-btn").forEach((b) => {
    b.addEventListener("click", () => onBacklogAction(b.dataset.file, b.dataset.status, kind, b.dataset.product, b.dataset.subreddit, b.dataset.title));
  });
}

function renderBacklogCard(it, kind) {
  const status = it.status || "draft";
  const typeLabel = kind === "blog_link" ? "blog link" : (kind === "problem_post" ? "problem" : "value");
  const blogLine = (kind === "blog_link" && it.blog_url)
    ? '<div class="bk-bloglink"><a href="' + escapeHtml(it.blog_url) + '" target="_blank" rel="noopener">' + escapeHtml(it.blog_url) + "</a></div>"
    : "";
  const actions = status === "draft"
    ? (
      '<button class="act-btn bk-copy-btn"  data-file="' + escapeHtml(it.file) + '">📋 Copy post</button>' +
      '<button class="act-btn posted bk-act-btn"  data-file="' + escapeHtml(it.file) + '" data-status="posted"  data-product="' + escapeHtml(it.product || "") + '" data-subreddit="' + escapeHtml(it.subreddit || "") + '" data-title="' + escapeHtml(it.title || "") + '">✅ Mark posted</button>' +
      '<button class="act-btn skipped bk-act-btn" data-file="' + escapeHtml(it.file) + '" data-status="skipped" data-product="' + escapeHtml(it.product || "") + '" data-subreddit="' + escapeHtml(it.subreddit || "") + '" data-title="' + escapeHtml(it.title || "") + '">⏭ Skip</button>'
    )
    : '<span class="badge badge-' + (status === "posted" ? "posted" : "skipped") + '">' + escapeHtml(status) + "</span>";

  return (
    '<div class="reddit-draft r-' + (status === "draft" ? "" : status) + '">' +
      '<div class="reddit-draft-head">' +
        "<div>" +
          '<span class="r-type-pill">' + escapeHtml(typeLabel) + "</span> " +
          '<span class="r-cat">' + escapeHtml(it.product_name || "") + " · " + escapeHtml(it.subreddit || "") + "</span>" +
        "</div>" +
        '<span class="badge badge-' + (status === "draft" ? "pending" : status) + '">' + escapeHtml(status) + "</span>" +
      "</div>" +
      '<div class="r-title">' + escapeHtml(it.title || "") + "</div>" +
      blogLine +
      '<div class="r-body">' + escapeHtml(it.preview || "") + "</div>" +
      '<div class="signal-actions">' + actions + "</div>" +
    "</div>"
  );
}

function renderPinterestQueue(items) {
  const target = $("#backlog-content");
  if (!items || !items.length) {
    target.innerHTML = '<div class="empty">No Pinterest drafts in queue.</div>';
    return;
  }
  target.innerHTML = items.map((p) => (
    '<div class="reddit-draft">' +
      '<div class="reddit-draft-head">' +
        '<div><span class="r-type-pill">pin</span> ' +
          '<span class="r-cat">' + escapeHtml(p.product_name || "") + " · " + escapeHtml(p.board || "") + "</span>" +
        "</div>" +
        '<span class="badge badge-' + (p.status === "posted" ? "posted" : "pending") + '">' + escapeHtml(p.status) + "</span>" +
      "</div>" +
      '<div class="r-title">' + escapeHtml(p.title || "") + "</div>" +
      (p.etsy_url
        ? '<div class="bk-bloglink"><a href="' + escapeHtml(p.etsy_url) + '" target="_blank" rel="noopener">' + escapeHtml(p.etsy_url) + "</a></div>"
        : "") +
      '<div class="r-body">' + escapeHtml(p.description || "") + "</div>" +
    "</div>"
  )).join("");
}

function renderBlogTab(published, outlines) {
  const target = $("#backlog-content");
  let html = '<div class="bk-blog-section"><div class="bk-section-title">Published — ' + (published || []).length + "</div><ul class=\"plain-list\">";
  if (!published || !published.length) {
    html += '<li class="empty">No published posts yet.</li>';
  } else {
    html += published.map((p) => (
      '<li><a href="' + escapeHtml(p.url) + '" target="_blank" rel="noopener">' + escapeHtml(p.title) + "</a>" +
        '<span class="list-meta">' + escapeHtml(p.date) + "</span></li>"
    )).join("");
  }
  html += "</ul></div>";
  html += '<div class="bk-blog-section"><div class="bk-section-title">Unpublished outlines — ' + (outlines || []).length + "</div><ul class=\"plain-list\">";
  if (!outlines || !outlines.length) {
    html += '<li class="empty">All outlines published.</li>';
  } else {
    html += outlines.map((o) => (
      "<li><b>" + escapeHtml(o.title) + "</b>" +
        '<span class="list-meta">' + escapeHtml(o.file) + "</span></li>"
    )).join("");
  }
  html += "</ul></div>";
  target.innerHTML = html;
}

async function onBacklogCopy(file, kind) {
  if (!_backlogCache) return;
  const items =
    kind === "value_post"   ? _backlogCache.value_posts   :
    kind === "problem_post" ? _backlogCache.problem_posts :
                              _backlogCache.blog_posts;
  const it = (items || []).find((x) => x.file === file);
  if (!it) return;
  const text = kind === "blog_link"
    ? (it.title + "\n\n" + (it.body || "") + (it.blog_url && !(it.body || "").includes(it.blog_url) ? "\n\n" + it.blog_url : ""))
    : (it.title + "\n\n" + (it.body || ""));
  try {
    await navigator.clipboard.writeText(text);
    alert("Copied: " + it.title);
  } catch (e) {
    prompt("Copy this:", text);
  }
}

async function onBacklogAction(file, status, kind, product, subreddit, title) {
  try {
    const r = await fetch("/api/content-action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        file: file, status: status, type: kind,
        product: product, subreddit: subreddit, title: title,
      }),
    });
    if (!r.ok) throw new Error("status " + r.status);
    await loadBacklog();
    await loadPerformance();
  } catch (e) {
    alert("Failed to record action: " + e.message);
  }
}

function wireBacklogTabs() {
  document.querySelectorAll(".backlog-tab").forEach((b) => {
    b.addEventListener("click", () => {
      document.querySelectorAll(".backlog-tab").forEach((x) => x.classList.remove("active"));
      b.classList.add("active");
      _backlogTab = b.dataset.tab;
      renderBacklog();
    });
  });
}

// ───────────── Performance ─────────────
async function loadPerformance() {
  const body = $("#performance-body");
  body.innerHTML = '<div class="empty">Loading…</div>';
  try {
    const p = await getJSON("/api/performance");
    $("#performance-meta").textContent = "Week of " + p.week_start;
    const cells = [
      ["Posts made",   p.posted],
      ["Posts pending", p.pending],
      ["Total reach (views)", p.total_views || 0],
      ["Best upvotes", p.best_post && p.best_post.upvotes != null ? p.best_post.upvotes : "—"],
    ];
    let html = '<div class="stats-grid">' + cells.map(([label, value]) => (
      '<div class="stat-cell">' +
        '<div class="stat-value">' + escapeHtml(String(value)) + "</div>" +
        '<div class="stat-label">' + escapeHtml(label) + "</div>" +
      "</div>"
    )).join("") + "</div>";
    if (p.best_post) {
      html += '<div class="bk-best"><b>Best post:</b> ' + escapeHtml(p.best_post.title || "") +
        ' <span class="list-meta">' + escapeHtml(p.best_post.subreddit || "") + " · " + escapeHtml(p.best_post.product || "") + "</span></div>";
    }
    if (p.cold_products && p.cold_products.length) {
      html += '<div class="bk-cold"><b>Cold this week (no posts):</b><ul class="bk-cold-list">' +
        p.cold_products.map((c) => '<li>' + escapeHtml(c.product_name) + '</li>').join("") +
        "</ul></div>";
    }
    body.innerHTML = html;
  } catch (e) {
    body.innerHTML = '<div class="empty">Error: ' + escapeHtml(e.message) + "</div>";
  }
}

// ───────────── Bootstrap ─────────────
async function refreshAll() {
  $("#today").textContent = new Date().toLocaleDateString(undefined, {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  await Promise.all([loadSignals(), loadBacklog(), loadPerformance(), loadReddit(), loadPipeline(), loadPinterest(), loadBlog(), loadTracker(), loadStats()]);
  $("#last-refresh").textContent = "refreshed " + new Date().toLocaleTimeString();
}

document.addEventListener("DOMContentLoaded", () => {
  wireRedditTabs();
  wireBacklogTabs();
  refreshAll();
  $("#refresh").addEventListener("click", refreshAll);
  setInterval(refreshAll, 5 * 60 * 1000);
});
