#!/usr/bin/env python3
"""Mockup — render the 5 Etsy listing images for a single product.

Output: /root/clearfolks/mockups/<slug>/image-{1..5}.png (each 2000x2000).
Uses the same brand palette as deliver.py so delivery PDF + listing images
read as one system.
"""
import os
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

sys.path.insert(0, str(Path(__file__).parent))
import brand

SCREENSHOTS = Path(os.environ.get("CLEARFOLKS_HOME", "/root/clearfolks")) / "screenshots"


def _load_screenshot(slug: str, suffix: str = "mobile"):
    """Return PIL.Image if <slug>-<suffix>.png exists, else None."""
    p = SCREENSHOTS / f"{slug}-{suffix}.png"
    if not p.exists():
        return None
    try:
        return Image.open(p).convert("RGB")
    except Exception:
        return None


def _rounded_mask(size, radius):
    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size[0], size[1]), radius=radius, fill=255)
    return mask

# ---------------------------------------------------------------------------
# Brand palette (RGB)
# ---------------------------------------------------------------------------
NAVY   = (31, 58, 92)
NAVY_D = (18, 40, 68)
CREAM  = (248, 245, 236)
TEAL   = (46, 138, 133)
TEAL_D = (30, 110, 106)
ORANGE = (200, 134, 31)
GRAY   = (107, 114, 128)
GRAY_L = (215, 210, 199)
WHITE  = (255, 255, 255)

SIZE = 2000
FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def f(size: int, bold=False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def text_w(draw, text, font) -> int:
    l, _t, r, _b = draw.textbbox((0, 0), text, font=font)
    return r - l


def draw_pill(draw, xy, text, *, font, bg=TEAL, fg=WHITE, padding=(30, 14), radius=10):
    x, y = xy
    w = text_w(draw, text, font) + padding[0] * 2
    tl, tt, tr, tb = draw.textbbox((0, 0), text, font=font)
    h = (tb - tt) + padding[1] * 2
    draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=bg)
    draw.text((x + padding[0], y + padding[1] - tt), text, font=font, fill=fg)
    return w, h


def wrap(draw, text, font, max_w):
    words = text.split()
    lines, line = [], ""
    for w in words:
        trial = (line + " " + w).strip()
        if text_w(draw, trial, font) <= max_w:
            line = trial
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    return lines


def draw_wordmark(draw, xy, *, color=WHITE, accent=ORANGE, size=64):
    x, y = xy
    font = f(size, bold=True)
    draw.text((x, y), "Clearfolks", font=font, fill=color)
    tw = text_w(draw, "Clearfolks", font)
    draw.rectangle((x, y + size + 14, x + tw * 0.55, y + size + 22), fill=accent)


# ---------------------------------------------------------------------------
# Phone mockup — rounded-corner frame with a synthesized dashboard inside.
# Dashboard contents are per-product (looked up in brand.DASHBOARDS by slug).
# ---------------------------------------------------------------------------
_ACCENT_MAP = {"navy": NAVY, "teal": TEAL, "orange": ORANGE}


def draw_phone(img: Image.Image, top_left, slug: str, phone_w=540, phone_h=1100):
    """Render a phone frame. If a live screenshot exists for `slug`, composite
    it inside the screen area; otherwise fall back to the synthetic dashboard
    driven by brand.DASHBOARDS."""
    from PIL import ImageFilter

    draw = ImageDraw.Draw(img)
    x, y = top_left
    bezel = 14
    radius = 72
    screen_radius = 58

    # Shadow
    shadow = Image.new("RGBA", (phone_w + 80, phone_h + 80), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((40, 40, phone_w + 40, phone_h + 40), radius=radius, fill=(0, 0, 0, 70))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=18))
    img.paste(shadow, (x - 40, y - 30), shadow)

    # Phone body
    draw.rounded_rectangle((x, y, x + phone_w, y + phone_h), radius=radius, fill=NAVY_D)
    sx, sy = x + bezel, y + bezel
    sw, sh = phone_w - bezel * 2, phone_h - bezel * 2

    shot = _load_screenshot(slug, "mobile")
    if shot is not None:
        # Fit the screenshot into the screen area with cover-crop semantics,
        # then apply a rounded-corner mask so it sits cleanly inside the bezel.
        sized = ImageOps.fit(shot, (int(sw), int(sh)), method=Image.LANCZOS)
        mask = _rounded_mask((int(sw), int(sh)), int(screen_radius))
        img.paste(sized, (int(sx), int(sy)), mask)
        # Faint notch pill to sell the phone shape
        notch_w, notch_h = 160, 28
        nx = sx + (sw - notch_w) / 2
        draw.rounded_rectangle((nx, sy + 12, nx + notch_w, sy + 12 + notch_h), radius=14, fill=NAVY_D)
        return

    # ---------- Fallback: synthetic dashboard (no screenshot available) ----
    dash = brand.for_slug(slug)
    accents = [_ACCENT_MAP.get(c, TEAL) for c in dash.accent_cycle]

    draw.rounded_rectangle((sx, sy, sx + sw, sy + sh), radius=screen_radius, fill=CREAM)
    draw.text((sx + 28, sy + 22), "9:41", font=f(24, bold=True), fill=NAVY)
    notch_w, notch_h = 180, 34
    nx = sx + (sw - notch_w) / 2
    draw.rounded_rectangle((nx, sy + 14, nx + notch_w, sy + 14 + notch_h), radius=18, fill=NAVY_D)

    hy = sy + 80
    draw.text((sx + 28, hy), dash.app_title, font=f(40, bold=True), fill=NAVY)
    draw.text((sx + 28, hy + 52), dash.subtitle, font=f(20), fill=GRAY)

    grid_x = sx + 28
    grid_y = hy + 120
    card_w = (sw - 28 * 2 - 20) / 2
    card_h = 180
    for i, (label, value) in enumerate(dash.stats[:4]):
        row, col = i // 2, i % 2
        cx = grid_x + col * (card_w + 20)
        cy = grid_y + row * (card_h + 20)
        draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h), radius=20, fill=WHITE, outline=GRAY_L, width=2)
        draw.text((cx + 20, cy + 22), label, font=f(20), fill=GRAY)
        vsz = 72 if len(str(value)) <= 4 else (58 if len(str(value)) <= 6 else 44)
        draw.text((cx + 20, cy + 60), str(value), font=f(vsz, bold=True),
                  fill=accents[i] if i < len(accents) else TEAL)

    nav_y = sy + sh - 100
    draw.rounded_rectangle((sx + 20, nav_y, sx + sw - 20, nav_y + 80), radius=40, fill=WHITE, outline=GRAY_L, width=2)
    icons = dash.nav_icons[:5] if dash.nav_icons else ["📊", "📝", "📅", "🔖", "⭐"]
    slot = (sw - 40) / len(icons)
    for i, ic in enumerate(icons):
        cx = sx + 20 + slot * i + slot / 2
        color = TEAL if i == 0 else GRAY
        draw.text((cx - 18, nav_y + 18), ic, font=f(36), fill=color)


# ---------------------------------------------------------------------------
# Image builders
# ---------------------------------------------------------------------------
def image_hero(product: str, tagline: str, slug: str = "") -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), NAVY)
    draw = ImageDraw.Draw(img)

    # Soft diagonal gradient blob for depth
    blob = Image.new("RGBA", (SIZE, SIZE), (0, 0, 0, 0))
    bd = ImageDraw.Draw(blob)
    bd.ellipse((-400, -400, 1200, 1200), fill=(46, 138, 133, 90))
    from PIL import ImageFilter
    blob = blob.filter(ImageFilter.GaussianBlur(radius=200))
    img = Image.alpha_composite(img.convert("RGBA"), blob).convert("RGB")
    draw = ImageDraw.Draw(img)

    draw_wordmark(draw, (110, 110), color=WHITE, accent=ORANGE, size=64)
    draw.text((SIZE - 110 - text_w(draw, "clearfolks.com", f(36)), 140),
              "clearfolks.com", font=f(36), fill=(200, 210, 225))

    # DIGITAL APP pill
    draw_pill(draw, (110, 320), "DIGITAL APP", font=f(34, bold=True), bg=TEAL)

    # Title (wrap to fit)
    title_font = f(150, bold=True)
    lines = wrap(draw, product, title_font, SIZE - 220 - 560)  # reserve phone space
    ty = 430
    for ln in lines:
        draw.text((110, ty), ln, font=title_font, fill=WHITE)
        ty += 160

    # Orange underline
    draw.rectangle((110, ty + 10, 110 + 220, ty + 24), fill=ORANGE)

    # Tagline
    draw.text((110, ty + 60), tagline, font=f(52), fill=TEAL)

    # Phone mockup anchored right — dashboard contents driven by slug
    draw_phone(img, (SIZE - 660, 620), slug=slug, phone_w=540, phone_h=1100)

    # Footer
    footer_h = 120
    draw.rectangle((0, SIZE - footer_h, SIZE, SIZE), fill=ORANGE)
    draw.text((SIZE / 2, SIZE - footer_h + 38),
              "Clearfolks   —   Practical tools for life's complicated moments   —   clearfolks.com",
              font=f(32, bold=True), fill=WHITE, anchor="mt")

    return img


def image_features(slug: str = "") -> Image.Image:
    """Three real mobile screenshots side-by-side.

    Each card shows a different in-app section (Feed/Sleep/Milestones for Baby,
    etc.). If fewer than 3 section screenshots exist we fall back to three
    vertical thirds cropped from the desktop screenshot, and finally to the
    previous icon-based design if no screenshot exists at all.
    """
    img = Image.new("RGB", (SIZE, SIZE), WHITE)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, SIZE, 120), fill=NAVY)
    draw.text((SIZE / 2, 60), "Clearfolks", font=f(48, bold=True), fill=WHITE, anchor="mm")
    draw.text((SIZE / 2, 230), "See it in action",
              font=f(76, bold=True), fill=NAVY, anchor="mm")
    draw.text((SIZE / 2, 310), "Every section of the live app — exactly what you'll use.",
              font=f(36), fill=GRAY, anchor="mm")

    # Collect up to 3 section screenshots.
    section_shots = []
    for p in sorted(SCREENSHOTS.glob(f"{slug}-mobile-*.png")):
        try:
            raw = p.stem.rsplit("-mobile-", 1)[-1]
            # Normalize the label: some forge builds name containers
            # "pets-section" / "appointments-section" etc.; drop that suffix
            # so the caption dict below can match the bare verb.
            name = raw.replace("-section", "").strip("-")
            section_shots.append((name, Image.open(p).convert("RGB")))
        except Exception:
            continue
    # Drop the default landing view if present (redundant with hero).
    section_shots = [(n, im) for n, im in section_shots if n not in ("dashboard", "home", "overview")]
    section_shots = section_shots[:3]

    # Fill up from desktop if needed.
    if len(section_shots) < 3:
        desktop = _load_screenshot(slug, "desktop")
        if desktop is not None:
            w, h = desktop.size
            strip_w = w // 3
            for i in range(3 - len(section_shots)):
                x0 = i * strip_w
                section_shots.append((f"view-{i+1}", desktop.crop((x0, 0, x0 + strip_w, h))))

    # If we got nothing at all, fall back to old icon design.
    if not section_shots:
        return _image_features_icons_fallback()

    card_w, card_h = 520, 960
    total_w = card_w * 3 + 60 * 2
    start_x = (SIZE - total_w) / 2
    card_y = 420

    captions = {
        "feeding": "Feeding Log",  "feed": "Feeding Log",
        "sleep": "Sleep Tracker",
        "diapers": "Diaper Log",
        "milestones": "Milestones",
        "health": "Health & Meds",
        "postpartum": "Postpartum",
        "vendors": "Vendors",      "guests": "Guests",    "budget": "Budget",
        "schedule": "Schedule",    "assignments": "Assignments",
        "children": "Children",    "subjects": "Subjects",
        "pets": "Pets",            "medications": "Medications",
        "rooms": "Rooms",          "packing": "Packing",  "addresses": "Addresses",
        "timeline": "Timeline",    "itinerary": "Itinerary",
        "goals": "Goals",          "meetings": "Meetings",
        "questions": "Questions",  "actions": "Action Items",
        "sales": "Sales",          "listings": "Listings",
    }

    for i, (name, shot) in enumerate(section_shots[:3]):
        cx = start_x + i * (card_w + 60)
        # Phone-like rounded frame (no reserved bottom — caption goes below)
        draw.rounded_rectangle((cx, card_y, cx + card_w, card_y + card_h),
                               radius=42, fill=NAVY_D)
        inner = 10
        inner_w = card_w - inner * 2
        inner_h = card_h - inner * 2
        sized = ImageOps.fit(shot, (inner_w, inner_h), method=Image.LANCZOS)
        mask = _rounded_mask((inner_w, inner_h), 34)
        img.paste(sized, (int(cx + inner), int(card_y + inner)), mask)
        # Caption below the frame on white background
        caption = captions.get(name.lower(), name.replace("-", " ").title())
        cap_y = card_y + card_h + 48
        draw.text((cx + card_w / 2, cap_y), caption,
                  font=f(40, bold=True), fill=NAVY, anchor="mm")
        draw.rectangle((cx + card_w / 2 - 60, cap_y + 36, cx + card_w / 2 + 60, cap_y + 42),
                       fill=ORANGE)

    draw.rectangle((0, SIZE - 100, SIZE, SIZE), fill=ORANGE)
    draw.text((SIZE / 2, SIZE - 50), "clearfolks.com", font=f(32, bold=True), fill=WHITE, anchor="mm")
    return img


def _image_features_icons_fallback() -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), WHITE)
    draw = ImageDraw.Draw(img)
    draw.rectangle((0, 0, SIZE, 120), fill=NAVY)
    draw.text((SIZE / 2, 60), "Clearfolks", font=f(48, bold=True), fill=WHITE, anchor="mm")
    draw.text((SIZE / 2, 500), "Preview unavailable — run screenshot.py first.",
              font=f(40), fill=GRAY, anchor="mm")
    draw.rectangle((0, SIZE - 100, SIZE, SIZE), fill=ORANGE)
    draw.text((SIZE / 2, SIZE - 50), "clearfolks.com", font=f(32, bold=True), fill=WHITE, anchor="mm")
    return img


def image_how() -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), CREAM)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, SIZE, 120), fill=NAVY)
    draw.text((SIZE / 2, 60), "Clearfolks", font=f(48, bold=True), fill=WHITE, anchor="mm")

    draw.text((SIZE / 2, 230), "How it works",
              font=f(90, bold=True), fill=NAVY, anchor="mm")
    draw.rectangle((SIZE / 2 - 120, 290, SIZE / 2 + 120, 304), fill=ORANGE)
    draw.text((SIZE / 2, 360), "On your phone in under a minute.",
              font=f(36), fill=TEAL, anchor="mm")

    steps = [
        ("Visit the link",    "Open the URL or scan the QR code. The app loads in your browser — no install."),
        ("Add to Home Screen","Tap Share → Add to Home Screen. Instant icon on your phone."),
        ("Use it anywhere",   "Works offline after first load. Data stays on your device. No account needed."),
    ]
    sy = 540
    for i, (title, desc) in enumerate(steps):
        cy = sy + i * 360
        # Big numbered circle
        cr = 90
        cx = 240
        draw.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=NAVY)
        draw.text((cx, cy), str(i + 1), font=f(110, bold=True), fill=WHITE, anchor="mm")
        # Right column title + description. Title ascends from cy-80 (bottom
        # ~cy-18 at 62pt); description starts at cy+24 giving a clean ~40px gap.
        tx = cx + cr + 60
        draw.text((tx, cy - 80), title, font=f(62, bold=True), fill=NAVY)
        lines = wrap(draw, desc, f(38), SIZE - tx - 140)
        ly = cy + 24
        for ln in lines:
            draw.text((tx, ly), ln, font=f(38), fill=GRAY)
            ly += 52

    draw.rectangle((0, SIZE - 100, SIZE, SIZE), fill=ORANGE)
    draw.text((SIZE / 2, SIZE - 50), "clearfolks.com", font=f(32, bold=True), fill=WHITE, anchor="mm")
    return img


def image_included() -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), TEAL)
    draw = ImageDraw.Draw(img)

    # Subtle lighter block top
    draw.rectangle((0, 0, SIZE, 120), fill=TEAL_D)
    draw.text((SIZE / 2, 60), "Clearfolks", font=f(48, bold=True), fill=WHITE, anchor="mm")

    draw.text((SIZE / 2, 250), "What's included",
              font=f(100, bold=True), fill=WHITE, anchor="mm")
    draw.rectangle((SIZE / 2 - 140, 320, SIZE / 2 + 140, 336), fill=ORANGE)

    items = [
        "Works on iPhone, Android, iPad, and desktop",
        "Add to home screen like a native app",
        "Works completely offline after first load",
        "Data saves automatically on your device",
        "Free lifetime updates",
        "No accounts, no subscriptions, no ads",
    ]
    # Bullet list, centered block
    line_h = 90
    total_h = len(items) * line_h
    start_y = (SIZE - total_h) / 2 + 80
    max_w = 0
    for item in items:
        w = text_w(draw, item, f(44))
        max_w = max(max_w, w)

    list_left = (SIZE - (max_w + 90)) / 2  # include space for bullet
    for i, item in enumerate(items):
        y = start_y + i * line_h
        draw.ellipse((list_left, y + 22, list_left + 28, y + 50), fill=WHITE)
        draw.text((list_left + 56, y + 12), item, font=f(44), fill=WHITE)

    # Footer
    draw.rectangle((0, SIZE - 100, SIZE, SIZE), fill=ORANGE)
    draw.text((SIZE / 2, SIZE - 50),
              "Clearfolks — Practical tools for life's complicated moments",
              font=f(32, bold=True), fill=WHITE, anchor="mm")
    return img


def image_devices() -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE), WHITE)
    draw = ImageDraw.Draw(img)

    draw.rectangle((0, 0, SIZE, 120), fill=NAVY)
    draw.text((SIZE / 2, 60), "Clearfolks", font=f(48, bold=True), fill=WHITE, anchor="mm")

    draw.text((SIZE / 2, 240), "Works everywhere",
              font=f(100, bold=True), fill=NAVY, anchor="mm")
    draw.rectangle((SIZE / 2 - 180, 310, SIZE / 2 + 180, 324), fill=ORANGE)
    draw.text((SIZE / 2, 380), "Same app, every device. Your data stays with you.",
              font=f(36), fill=TEAL, anchor="mm")

    # Device tiles
    tiles = [
        ("iPhone",  _icon_iphone),
        ("Android", _icon_android),
        ("iPad",    _icon_ipad),
        ("Desktop", _icon_desktop),
    ]
    tile_w = 400
    tile_h = 520
    gap = 40
    total_w = tile_w * 4 + gap * 3
    start_x = (SIZE - total_w) / 2
    tile_y = 600
    for i, (label, icon_fn) in enumerate(tiles):
        tx = start_x + i * (tile_w + gap)
        draw.rounded_rectangle((tx, tile_y, tx + tile_w, tile_y + tile_h),
                               radius=30, fill=CREAM, outline=GRAY_L, width=2)
        icon_fn(draw, tx + tile_w / 2, tile_y + tile_h / 2 - 60)
        draw.text((tx + tile_w / 2, tile_y + tile_h - 90),
                  label, font=f(46, bold=True), fill=NAVY, anchor="mm")

    draw.rectangle((0, SIZE - 100, SIZE, SIZE), fill=ORANGE)
    draw.text((SIZE / 2, SIZE - 50), "One payment · Lifetime access",
              font=f(32, bold=True), fill=WHITE, anchor="mm")
    return img


# --- Simple vector-ish device icons -----------------------------------------
def _icon_iphone(draw, cx, cy):
    w, h = 150, 280
    draw.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
                           radius=28, fill=NAVY, outline=NAVY_D, width=3)
    draw.rounded_rectangle((cx - w / 2 + 12, cy - h / 2 + 18, cx + w / 2 - 12, cy + h / 2 - 18),
                           radius=18, fill=TEAL)
    draw.rounded_rectangle((cx - 30, cy - h / 2 + 8, cx + 30, cy - h / 2 + 22),
                           radius=7, fill=NAVY_D)

def _icon_android(draw, cx, cy):
    w, h = 150, 280
    draw.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
                           radius=20, fill=NAVY, outline=NAVY_D, width=3)
    draw.rounded_rectangle((cx - w / 2 + 12, cy - h / 2 + 28, cx + w / 2 - 12, cy + h / 2 - 28),
                           radius=6, fill=ORANGE)

def _icon_ipad(draw, cx, cy):
    w, h = 260, 340
    draw.rounded_rectangle((cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2),
                           radius=22, fill=NAVY, outline=NAVY_D, width=3)
    draw.rounded_rectangle((cx - w / 2 + 14, cy - h / 2 + 14, cx + w / 2 - 14, cy + h / 2 - 14),
                           radius=8, fill=TEAL)

def _icon_desktop(draw, cx, cy):
    w, h = 320, 220
    # screen
    draw.rounded_rectangle((cx - w / 2, cy - h / 2 - 20, cx + w / 2, cy + h / 2 - 20),
                           radius=14, fill=NAVY, outline=NAVY_D, width=3)
    draw.rounded_rectangle((cx - w / 2 + 14, cy - h / 2 - 6, cx + w / 2 - 14, cy + h / 2 - 34),
                           radius=4, fill=TEAL)
    # stand
    draw.polygon([(cx - 70, cy + h / 2), (cx + 70, cy + h / 2), (cx + 30, cy + h / 2 + 48), (cx - 30, cy + h / 2 + 48)],
                 fill=NAVY)
    draw.rounded_rectangle((cx - 110, cy + h / 2 + 44, cx + 110, cy + h / 2 + 60),
                           radius=6, fill=NAVY)


def main():
    if len(sys.argv) != 4:
        print("Usage: mockup.py <product_name> <tagline> <slug>")
        sys.exit(2)
    product, tagline, slug = sys.argv[1:4]
    out_dir = Path(os.environ.get("CLEARFOLKS_HOME", "/root/clearfolks")) / "mockups" / slug
    out_dir.mkdir(parents=True, exist_ok=True)

    builders = [
        ("image-1.png", lambda: image_hero(product, tagline, slug)),
        ("image-2.png", lambda: image_features(slug)),
        ("image-3.png", image_how),
        ("image-4.png", image_included),
        ("image-5.png", image_devices),
    ]
    for name, make in builders:
        img = make()
        path = out_dir / name
        img.save(path, "PNG", optimize=True)
        print(f"Wrote {path} ({path.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
