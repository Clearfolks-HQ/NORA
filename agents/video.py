#!/usr/bin/env python3
"""Video — render a 30–35s Etsy listing video (H.264 MP4, 1080x1080, 30fps).

Seven brand-matched scenes with fade-in / hold / fade-out transitions:
    1. Title card
    2. Dashboard preview
    3. Offline feature
    4. Partner sharing feature
    5. Lifetime access feature
    6. QR code + URL
    7. Brand close

Writes: /root/clearfolks/videos/<slug>-listing.mp4
"""
import io
import os
import sys
from pathlib import Path

import numpy as np
import qrcode
from PIL import Image, ImageDraw, ImageFont, ImageOps
import imageio.v2 as imageio

sys.path.insert(0, str(Path(__file__).parent))
import brand

SCREENSHOTS = Path(os.environ.get("CLEARFOLKS_HOME", "/root/clearfolks")) / "screenshots"


def _load_desktop(slug: str):
    p = SCREENSHOTS / f"{slug}-desktop.png"
    if not p.exists():
        return None
    try:
        return Image.open(p).convert("RGB")
    except Exception:
        return None


def _crop_zoom(src: Image.Image, out_size: tuple[int, int], scale: float, focus=(0.5, 0.5)):
    """Crop a portion of `src` centered on `focus` (0..1 fractions), zoomed
    by `scale` (>1 = zoom in), then resize to out_size. Used for Ken Burns."""
    sw, sh = src.size
    cw = sw / scale
    ch = sh / scale
    cx = sw * focus[0]
    cy = sh * focus[1]
    x0 = max(0, min(sw - cw, cx - cw / 2))
    y0 = max(0, min(sh - ch, cy - ch / 2))
    crop = src.crop((x0, y0, x0 + cw, y0 + ch))
    return crop.resize(out_size, Image.LANCZOS)

# ---------------------------------------------------------------------------
# Brand palette
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

SIZE = 1080
FPS = 30
# Scene duration is configurable so the same script produces both the long
# 35s (5s × 7 scenes) promo cut and the 14s (2s × 7 scenes) Etsy-compliant
# cut. Etsy caps listing videos at 15s.
SCENE_SECONDS = int(os.environ.get("CLEARFOLKS_SCENE_SECONDS", "5"))
FRAMES_PER_SCENE = SCENE_SECONDS * FPS
FADE_FRAMES = min(15, FRAMES_PER_SCENE // 4)

FONT_REG  = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


def f(size: int, bold=False) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(FONT_BOLD if bold else FONT_REG, size)


def text_w(draw, text, font) -> int:
    l, _t, r, _b = draw.textbbox((0, 0), text, font=font)
    return r - l


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


def blank(bg=NAVY) -> Image.Image:
    return Image.new("RGB", (SIZE, SIZE), bg)


def draw_brand_strip(draw, top=True):
    y = 0 if top else SIZE - 60
    draw.rectangle((0, y, SIZE, y + 60), fill=NAVY_D if top else ORANGE)
    text = "Clearfolks" if top else "clearfolks.com"
    draw.text((SIZE / 2, y + 30), text, font=f(26, bold=True), fill=WHITE, anchor="mm")


# ---------------------------------------------------------------------------
# Scene builders — return a fully composited PIL Image (no fade applied)
# ---------------------------------------------------------------------------
def scene_title(product: str, tagline: str) -> Image.Image:
    img = blank(NAVY)
    draw = ImageDraw.Draw(img)

    # Wordmark
    draw.text((60, 60), "Clearfolks", font=f(46, bold=True), fill=WHITE)
    draw.rectangle((60, 118, 180, 126), fill=ORANGE)

    # DIGITAL APP pill
    pill_font = f(22, bold=True)
    pw = text_w(draw, "DIGITAL APP", pill_font) + 40
    draw.rounded_rectangle((60, 260, 60 + pw, 306), radius=8, fill=TEAL)
    draw.text((60 + pw / 2, 283), "DIGITAL APP", font=pill_font, fill=WHITE, anchor="mm")

    # Title (wrap)
    title_font = f(92, bold=True)
    lines = wrap(draw, product, title_font, SIZE - 120)
    ty = 360
    for ln in lines:
        draw.text((60, ty), ln, font=title_font, fill=WHITE)
        ty += 100
    # Orange underline
    draw.rectangle((60, ty + 16, 60 + 180, ty + 28), fill=ORANGE)

    # Tagline
    draw.text((60, ty + 70), tagline, font=f(44), fill=TEAL)

    # URL strip
    draw.text((SIZE / 2, SIZE - 120),
              "app.clearfolks.com", font=f(34, bold=True), fill=WHITE, anchor="mm")
    return img


_ACCENT_MAP = {"navy": NAVY, "teal": TEAL, "orange": ORANGE}


def _screenshot_canvas(slug: str, caption: str, scale: float, focus):
    """Render one frame: navy canvas + top brand strip + desktop screenshot
    (Ken Burns cropped/zoomed) + bottom caption strip. Used by scenes 2–5."""
    desktop = _load_desktop(slug)
    canvas = Image.new("RGB", (SIZE, SIZE), NAVY)

    # Screenshot band (center). We reserve 96 top + 180 bottom for UI.
    band_top, band_bot = 96, SIZE - 180
    band_h = band_bot - band_top

    if desktop is not None:
        # Fit desktop (1280x800 → aspect 1.6) into full width, preserve ratio.
        target_w = SIZE - 40  # 20px padding each side
        target_h = int(target_w * desktop.size[1] / desktop.size[0])
        if target_h > band_h - 20:
            target_h = band_h - 20
            target_w = int(target_h * desktop.size[0] / desktop.size[1])
        shot = _crop_zoom(desktop, (target_w, target_h), scale=scale, focus=focus)
        mask = Image.new("L", shot.size, 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, target_w, target_h), radius=18, fill=255)
        px = (SIZE - target_w) // 2
        py = band_top + (band_h - target_h) // 2
        canvas.paste(shot, (px, py), mask)

    draw = ImageDraw.Draw(canvas)
    # Top strip — brand
    draw.rectangle((0, 0, SIZE, 80), fill=NAVY_D)
    draw.text((SIZE / 2, 40), "Clearfolks", font=f(26, bold=True), fill=WHITE, anchor="mm")

    # Bottom strip — caption with orange accent
    draw.rectangle((0, SIZE - 180, SIZE, SIZE), fill=NAVY_D)
    # Wrap caption to at most 2 lines
    lines = wrap(draw, caption, f(38, bold=True), SIZE - 120)[:2]
    cy = SIZE - 180 + (180 - len(lines) * 48) / 2 + 20
    for ln in lines:
        draw.text((SIZE / 2, cy), ln, font=f(38, bold=True), fill=WHITE, anchor="mm")
        cy += 48
    draw.rectangle((SIZE / 2 - 60, SIZE - 44, SIZE / 2 + 60, SIZE - 36), fill=ORANGE)

    return canvas


def scene_dashboard(slug: str = ""):
    """Scene 2 — real desktop screenshot with subtle Ken Burns zoom-in."""
    dash = brand.for_slug(slug)
    caption = dash.caption

    def frame(i, total):
        t = i / max(total - 1, 1)
        scale = 1.0 + 0.08 * t
        return _screenshot_canvas(slug, caption, scale, focus=(0.5, 0.5))

    return frame


def scene_feature_screenshot(slug: str, caption: str, focus_start, focus_end):
    """Feature scene — pan across the desktop screenshot while caption sits
    in the bottom strip. `focus_start` and `focus_end` are (x_frac, y_frac)."""
    def frame(i, total):
        t = i / max(total - 1, 1)
        # Ease-in-out for smoother pan
        e = t * t * (3 - 2 * t)
        scale = 1.12
        focus = (
            focus_start[0] + (focus_end[0] - focus_start[0]) * e,
            focus_start[1] + (focus_end[1] - focus_start[1]) * e,
        )
        return _screenshot_canvas(slug, caption, scale, focus=focus)

    return frame


def scene_feature(headline: str, detail: str, accent=TEAL, icon: str | None = "🌙") -> Image.Image:
    img = blank(WHITE)
    draw = ImageDraw.Draw(img)
    draw_brand_strip(draw, top=True)

    # Big icon disc
    disc_cy = 340
    r = 150
    draw.ellipse((SIZE / 2 - r, disc_cy - r, SIZE / 2 + r, disc_cy + r), fill=accent)
    if icon:
        draw.text((SIZE / 2, disc_cy), icon, font=f(160), fill=WHITE, anchor="mm")

    # Headline
    head_font = f(56, bold=True)
    lines = wrap(draw, headline, head_font, SIZE - 160)
    hy = disc_cy + r + 60
    for ln in lines:
        draw.text((SIZE / 2, hy), ln, font=head_font, fill=NAVY, anchor="mm")
        hy += 70

    # Accent rule
    draw.rectangle((SIZE / 2 - 90, hy + 10, SIZE / 2 + 90, hy + 20), fill=ORANGE)

    # Detail text
    detail_font = f(32)
    lines = wrap(draw, detail, detail_font, SIZE - 220)
    dy = hy + 60
    for ln in lines:
        draw.text((SIZE / 2, dy), ln, font=detail_font, fill=GRAY, anchor="mm")
        dy += 46

    draw_brand_strip(draw, top=False)
    return img


def scene_qr(etsy_url: str) -> Image.Image:
    img = blank(NAVY)
    draw = ImageDraw.Draw(img)
    draw.text((60, 60), "Clearfolks", font=f(46, bold=True), fill=WHITE)
    draw.rectangle((60, 118, 180, 126), fill=ORANGE)

    draw.text((SIZE / 2, 200), "Get it on Etsy today",
              font=f(62, bold=True), fill=WHITE, anchor="mm")
    draw.text((SIZE / 2, 260), "Scan to buy on Etsy",
              font=f(30), fill=TEAL, anchor="mm")

    # QR → Etsy listing (not the app). The app URL is in the PDF they get
    # after purchase; this QR is for prospective buyers on the listing page.
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=10, border=2)
    qr.add_data(etsy_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="#1F3A5C", back_color="white").convert("RGB")

    card_size = 520
    card_x = (SIZE - card_size) / 2
    card_y = 320
    draw.rounded_rectangle((card_x, card_y, card_x + card_size, card_y + card_size),
                           radius=26, fill=WHITE)
    inset = 28
    qr_img = qr_img.resize((card_size - inset * 2, card_size - inset * 2), Image.LANCZOS)
    img.paste(qr_img, (int(card_x + inset), int(card_y + inset)))

    draw.text((SIZE / 2, card_y + card_size + 60),
              etsy_url, font=f(28, bold=True), fill=WHITE, anchor="mm")
    return img


def scene_brand(tagline: str) -> Image.Image:
    img = blank(ORANGE)
    draw = ImageDraw.Draw(img)
    draw.text((SIZE / 2, SIZE / 2 - 80), "Clearfolks",
              font=f(140, bold=True), fill=WHITE, anchor="mm")
    draw.rectangle((SIZE / 2 - 130, SIZE / 2 + 20, SIZE / 2 + 130, SIZE / 2 + 36), fill=NAVY)
    draw.text((SIZE / 2, SIZE / 2 + 110),
              "Practical tools for life's complicated moments",
              font=f(32), fill=NAVY, anchor="mm")
    draw.text((SIZE / 2, SIZE - 100), "clearfolks.com",
              font=f(36, bold=True), fill=WHITE, anchor="mm")
    return img


# ---------------------------------------------------------------------------
# Fade helper
# ---------------------------------------------------------------------------
def fade_to_black(img: Image.Image, alpha: float) -> np.ndarray:
    """alpha 1.0 = full image, 0.0 = black."""
    arr = np.asarray(img, dtype=np.float32)
    return np.clip(arr * alpha, 0, 255).astype(np.uint8)


def build(product: str, tagline: str, etsy_url: str, out_path: Path, slug: str = ""):
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Scene list: static PIL.Image OR callable(frame_i, total_frames) -> Image.
    has_desktop = _load_desktop(slug) is not None
    if has_desktop:
        scenes = [
            scene_title(product, tagline),
            scene_dashboard(slug),
            scene_feature_screenshot(slug,
                "Works offline — log anywhere, no Wi-Fi needed",
                focus_start=(0.20, 0.40), focus_end=(0.30, 0.55)),
            scene_feature_screenshot(slug,
                "Share with your partner — both see updates in real time",
                focus_start=(0.50, 0.50), focus_end=(0.50, 0.45)),
            scene_feature_screenshot(slug,
                "One payment. Lifetime access. No subscriptions.",
                focus_start=(0.80, 0.50), focus_end=(0.70, 0.50)),
            scene_qr(etsy_url),
            scene_brand(tagline),
        ]
    else:
        # Fallback: no screenshot — use the old icon-based feature scenes
        scenes = [
            scene_title(product, tagline),
            scene_feature("Track everything in one place",
                          "Dashboard, log entries, exports — all from the same app.",
                          accent=NAVY, icon="📊"),
            scene_feature("Works offline — log anywhere, no Wi-Fi needed",
                          "The app loads once, then runs offline. Data saves to your device.",
                          accent=NAVY, icon="🌙"),
            scene_feature("Share with your partner — real-time updates",
                          "Add anyone. No accounts, no sign-up. An encrypted link you control.",
                          accent=TEAL, icon="👥"),
            scene_feature("One payment. Lifetime access.",
                          "Buy it once. Own it forever. Free updates for life.",
                          accent=ORANGE, icon="♾️"),
            scene_qr(etsy_url),
            scene_brand(tagline),
        ]
    assert len(scenes) == 7

    writer = imageio.get_writer(
        str(out_path),
        fps=FPS,
        codec="libx264",
        pixelformat="yuv420p",
        macro_block_size=8,
        quality=8,
        ffmpeg_log_level="error",
    )

    try:
        for scene in scenes:
            for i in range(FRAMES_PER_SCENE):
                if i < FADE_FRAMES:
                    alpha = i / FADE_FRAMES
                elif i >= FRAMES_PER_SCENE - FADE_FRAMES:
                    alpha = (FRAMES_PER_SCENE - 1 - i) / FADE_FRAMES
                else:
                    alpha = 1.0
                img = scene(i, FRAMES_PER_SCENE) if callable(scene) else scene
                writer.append_data(fade_to_black(img, alpha))
    finally:
        writer.close()


def main():
    if len(sys.argv) != 5:
        print("Usage: video.py <product_name> <tagline> <etsy_url> <slug>")
        print("  etsy_url is the Etsy listing URL (or shop URL as placeholder)")
        sys.exit(2)
    product, tagline, etsy_url, slug = sys.argv[1:5]
    # The slug passed to video.py may be suffixed with "-etsy" for the short
    # cut; strip the suffix so brand.DASHBOARDS lookup still matches.
    dashboard_slug = slug[:-5] if slug.endswith("-etsy") else slug
    out = Path(os.environ.get("CLEARFOLKS_HOME", "/root/clearfolks")) / "videos" / f"{slug}-listing.mp4"
    print(f"Rendering {7 * FRAMES_PER_SCENE} frames at {FPS}fps → {out}")
    print(f"QR target: {etsy_url}")
    build(product, tagline, etsy_url, out, slug=dashboard_slug)
    print(f"Wrote {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
