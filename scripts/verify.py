#!/usr/bin/env python3
"""
verify.py — pre-flight a week before it goes anywhere near Instagram.

Catches the failure modes that silently kill automated posting:
  * caption over 2,200 chars (IG hard-rejects)
  * more than 30 hashtags (IG hard-rejects)
  * missing / non-JPEG / wrong-aspect image
  * file over 8 MB
  * a quote that duplicates something already published
  * gaps or duplicate dates in the week

Exit code 1 on any error, so CI and the publisher can both gate on it.
"""
import json, os, sys, datetime
from PIL import Image

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAX_CAPTION, MAX_TAGS, MAX_BYTES = 2200, 30, 8 * 1024 * 1024
AR_MIN, AR_MAX = 0.8, 1.91          # IG accepts 4:5 .. 1.91:1

errors, warnings = [], []


def check(cond, msg, hard=True):
    if not cond:
        (errors if hard else warnings).append(msg)


def main():
    q = json.load(open(os.path.join(ROOT, "content/queue.json")))
    pub = json.load(open(os.path.join(ROOT, "content/published.json")))
    seen = {p["text"].strip().lower() for p in pub.get("posts", [])}
    dates, texts = [], set()

    for p in q["posts"]:
        tag = p.get("id", "?")

        cap = "\n".join([p.get("caption", ""), " ".join(p.get("hashtags", []))])
        check(len(cap) <= MAX_CAPTION, f"{tag}: caption {len(cap)} chars > {MAX_CAPTION}")
        check(len(p.get("hashtags", [])) <= MAX_TAGS, f"{tag}: {len(p.get('hashtags', []))} hashtags > {MAX_TAGS}")
        check(all(h.startswith("#") for h in p.get("hashtags", [])), f"{tag}: hashtag missing '#'")

        body = p["text"].strip().lower()
        check(body not in seen, f"{tag}: this quote was already published")
        check(body not in texts, f"{tag}: duplicate quote inside this same week")
        texts.add(body)
        check(len(p["text"]) <= 140, f"{tag}: quote is {len(p['text'])} chars — long quotes render small", hard=False)

        img = os.path.join(ROOT, p.get("image", ""))
        if not p.get("image") or not os.path.exists(img):
            errors.append(f"{tag}: image missing — run scripts/render.py")
        else:
            check(img.lower().endswith((".jpg", ".jpeg")), f"{tag}: image must be JPEG, got {os.path.splitext(img)[1]}")
            size = os.path.getsize(img)
            check(size <= MAX_BYTES, f"{tag}: image {size/1e6:.1f} MB > 8 MB")
            with Image.open(img) as im:
                ar = im.width / im.height
                check(AR_MIN <= ar <= AR_MAX, f"{tag}: aspect ratio {ar:.3f} outside {AR_MIN}–{AR_MAX}")
                check(im.width >= 320, f"{tag}: width {im.width}px too small")

        try:
            dates.append(datetime.date.fromisoformat(p["date"]))
        except Exception:
            errors.append(f"{tag}: bad date '{p.get('date')}'")

    check(len(dates) == len(set(dates)), "two posts share the same date")
    if dates:
        span = (max(dates) - min(dates)).days + 1
        check(span == len(dates), f"gap in the schedule: {len(dates)} posts across {span} days", hard=False)

    for w in warnings:
        print(f"  ! {w}")
    for e in errors:
        print(f"  ✗ {e}")
    if not errors:
        print(f"  ✓ {len(q['posts'])} posts verified — {q['posts'][0]['date']} to {q['posts'][-1]['date']}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
