#!/usr/bin/env python3
"""
render.py - turns an approved quote record into a 1080x1350 Instagram image.

Usage:
    python3 scripts/render.py --queue content/queue.json --out assets/rendered
    python3 scripts/render.py --text "Your quote" --author "Anon" --palette sage --out /tmp

Design contract: every image is text-first, high contrast, safe-zone aware,
and consistent enough that the 3-wide grid reads as one brand.
"""
import argparse, hashlib, json, math, os, random, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def hex2rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def linear_gradient(size, c1, c2, angle=145):
    """Smooth diagonal gradient, rendered small then upscaled (fast + banding-free)."""
    w, h = size
    small = (128, int(128 * h / w))
    base = Image.new("RGB", small)
    px = base.load()
    rad = math.radians(angle)
    dx, dy = math.cos(rad), math.sin(rad)
    sw, sh = small
    proj = [[(x / sw) * dx + (y / sh) * dy for x in range(sw)] for y in range(sh)]
    lo = min(min(r) for r in proj)
    hi = max(max(r) for r in proj)
    span = (hi - lo) or 1
    for y in range(sh):
        for x in range(sw):
            t = (proj[y][x] - lo) / span
            t = t * t * (3 - 2 * t)  # smoothstep
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3))
    return base.resize(size, Image.LANCZOS)


def add_grain(img, amount):
    """Subtle luminance noise. Kills gradient banding after Instagram's re-encode."""
    if amount <= 0:
        return img
    w, h = img.size
    noise = Image.effect_noise((w, h), amount * 12).convert("L")
    noise = noise.filter(ImageFilter.GaussianBlur(0.4))
    return Image.blend(img, Image.merge("RGB", (noise, noise, noise)), amount / 100.0)


def vignette(img, strength=0.10):
    w, h = img.size
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    d.ellipse([-w * 0.30, -h * 0.30, w * 1.30, h * 1.30], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(w // 8))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength), mask)


def smarten(text):
    """Straight quotes -> typographic. Serif type looks amateur without this."""
    import re as _re
    t = text.replace("...", "\u2026").replace("--", "\u2014")
    t = _re.sub(r"(\w)'(\w)", "\\1\u2019\\2", t)          # don't -> don\u2019t
    t = _re.sub(r'(^|[\s(\[])"', "\\1\u201c", t)             # opening "
    t = t.replace('"', "\u201d")                             # closing "
    t = _re.sub(r"(^|[\s(\[])'", "\\1\u2018", t)
    t = t.replace("'", "\u2019")
    return t


def wrap_balanced(text, font, draw, max_w):
    """Greedy wrap, then rebalance so the last line is never a lonely orphan word."""
    words = text.split()
    lines, cur = [], []
    for word in words:
        trial = " ".join(cur + [word])
        if draw.textlength(trial, font=font) <= max_w or not cur:
            cur.append(word)
        else:
            lines.append(" ".join(cur))
            cur = [word]
    if cur:
        lines.append(" ".join(cur))
    # orphan fix: pull a word down if the final line is a single short word
    if len(lines) >= 2 and len(lines[-1].split()) == 1 and len(lines[-1]) <= 6:
        prev = lines[-2].split()
        if len(prev) > 2:
            lines[-1] = prev[-1] + " " + lines[-1]
            lines[-2] = " ".join(prev[:-1])
    return lines


def fit_text(draw, text, font_path, max_w, max_h, hi, lo, spacing):
    """Binary-search the largest font size whose wrapped block fits the box."""
    best = None
    while lo <= hi:
        mid = (lo + hi) // 2
        font = ImageFont.truetype(font_path, mid)
        lines = wrap_balanced(text, font, draw, max_w)
        lh = mid * spacing
        block_h = lh * len(lines)
        widest = max((draw.textlength(l, font=font) for l in lines), default=0)
        if block_h <= max_h and widest <= max_w:
            best = (mid, font, lines, block_h, lh)
            lo = mid + 1
        else:
            hi = mid - 1
    if best is None:
        font = ImageFont.truetype(font_path, 40)
        lines = wrap_balanced(text, font, draw, max_w)
        best = (40, font, lines, 40 * spacing * len(lines), 40 * spacing)
    return best


def render(cfg, text, author=None, kicker=None, palette=None, seed=None, plate=None):
    W = cfg["canvas"]["w"]
    H = cfg["canvas"]["h"]
    L = cfg["layout"]
    rnd = random.Random(seed if seed is not None else text)
    text = smarten(text)

    pals = {p["name"]: p for p in cfg["palettes"]}
    pal = pals.get(palette) or rnd.choice(cfg["palettes"])
    ink = hex2rgb(pal["ink"])
    muted = hex2rgb(pal["muted"])

    # --- background: Canva-designed plate if supplied, else generated gradient
    if plate and os.path.exists(plate):
        img = Image.open(plate).convert("RGB").resize((W, H), Image.LANCZOS)
    else:
        img = linear_gradient((W, H), hex2rgb(pal["bg"][0]), hex2rgb(pal["bg"][1]),
                              angle=rnd.choice([135, 145, 160, 200]))
        img = vignette(img, 0.08)

    draw = ImageDraw.Draw(img)
    max_w = W - 2 * L["margin_x"]
    box_top, box_bot = L["quote_box_top"], L["quote_box_bottom"]

    # --- kicker (e.g. "REMINDER" / "MONDAY MANTRA")
    y_cursor = box_top
    if kicker:
        kf = ImageFont.truetype(cfg["fonts"]["ui_bold"], 30)
        kt = " ".join(kicker.upper())          # letterspaced
        kw = draw.textlength(kt, font=kf)
        draw.text(((W - kw) / 2, box_top - 118), kt, font=kf, fill=muted)
        draw.line([(W / 2 - 34, box_top - 62), (W / 2 + 34, box_top - 62)], fill=muted, width=2)

    # --- quote, auto-fitted
    avail_h = box_bot - box_top
    size, font, lines, block_h, lh = fit_text(
        draw, text, cfg["fonts"]["quote"], max_w, avail_h,
        L["max_font"], L["min_font"], L["line_spacing"])

    y = box_top + (avail_h - block_h) / 2
    for line in lines:
        lw = draw.textlength(line, font=font)
        draw.text(((W - lw) / 2, y), line, font=font, fill=ink)
        y += lh

    # --- attribution
    if author:
        af = ImageFont.truetype(cfg["fonts"]["ui"], 32)
        at = f"— {author}"
        aw = draw.textlength(at, font=af)
        draw.text(((W - aw) / 2, min(y + 34, box_bot + 40)), at, font=af, fill=muted)

    # --- handle lockup, bottom centre, outside IG's UI overlay zone
    hf = ImageFont.truetype(cfg["fonts"]["ui_bold"], 30)
    handle = cfg["handle"]
    hw = draw.textlength(handle, font=hf)
    draw.text(((W - hw) / 2, H - 108), handle, font=hf, fill=muted)

    img = add_grain(img, L.get("grain", 5))
    return img, pal["name"]


def slug(s, n=42):
    keep = "".join(c if c.isalnum() else "-" for c in s.lower())
    return "-".join(w for w in keep.split("-") if w)[:n]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default=os.path.join(ROOT, "config/brand.json"))
    ap.add_argument("--queue")
    ap.add_argument("--text")
    ap.add_argument("--author")
    ap.add_argument("--kicker")
    ap.add_argument("--palette")
    ap.add_argument("--plate")
    ap.add_argument("--out", default=os.path.join(ROOT, "assets/rendered"))
    a = ap.parse_args()

    cfg = json.load(open(a.config))
    # resolve font paths relative to the repo root so CI and local behave identically
    for k, v in cfg["fonts"].items():
        cfg["fonts"][k] = v if os.path.isabs(v) else os.path.join(ROOT, v)
    os.makedirs(a.out, exist_ok=True)

    if a.queue:
        q = json.load(open(a.queue))
        posts = q["posts"] if isinstance(q, dict) else q
        for p in posts:
            img, pal = render(cfg, p["text"], p.get("author"), p.get("kicker"),
                              p.get("palette"), seed=p.get("id"), plate=p.get("plate"))
            fn = f"{p['date']}-{slug(p['text'])}.jpg"
            path = os.path.join(a.out, fn)
            # Instagram Content Publishing accepts JPEG only — PNG uploads fail.
            img.save(path, "JPEG", quality=92, subsampling=0, optimize=True)
            p["image"] = f"assets/rendered/{fn}"
            p["palette"] = pal
            print(f"  ✓ {p['date']}  {pal:6s}  {fn}")
        if isinstance(q, dict):
            q["posts"] = posts
        json.dump(q, open(a.queue, "w"), indent=2, ensure_ascii=False)
    else:
        img, pal = render(cfg, a.text, a.author, a.kicker, a.palette, plate=a.plate)
        path = os.path.join(a.out, f"{slug(a.text)}.jpg")
        img.save(path, "JPEG", quality=92, subsampling=0, optimize=True)
        print(path)


if __name__ == "__main__":
    main()
