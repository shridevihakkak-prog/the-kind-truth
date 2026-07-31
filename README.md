# positivity-engine

Daily Instagram quote channel. Content is generated and rendered automatically,
approved by a human once a week, and published unattended every day.

```
 Claude (weekly)          you (10 min)            GitHub Actions        cron-job.org (daily)
 ──────────────           ────────────            ──────────────        ───────────────────
 write 7 quotes    ──►    review queue.json  ──►  render 7 JPEGs   ──►  GET /api/publish
 + captions               flip status to          commit to repo        ├─ pick today's post
 + hashtags               "approved"                                    ├─ POST /media
                                                                        ├─ POST /media_publish
                                                                        └─ move to published.json
```

## Layout

| Path | What it is |
|---|---|
| `config/brand.json` | Handle, palettes, fonts, layout metrics. The whole look lives here. |
| `content/queue.json` | The coming week. `status` must be `approved` or nothing publishes. |
| `content/published.json` | Archive + the dedupe source of truth. |
| `scripts/render.py` | Quote record → 1080×1350 JPEG. |
| `scripts/verify.py` | Pre-flight gate. Exits 1 on anything Instagram would reject. |
| `api/publish.js` | Vercel endpoint that cron-job.org hits once a day. |
| `assets/plates/` | Optional Canva-designed backgrounds. Drop a JPEG here, point a post's `plate` at it. |

## Local use

```bash
pip install -r requirements.txt
python3 scripts/render.py --queue content/queue.json --out assets/rendered
python3 scripts/verify.py

# one-off preview without touching the queue
python3 scripts/render.py --text "Begin badly. Begin anyway." --kicker "reminder" --palette dusk --out /tmp
```

## Environment (Vercel)

| Var | Notes |
|---|---|
| `CRON_SECRET` | Must match the `?key=` cron-job.org sends. |
| `GH_TOKEN` | Fine-grained PAT, Contents read+write, this repo only. |
| `GH_REPO` | `owner/positivity-engine` |
| `GH_BRANCH` | `main` |
| `IG_USER_ID` | Numeric professional-account ID. |
| `IG_ACCESS_TOKEN` | Long-lived token. See `.github/workflows/refresh-token.yml`. |
| `TZ_OFFSET_MIN` | `330` for IST. |

## Safety rails already in place

- **Idempotent** — a post ID already in `published.json` is never republished, so a double cron fire is harmless.
- **Approval gate** — `status != "approved"` returns 409 and posts nothing.
- **Dry run** — add `&dry=1` to see the exact image URL and caption without publishing.
- **JPEG enforced** — the Graph API rejects PNG; `verify.py` fails the build if one slips in.
- **Friday health check** — opens a GitHub issue if next week isn't approved.
