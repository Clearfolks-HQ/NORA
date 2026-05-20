#!/usr/bin/env python3
"""
QA Agent — functional test suite for the Clearfolks PWAs.

This is the second-generation qa.py. The first generation only grep'd for
function names in HTML, which let "Save button does nothing" bugs through —
the grep saw `function saveVendor` but never proved it grew state or that
the rendered list updated. This rewrite shells out to qa_runner.js (Node +
jsdom), which boots each PWA's actual page, runs its actual JS, and exercises
real flows: navigation, form save, render-after-save, persistence, delete,
and export.

Two callable surfaces:

    # CLI — same human-readable summary as the previous qa.py
    python3 qa.py

    # Programmatic — Forge calls this before deploy()
    from qa import run_functional_qa
    result = run_functional_qa(slug, html_path)
    if not result["passed"]: ...

The runner needs a jsdom install at /tmp/node_modules/jsdom (already present
on the droplet from earlier work; the runner will print a clear error if it
ever goes missing).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

CLEARFOLKS_HOME = Path(os.environ.get("CLEARFOLKS_HOME", "/root/clearfolks"))
PRODUCTS_FILE = CLEARFOLKS_HOME / "products.json"
WWW_ROOT = "/var/www/clearfolk"
QA_RUNNER = CLEARFOLKS_HOME / "qa_runner.js"


def run_functional_qa(slug: str, html_path: str | None = None, timeout: int = 60) -> dict:
    """Run the jsdom-based test suite against a single product.

    Returns a dict shaped like:
        {
            "slug": "<slug>",
            "passed": True|False,
            "tests": [{"name": "Navigation", "ok": True, "detail": "…"}, …],
            "failures": ["Form save — …", …],   # convenience flat list
            "error": "<runner-level error>"     # only on infra failure
        }
    """
    cmd = ["node", str(QA_RUNNER), "--slug", slug, "--json"]
    if html_path:
        cmd += ["--html", html_path]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"slug": slug, "passed": False, "tests": [], "failures": [f"Runner timeout after {timeout}s"], "error": "timeout"}
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return {
            "slug": slug,
            "passed": False,
            "tests": [],
            "failures": [proc.stderr.strip() or proc.stdout.strip() or "runner emitted no JSON"],
            "error": "json_decode",
        }
    data.setdefault("failures", [])
    for t in data.get("tests", []):
        if not t.get("ok"):
            data["failures"].append(f"{t['name']} — {t.get('detail', 'failed')}")
    return data


def print_human(result: dict, product_meta: dict | None = None) -> None:
    flag = "PASS" if result.get("passed") else "FAIL"
    label = product_meta["name"] if product_meta else result.get("slug", "")
    pid = product_meta["id"] if product_meta else ""
    print(f"[{flag}] {pid}{' — ' if pid else ''}{label}")
    if product_meta and "url" in product_meta:
        print(f"  URL: {product_meta['url']}")
    for t in result.get("tests", []):
        mark = "✓" if t.get("ok") else "✗"
        print(f"  {mark} {t['name']} — {t.get('detail', '')}")
    if result.get("error"):
        print(f"  !! runner error: {result['error']}")
    print()


def main():
    parser = argparse.ArgumentParser(description="Functional QA for Clearfolks PWAs")
    parser.add_argument("--slug", help="check only this slug (default: all from products.json)")
    parser.add_argument("--html", help="alternate index.html path (forge pre-deploy gate)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    parser.add_argument("--timeout", type=int, default=60, help="per-product runner timeout (s)")
    args = parser.parse_args()

    if not QA_RUNNER.exists():
        print(f"ERROR: qa_runner.js missing at {QA_RUNNER}", file=sys.stderr)
        sys.exit(2)

    if args.slug:
        products = [{"slug": args.slug, "name": args.slug, "id": "", "url": ""}]
    else:
        if not PRODUCTS_FILE.exists():
            print(f"ERROR: {PRODUCTS_FILE} not found", file=sys.stderr)
            sys.exit(2)
        products = json.loads(PRODUCTS_FILE.read_text())["products"]

    print(f"QA checking {len(products)} product(s)...\n")

    results = []
    for p in products:
        slug = p["slug"]
        html = args.html or f"{WWW_ROOT}/{slug}/index.html"
        r = run_functional_qa(slug, html_path=html, timeout=args.timeout)
        r["product"] = {"id": p.get("id", ""), "name": p.get("name", slug), "url": p.get("url", "")}
        results.append(r)
        if not args.json:
            print_human(r, r["product"])

    passed = sum(1 for r in results if r.get("passed"))
    failed = len(results) - passed
    if not args.json:
        print("=" * 60)
        print(f"Results: {passed} passed, {failed} failed\n")
        if failed == 0:
            print("All products passed functional QA.")
        else:
            print("Fix functional failures before listing on Etsy.")

    report = CLEARFOLKS_HOME / "logs" / "qa-report.json"
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(results, indent=2))
    if not args.json:
        print(f"\nReport saved: {report}")
    else:
        print(json.dumps(results, indent=2))

    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
