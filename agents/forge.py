#!/usr/bin/env python3
"""
Forge — PWA Builder Agent (two-pass: HTML first, then JS)
Usage: forge.py "Product Name" | forge.py --next | forge.py --list
"""

import os, sys, json, random, subprocess, re, time, tempfile
from datetime import datetime
import urllib.request, urllib.parse
import anthropic

# Functional QA — used as a mandatory deploy gate further down. Imported
# lazily so a missing qa.py doesn't break unrelated forge invocations
# (forge --list shouldn't load qa).
def _import_qa():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from qa import run_functional_qa
    return run_functional_qa

client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
CATEGORIES_FILE = "/root/clearfolks/categories.json"
PRODUCTS_FILE = "/root/clearfolks/products.json"
WWW_ROOT = "/var/www/clearfolk"
NGINX_CONF = "/etc/nginx/sites-available/clearfolk"
LOGS_DIR = "/root/clearfolks/logs"

HTML_PROMPT = '''You are Forge, building a PWA for Clearfolks Templates.

PASS 1 — Generate the complete HTML structure and CSS only. No JavaScript.
End the file with <script id="app-script"></script></body></html>
This is a placeholder — JavaScript will be injected separately.

DESIGN RULES:
- Google Fonts: DM Sans + DM Mono
- CSS variables: --bg:#F5F5F7; --surface:#fff; --s2:#F9F9FB; --border:#E5E5EA; --text:#1C1C1E; --t2:#636366; --t3:#AEAEB2; --accent:#2C6BED; --red:#FF3B30; --orange:#FF9500; --green:#34C759; --purple:#5856D6; --dark:#1C1C1E; --r:12px; --rsm:8px; --sh:0 1px 3px rgba(0,0,0,.06),0 4px 16px rgba(0,0,0,.04); --f:'DM Sans',-apple-system,sans-serif; --mono:'DM Mono',monospace; --sat:env(safe-area-inset-top,0px); --sab:env(safe-area-inset-bottom,0px)
- Dark sidebar on desktop, bottom nav on mobile
- Cards border-radius 12px, subtle shadow
- PWA meta tags, manifest link, apple touch icon
- Brand footer: "Made by Clearfolk · Practical tools for life's complicated moments · clearfolks.com"
- All sections present but hidden (display:none) except first
- Use onclick="METHOD()" for ALL interactive elements — call global functions by bare name, NO "app." prefix anywhere
- Minimum 5 nav sections + Export section
- Keep CSS compact: reuse utility classes, no decorative extras
- Target total file size under 40KB — prioritize working structure over visual flourishes

PRODUCT: {NAME}
CATEGORY: {CATEGORY}
PAIN: {PAIN}

Output only the HTML file. No markdown fences.'''

JS_PROMPT = '''You are Forge, completing a PWA for Clearfolks Templates.

PASS 2 — Generate ONLY the JavaScript for this PWA.
The HTML structure already exists. Your JS will be injected into <script id="app-script">.

ALL functions must be declared at top level with `function NAME() {{ ... }}`.
HTML uses `onclick="METHOD()"` — bare calls, NO `app.` prefix, NO object wrapping.

REQUIREMENTS:
- Top-level declarations only: `function switchSection(name) {{...}}`, `function openModal(id) {{...}}`, etc.
- Keep shared mutable state in a single top-level `let state = {{...}}` variable, NOT on an `app` object.
- localStorage key: "{STORAGE_KEY}"
- switchSection(name) — hide all .section, show matching one, update nav active state
- Full CRUD for each data type
- Export to CSV
- importData() and clearAllData()
- At the bottom of the script, immediately invoke load() and render the first section — no app.init wrapper.
- Also register the service worker: `if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');`

MANDATORY CONTRACT — you MUST declare every one of these functions at top level,
with behavior that matches its name. Missing any of them = build failure:
{REQUIRED_FNS}

The HTML references these element IDs via document.getElementById. Read/write
them by exactly these IDs; do not invent new IDs or rename existing ones:
{ELEMENT_IDS}

PRODUCT: {NAME}
SECTIONS: {SECTIONS}
DATA TYPES: {DATA_TYPES}

Output ONLY the JavaScript code. No HTML, no markdown fences, no explanation.'''

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    data = urllib.parse.urlencode({"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=15)
    except Exception as e:
        print(f"Telegram error: {e}")

def generate_slug():
    return "cf-" + "".join(random.choices("abcdefghijklmnopqrstuvwxyz0123456789", k=8))

def extract_sections(html):
    sections = re.findall(r'id="(\w+)"\s+class="section', html)
    return sections if sections else ["overview", "list", "add", "notes", "export"]

def extract_data_types(html):
    inputs = re.findall(r'id="(\w+)Input"', html)
    return list(set([re.sub(r'(Name|Title|Date|Amount|Notes|Status|Type)$', '', i) for i in inputs if len(i) > 4]))

def extract_onclick_fns(html):
    """Return every bare function name referenced from onclick= in the HTML."""
    return sorted(set(re.findall(r'onclick="(\w+)\(', html)))

def extract_element_ids(html):
    """Return every id on an <input>, <select>, or <textarea> in the HTML."""
    pattern = re.compile(r'<(?:input|select|textarea)\b[^>]*\bid="([^"]+)"', re.IGNORECASE)
    return sorted(set(pattern.findall(html)))

def call_claude(prompt, max_tokens=6000):
    last_err = None
    for attempt in range(4):
        try:
            chunks = []
            with client.messages.stream(
                model="claude-sonnet-4-5",
                max_tokens=max_tokens,
                messages=[{"role": "user", "content": prompt}],
            ) as stream:
                for text in stream.text_stream:
                    chunks.append(text)
            return "".join(chunks).strip()
        except (anthropic.APIStatusError, anthropic.APIConnectionError) as e:
            last_err = e
            status = getattr(e, "status_code", None)
            if status is not None and status < 500 and status != 429:
                raise
            wait = 30 * (2 ** attempt)
            print(f"  API error ({status or type(e).__name__}) — retrying in {wait}s (attempt {attempt + 1}/4)")
            time.sleep(wait)
    raise last_err

def clean_code(text, expected="html"):
    text = re.sub(r'^```\w*\n?', '', text)
    text = re.sub(r'\n?```$', '', text)
    return text.strip()

def qa_check(html):
    issues = []
    if not html.strip().endswith("</html>"):
        issues.append("CRITICAL: missing </html>")
    if "</body>" not in html:
        issues.append("CRITICAL: missing </body>")
    if "app-script" not in html:
        issues.append("CRITICAL: missing script placeholder")
    return issues

def deploy(slug, html):
    folder = f"{WWW_ROOT}/{slug}"
    os.makedirs(folder, exist_ok=True)
    with open(f"{folder}/index.html", "w") as f:
        f.write(html)
    print(f"  Deployed to {folder}")

def add_nginx_route(slug, name):
    with open(NGINX_CONF) as f:
        config = f.read()
    if f"/{slug}" in config:
        print(f"  Route /{slug} exists")
        return
    route = f"""
    # {name}
    location /{slug} {{
        alias {WWW_ROOT}/{slug};
        try_files $uri $uri/ /{slug}/index.html;
        add_header Cache-Control "public, max-age=3600, must-revalidate";
    }}
"""
    marker = "    # Default — show product index or redirect to Etsy"
    with open(NGINX_CONF, "w") as f:
        f.write(config.replace(marker, route + "\n    " + marker.strip()))
    print(f"  Nginx route: /{slug}")

def reload_nginx():
    r = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  Nginx test failed: {r.stderr}")
        return False
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    print("  Nginx reloaded")
    return True

def register(name, slug, category, url):
    data = json.load(open(PRODUCTS_FILE)) if os.path.exists(PRODUCTS_FILE) else {"products": []}
    ids = [int(p["id"].replace("P","")) for p in data["products"]]
    pid = f"P{(max(ids)+1):04d}" if ids else "P0006"
    data["products"].append({"id": pid, "name": name, "slug": slug, "url": url, "status": "live", "category": category, "etsy_listing": "pending"})
    data["updated"] = datetime.now().strftime("%Y-%m-%d")
    json.dump(data, open(PRODUCTS_FILE, "w"), indent=2)
    print(f"  Registered as {pid}")
    return pid

def build(category_data, force_slug=None):
    name = category_data.get("suggested_product_name", "")
    category = category_data.get("category", "")
    pain = category_data.get("pain_summary", "")
    slug = force_slug or generate_slug()
    storage_key = name.lower().replace(" ", "_")

    print(f"\nForge building: {name}")
    print(f"  Slug: {slug}")

    # Pass 1 — HTML + CSS
    print("  Pass 1: Generating HTML structure...")
    html_prompt = HTML_PROMPT.replace("{NAME}", name).replace("{CATEGORY}", category).replace("{PAIN}", pain)
    html = clean_code(call_claude(html_prompt, max_tokens=32000))

    issues = qa_check(html)
    if issues:
        print(f"  HTML issues: {issues}")
        send_telegram(f"Forge WARNING: HTML issues for *{name}*:\n" + "\n".join(issues))
        return

    print(f"  HTML: {len(html):,} chars")

    # Extract structure for JS generation
    sections = extract_sections(html)
    data_types = extract_data_types(html)
    required_fns = extract_onclick_fns(html)
    element_ids = extract_element_ids(html)
    print(f"  Sections: {sections}")
    print(f"  Data types: {data_types}")
    print(f"  Required fns ({len(required_fns)}): {required_fns}")
    print(f"  Element ids ({len(element_ids)})")

    # Pass 2 — JavaScript
    print("  Pass 2: Generating JavaScript...")
    js_prompt = JS_PROMPT.replace("{NAME}", name).replace("{STORAGE_KEY}", storage_key)
    js_prompt = js_prompt.replace("{SECTIONS}", str(sections)).replace("{DATA_TYPES}", str(data_types))
    js_prompt = js_prompt.replace("{REQUIRED_FNS}", "\n".join(f"  - {fn}" for fn in required_fns))
    js_prompt = js_prompt.replace("{ELEMENT_IDS}", ", ".join(element_ids) if element_ids else "(none)")
    js = clean_code(call_claude(js_prompt, max_tokens=32000), "js")

    # Inject JS into HTML
    final_html = html.replace(
        '<script id="app-script"></script>',
        f'<script id="app-script">\n{js}\n</script>'
    )

    # Final QA
    missing_fns = []
    onclick_calls = set(re.findall(r'onclick="(\w+)\(', final_html))
    for fn in onclick_calls:
        if fn not in js:
            missing_fns.append(fn)

    if missing_fns:
        print(f"  WARNING: Missing JS functions: {missing_fns}")
    else:
        print(f"  JS QA: all {len(onclick_calls)} functions present")

    # ------------------------------------------------------------------
    # Functional QA — mandatory deploy gate.
    #
    # Boots the candidate HTML in jsdom and exercises the real flows
    # (navigation, form save, render-after-save, persistence, delete,
    # export). If the build fails any *critical* test we refuse to
    # deploy, send a Telegram alert with the failures, and return.
    #
    # "Critical" = Navigation, Form save, Render after save. The
    # Persistence/Delete/Export tests are warned-on but not blocking —
    # forge-generated apps occasionally have sub-flow quirks that don't
    # warrant blocking shipment, and our test coverage of them isn't
    # tight enough to be authoritative on its own.
    # ------------------------------------------------------------------
    print("  Functional QA: running jsdom-based gate…")
    try:
        run_functional_qa = _import_qa()
        with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as tf:
            tf.write(final_html)
            qa_html_path = tf.name
        try:
            qa = run_functional_qa(slug, html_path=qa_html_path, timeout=90)
        finally:
            try: os.unlink(qa_html_path)
            except OSError: pass
    except Exception as e:
        # If the QA infra itself is broken, fail closed.
        msg = f"Forge QA INFRA FAILURE for *{name}* — refusing to deploy.\n{e}"
        print(msg)
        send_telegram(msg)
        return

    BLOCKING = {"Navigation", "Form save", "Render after save"}
    blocking_fails = [t for t in qa.get("tests", []) if not t.get("ok") and t.get("name") in BLOCKING]
    other_fails = [t for t in qa.get("tests", []) if not t.get("ok") and t.get("name") not in BLOCKING]

    if blocking_fails:
        bullet = "\n".join(f"  ✗ {t['name']} — {t.get('detail', '')}" for t in blocking_fails)
        print(f"  QA FAILED — not deploying {name}")
        print(bullet)
        send_telegram(f"Forge QA FAILED for *{name}* — not deployed:\n{bullet}")
        return

    if other_fails:
        warn = "; ".join(f"{t['name']}: {t.get('detail','')}" for t in other_fails)
        print(f"  QA: critical tests passed; non-blocking warnings — {warn}")
    else:
        print(f"  QA: all functional tests passed")

    deploy(slug, final_html)
    add_nginx_route(slug, name)

    if not reload_nginx():
        send_telegram(f"Forge ERROR: Nginx reload failed for *{name}*")
        return

    url = f"https://app.clearfolks.com/{slug}"
    pid = register(name, slug, category, url)

    with open(f"{LOGS_DIR}/forge.log", "a") as log:
        log.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: [{pid}] {name} → {url} | missing_fns: {missing_fns}\n")

    send_telegram(
        f"*Forge: {pid} live*\n\n*{name}*\n{url}\n\n"
        + (f"⚠️ Missing functions: {missing_fns}" if missing_fns else "✓ All JS functions present")
    )
    print(f"\nDone. {pid} at {url}")

def load_categories():
    with open(CATEGORIES_FILE) as f:
        return json.load(f)

def main():
    if len(sys.argv) < 2 or sys.argv[1] == "--list":
        data = load_categories()
        print("BUILD categories:")
        for c in data["categories"]:
            if c["verdict"] == "build":
                print(f"  - {c['suggested_product_name']}")
        sys.exit(0)

    data = load_categories()

    if sys.argv[1] == "--next":
        builds = [c for c in data["categories"] if c["verdict"] == "build"]
        if not builds:
            print("No BUILD categories")
            sys.exit(1)
        build(builds[0])
    elif sys.argv[1] == "--rebuild-caregiver":
        target = next((c for c in data["categories"] if c.get("suggested_product_name") == "Caregiver Command Center"), None)
        if target:
            build(target, force_slug="caregiver")
        else:
            print("Caregiver not found in categories")
    else:
        name = " ".join(sys.argv[1:])
        target = next((c for c in data["categories"] if c.get("suggested_product_name","").lower() == name.lower()), None)
        if not target:
            print(f"'{name}' not found. Run --list to see options.")
            sys.exit(1)
        build(target)

if __name__ == "__main__":
    main()
