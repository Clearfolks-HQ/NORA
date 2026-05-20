#!/usr/bin/env python3
"""
generate_pin_images.py — Build 12 branded 1000x1500 Pinterest pin images.

Saves to /root/clearfolks/static/pin-images/{cluster}.png

Brand palette:
  navy   #1a2744   deep panel background
  cream  #f7f4ee   primary text
  rust   #b85c38   accent bars + clearfolks.com line
  cream2 #ede9df   secondary tagline
  muted  #a8a49e   reserved
  panel  #0f1829   bottom-third dark panel

Fonts:
  Playfair Display Bold   — headlines        (downloaded into static/fonts/)
  Playfair Display Italic — taglines         (downloaded into static/fonts/)
  DejaVu Sans Bold        — CLEARFOLKS wordmark + bottom panel copy (system)
  Noto Color Emoji        — cluster glyph    (system, native 109pt bitmap)
"""

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

BASE        = Path("/root/clearfolks")
FONTS_DIR   = BASE / "static" / "fonts"
OUT_DIR     = BASE / "static" / "pin-images"

NAVY   = (26, 39, 68)       # #1a2744
CREAM  = (247, 244, 238)    # #f7f4ee
RUST   = (184, 92, 56)      # #b85c38
CREAM2 = (237, 233, 223)    # #ede9df
MUTED  = (168, 164, 158)    # #a8a49e
PANEL  = (15, 24, 41)       # #0f1829

W, H = 1000, 1500

FONT_HEADLINE = str(FONTS_DIR / "PlayfairDisplay-Bold.ttf")
FONT_ITALIC   = str(FONTS_DIR / "PlayfairDisplay-Italic.ttf")
FONT_SANS     = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_EMOJI    = "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"

CLUSTERS = {
    "caregiver": {
        "headline": "Caring for Someone\nYou Love\nWithout Losing Yourself",
        "tagline":  "Practical tools for family caregivers",
        "emoji":    "🤍",
    },
    "medication": {
        "headline": "Never Miss\nAnother\nMedication",
        "tagline":  "Track every dose, every doctor, every refill",
        "emoji":    "💊",
    },
    "iep": {
        "headline": "Walk Into\nEvery IEP Meeting\nPrepared",
        "tagline":  "Advocate confidently for your child",
        "emoji":    "📋",
    },
    "etsy-seller": {
        "headline": "Run Your\nEtsy Shop\nWithout the Chaos",
        "tagline":  "Inventory, finances, growth in one place",
        "emoji":    "🛍️",
    },
    "wedding": {
        "headline": "Plan Your\nWedding Without\nthe Overwhelm",
        "tagline":  "Calm, organised, from yes to I do",
        "emoji":    "🤍",
    },
    "baby": {
        "headline": "Survive the\nNewborn Stage\nWith Sanity Intact",
        "tagline":  "Tracking tools for exhausted new parents",
        "emoji":    "🍼",
    },
    "homeschool": {
        "headline": "Homeschool\nWithout the\nSpreadsheet Nightmare",
        "tagline":  "Planning that actually works for real families",
        "emoji":    "📚",
    },
    "pet-care": {
        "headline": "Keep Your\nPet Healthy\nand Organised",
        "tagline":  "Vet records, vaccines, meds in one place",
        "emoji":    "🐾",
    },
    "meal-planning": {
        "headline": "End the\nWhat's For Dinner\nSpiral Forever",
        "tagline":  "Meal planning that sticks for busy households",
        "emoji":    "🥗",
    },
    "moving": {
        "headline": "Move Without\nLosing Your\nMind",
        "tagline":  "Checklists and systems for a smoother move",
        "emoji":    "📦",
    },
    "travel": {
        "headline": "Travel That\nActually Goes\nTo Plan",
        "tagline":  "Itineraries, documents, budgets organised",
        "emoji":    "✈️",
    },
    "generic": {
        "headline": "Run Your\nHousehold\nLike a Pro",
        "tagline":  "Practical systems for life's complicated moments",
        "emoji":    "🏠",
    },
}


def text_width(draw, text, font):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0]


def draw_centered(draw, y, text, font, color):
    w = text_width(draw, text, font)
    draw.text(((W - w) / 2, y), text, font=font, fill=color)


def draw_letter_spaced(draw, y, text, font, color, tracking=8):
    """Draw text centered horizontally with extra spacing between letters."""
    glyph_widths = [text_width(draw, ch, font) for ch in text]
    total = sum(glyph_widths) + tracking * (len(text) - 1)
    x = (W - total) / 2
    for ch, gw in zip(text, glyph_widths):
        draw.text((x, y), ch, font=font, fill=color)
        x += gw + tracking


def draw_emoji(img, emoji_char, cy):
    """
    Render an emoji to a transparent RGBA tile at Noto Color Emoji's native
    109pt bitmap size, scale it to ~150px wide, then paste centered at cy.
    """
    native = 109
    target = 150
    tile = Image.new("RGBA", (native * 2, native * 2), (0, 0, 0, 0))
    td = ImageDraw.Draw(tile)
    font = ImageFont.truetype(FONT_EMOJI, native)
    td.text((10, 10), emoji_char, font=font, embedded_color=True)
    # crop to non-transparent bounds for clean placement
    bbox = tile.getbbox()
    if bbox:
        tile = tile.crop(bbox)
    # scale preserving aspect, fit within target × target
    tw, th = tile.size
    scale = target / max(tw, th)
    new_size = (max(1, int(tw * scale)), max(1, int(th * scale)))
    tile = tile.resize(new_size, Image.LANCZOS)
    x = (W - tile.size[0]) // 2
    img.paste(tile, (x, cy - tile.size[1] // 2), tile)


def build_pin(cluster, data):
    img = Image.new("RGB", (W, H), NAVY)
    draw = ImageDraw.Draw(img)

    # ── Top section ──────────────────────────────────────────────────────
    wordmark_font = ImageFont.truetype(FONT_SANS, 28)
    draw_letter_spaced(draw, 105, "CLEARFOLKS", wordmark_font, CREAM, tracking=10)
    # rust accent bar at y=180, 6px tall, full width
    draw.rectangle([(0, 180), (W, 186)], fill=RUST)

    # ── Middle section ───────────────────────────────────────────────────
    # Emoji centered at y=320 (vertical center)
    draw_emoji(img, data["emoji"], 320)

    # Headline — autoscale font size so the longest line fits within 880px
    lines = data["headline"].split("\n")
    headline_size = 80
    while headline_size > 56:
        f = ImageFont.truetype(FONT_HEADLINE, headline_size)
        max_w = max(text_width(draw, ln, f) for ln in lines)
        if max_w <= 880:
            break
        headline_size -= 2
    headline_font = ImageFont.truetype(FONT_HEADLINE, headline_size)
    line_height = int(headline_size * 1.15)

    # Vertically position headline block so it sits ~y=460..760 area
    block_h = line_height * len(lines)
    headline_top = 460
    y = headline_top
    for ln in lines:
        draw_centered(draw, y, ln, headline_font, CREAM)
        y += line_height
    headline_bottom = headline_top + block_h

    # Tagline — italic, 36pt, autoscale down if too wide
    tagline_size = 36
    while tagline_size > 26:
        tf = ImageFont.truetype(FONT_ITALIC, tagline_size)
        if text_width(draw, data["tagline"], tf) <= 880:
            break
        tagline_size -= 2
    tagline_font = ImageFont.truetype(FONT_ITALIC, tagline_size)
    tagline_y = headline_bottom + 40
    draw_centered(draw, tagline_y, data["tagline"], tagline_font, CREAM2)

    # Rust accent line — 200px wide, 3px tall, centered below tagline
    accent_y = tagline_y + tagline_size + 50
    draw.rectangle([((W - 200) / 2, accent_y), ((W + 200) / 2, accent_y + 3)], fill=RUST)

    # ── Bottom panel ─────────────────────────────────────────────────────
    draw.rectangle([(0, 1100), (W, H)], fill=PANEL)

    # Three subtle decorative dots
    dot_y = 1170
    for i, dx in enumerate((-32, 0, 32)):
        cx = W // 2 + dx
        r = 3
        draw.ellipse([(cx - r, dot_y - r), (cx + r, dot_y + r)], fill=RUST if i == 1 else MUTED)

    brand_font = ImageFont.truetype(FONT_SANS, 32)
    draw_centered(draw, 1220, "The organized friend you wished you had", brand_font, CREAM)

    url_font = ImageFont.truetype(FONT_SANS, 28)
    draw_centered(draw, 1290, "clearfolks.com", url_font, RUST)

    out_path = OUT_DIR / f"{cluster}.png"
    img.save(out_path, "PNG", optimize=True)
    return out_path


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"Generating {len(CLUSTERS)} pin images → {OUT_DIR}")
    for cluster, data in CLUSTERS.items():
        path = build_pin(cluster, data)
        size_kb = path.stat().st_size // 1024
        print(f"  ✓ {cluster:<14} {size_kb}KB  {path.name}")
    print(f"\nDone. {len(CLUSTERS)} images saved.")


if __name__ == "__main__":
    main()
