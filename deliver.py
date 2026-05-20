#!/usr/bin/env python3
"""Deliver — generate the branded buyer-delivery PDF for a single product.

Matches the reference design in Downloads/buyer_pdfs/06_IEP_Parent_Binder_App.pdf:
navy header with orange underline → teal "DIGITAL APP" pill → bold title with
orange underline → teal tagline → two columns (QR card | numbered install
steps) → What's included bullets (teal dots) → support block → orange footer.

Usage:
    python3 deliver.py "Baby Tracker & Postpartum App" \
        "Tracked. Rested. Ready for what's next." \
        https://app.clearfolks.com/cf-q1d4697v \
        cf-q1d4697v

Writes: /root/clearfolks/delivery/<slug>-delivery.pdf
"""
import io
import os
import sys
from pathlib import Path

import qrcode
from reportlab.lib.colors import HexColor, white
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen import canvas

# ---------------------------------------------------------------------------
# Brand palette — extracted from the IEP reference PDF
# ---------------------------------------------------------------------------
NAVY   = HexColor("#1F3A5C")
CREAM  = HexColor("#F8F5EC")
TEAL   = HexColor("#2E8A85")
ORANGE = HexColor("#C8861F")
GRAY   = HexColor("#6B7280")
LIGHT_GRAY = HexColor("#D7D2C7")
WHITE  = white

PAGE_W, PAGE_H = LETTER  # 612 x 792

HEADER_H = 72
FOOTER_H = 36
MARGIN_X = 54


def qr_png_bytes(data: str, pixel_color="#1F3A5C") -> bytes:
    q = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=10,
        border=2,
    )
    q.add_data(data)
    q.make(fit=True)
    img = q.make_image(fill_color=pixel_color, back_color="white").convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def draw_header(c: canvas.Canvas):
    c.setFillColor(NAVY)
    c.rect(0, PAGE_H - HEADER_H, PAGE_W, HEADER_H, fill=1, stroke=0)

    # Brand wordmark
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(MARGIN_X, PAGE_H - HEADER_H + 28, "Clearfolks")

    # Orange accent underline under wordmark
    c.setFillColor(ORANGE)
    c.rect(MARGIN_X, PAGE_H - HEADER_H + 22, 78, 2.5, fill=1, stroke=0)

    # Top-right: clearfolks.com
    c.setFillColor(HexColor("#B8C5D5"))  # muted
    c.setFont("Helvetica", 10)
    c.drawRightString(PAGE_W - MARGIN_X, PAGE_H - HEADER_H + 28, "clearfolks.com")


def draw_footer(c: canvas.Canvas):
    c.setFillColor(ORANGE)
    c.rect(0, 0, PAGE_W, FOOTER_H, fill=1, stroke=0)

    c.setFillColor(WHITE)
    c.setFont("Helvetica", 10)
    text = "Clearfolks   —   Practical tools for life's complicated moments   —   clearfolks.com"
    c.drawCentredString(PAGE_W / 2, FOOTER_H / 2 - 3, text)


def draw_pill(c: canvas.Canvas, x, y, text):
    """Small teal rounded badge ('DIGITAL APP')."""
    c.setFont("Helvetica-Bold", 9)
    text_w = c.stringWidth(text, "Helvetica-Bold", 9)
    padding_x = 14
    padding_y = 7
    w = text_w + padding_x * 2
    h = 22
    c.setFillColor(TEAL)
    c.roundRect(x, y, w, h, 3, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.drawString(x + padding_x, y + padding_y, text)
    return w


def draw_title(c: canvas.Canvas, x, y, text):
    """Large navy bold title with a thick orange underline beneath."""
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 30)
    c.drawString(x, y, text)
    title_w = c.stringWidth(text, "Helvetica-Bold", 30)
    c.setFillColor(ORANGE)
    c.rect(x, y - 6, min(title_w, 260), 3, fill=1, stroke=0)


def draw_section_heading(c: canvas.Canvas, x, y, text, underline_width=130):
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(x, y, text)
    c.setFillColor(ORANGE)
    c.rect(x, y - 4, underline_width, 2, fill=1, stroke=0)


def draw_qr_card(c: canvas.Canvas, x, y, size, url):
    """White rounded card with QR and caption."""
    c.setFillColor(WHITE)
    c.setStrokeColor(LIGHT_GRAY)
    c.setLineWidth(1)
    c.roundRect(x, y - size, size, size, 8, fill=1, stroke=1)

    # "SCAN TO OPEN YOUR APP" caption above card
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 9)
    c.drawCentredString(x + size / 2, y + 10, "SCAN TO OPEN YOUR APP")

    # QR image inside card
    qr_img = ImageReader(io.BytesIO(qr_png_bytes(url)))
    qr_inset = 18
    qr_size = size - qr_inset * 2 - 16  # extra bottom room for URL text
    qr_x = x + (size - qr_size) / 2
    qr_y = y - size + 32  # bottom-anchored, leaving room for URL below
    c.drawImage(qr_img, qr_x, qr_y, qr_size, qr_size, preserveAspectRatio=True, mask="auto")

    # URL under QR
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 8.5)
    c.drawCentredString(x + size / 2, y - size + 14, url)


def draw_numbered_step(c: canvas.Canvas, x, y, n, title, subtitle):
    # Navy circle with white number
    c.setFillColor(NAVY)
    r = 11
    c.circle(x + r, y, r, fill=1, stroke=0)
    c.setFillColor(WHITE)
    c.setFont("Helvetica-Bold", 11)
    c.drawCentredString(x + r, y - 3.5, str(n))

    # Title
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x + r * 2 + 12, y + 2, title)

    # Subtitle
    c.setFillColor(GRAY)
    c.setFont("Helvetica", 10)
    c.drawString(x + r * 2 + 12, y - 12, subtitle)


def draw_bullets(c: canvas.Canvas, x, y, items, line_gap=19):
    for i, item in enumerate(items):
        cy = y - i * line_gap
        # Teal dot
        c.setFillColor(TEAL)
        c.circle(x + 4, cy + 3, 3.2, fill=1, stroke=0)
        # Text
        c.setFillColor(NAVY)
        c.setFont("Helvetica", 11)
        c.drawString(x + 18, cy, item)


def draw_support_block(c: canvas.Canvas, x, y):
    # Thin separator above
    c.setStrokeColor(LIGHT_GRAY)
    c.setLineWidth(0.8)
    c.line(x, y + 20, PAGE_W - MARGIN_X, y + 20)

    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(x, y, "Questions or issues?")

    c.setFillColor(GRAY)
    c.setFont("Helvetica", 10.5)
    c.drawString(x, y - 16, "Message us on Etsy and we will respond within 24 hours.")

    c.setFillColor(TEAL)
    c.setFont("Helvetica", 10.5)
    c.drawString(x, y - 32, "https://www.etsy.com/shop/clearfolk")


def build(product_name: str, tagline: str, url: str, out_path: Path):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(out_path), pagesize=LETTER)

    # Cream background for the body area
    c.setFillColor(CREAM)
    c.rect(0, FOOTER_H, PAGE_W, PAGE_H - HEADER_H - FOOTER_H, fill=1, stroke=0)

    draw_header(c)
    draw_footer(c)

    # --- Top of body area ---
    body_top = PAGE_H - HEADER_H  # 720

    # DIGITAL APP pill
    draw_pill(c, MARGIN_X, body_top - 50, "DIGITAL APP")

    # Title
    title_y = body_top - 100
    draw_title(c, MARGIN_X, title_y, product_name)

    # Tagline
    c.setFillColor(TEAL)
    c.setFont("Helvetica", 12)
    c.drawString(MARGIN_X, title_y - 24, tagline)

    # Two-column area
    cols_top = title_y - 54
    qr_size = 216
    draw_qr_card(c, MARGIN_X, cols_top, qr_size, url)

    # Steps column — right of QR card
    steps_x = MARGIN_X + qr_size + 28
    steps_top = cols_top
    c.setFillColor(NAVY)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(steps_x, steps_top, "3 steps to install")

    steps = [
        ("Open Safari on your iPhone", "Or any browser on Android"),
        ("Visit the link or scan the QR code", "The app loads in your browser"),
        ('Tap Share → "Add to Home Screen"', "Tap Add. Done. It's on your home screen."),
    ]
    first_step_y = steps_top - 30
    step_gap = 48
    for i, (title, sub) in enumerate(steps):
        draw_numbered_step(c, steps_x, first_step_y - i * step_gap, i + 1, title, sub)

    # What's included
    included_y = cols_top - qr_size - 36
    draw_section_heading(c, MARGIN_X, included_y, "What's included", underline_width=128)
    draw_bullets(c, MARGIN_X, included_y - 26, [
        "Works on iPhone, Android, iPad, and desktop",
        "Add to home screen like a native app",
        "Works completely offline after first load",
        "Data saves automatically on your device",
        "Free lifetime updates",
    ])

    # Support block near bottom
    draw_support_block(c, MARGIN_X, 100)

    c.showPage()
    c.save()
    return out_path


def main():
    if len(sys.argv) != 5:
        print("Usage: deliver.py <product_name> <tagline> <url> <slug>")
        sys.exit(2)
    name, tagline, url, slug = sys.argv[1:5]
    out = Path(os.environ.get("CLEARFOLKS_HOME", "/root/clearfolks")) / "delivery" / f"{slug}-delivery.pdf"
    build(name, tagline, url, out)
    size = out.stat().st_size
    print(f"Wrote {out} ({size:,} bytes)")


if __name__ == "__main__":
    main()
