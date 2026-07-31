# The Kind Truth — @thekind.truth

Daily Instagram quote channel. Content is written and rendered automatically,
approved by a human once a week, and published unattended every day.

**No server.** cron-job.org calls GitHub's REST API directly to dispatch a
workflow; the workflow does the publishing. A middle layer (Vercel/Workers)
would be pure overhead here — and would mean handing a Meta access token to a
third party.

```
 Claude (weekly)         you (10 min)          cron-job.org (daily)      GitHub Actions
 ───────────────         ────────────          ────────────────────      ──────────────
 write 7 quotes    ──►   review queue     ──►  POST .../dispatches  ──►  pick today's post
 + captions              set status:           {"ref":"main"}            POST /media
 + hashtags              "approved"            → 204                     poll until FINISHED
 render + verify                                                         POST /media_publish
                                                                         commit published.json
```

Fires at **19:30 IST** weekdays, **11:00 IST** weekends.

## Layout

| Path | What it is |
|---|---|
| `config/brand.json` | Handle, palettes, fonts, layout metrics. The whole look lives here. |
| `content/queue.json` | The coming week. `status` must be `approved` or nothing publishes. |
| `content/published.json` | Archive + the dedupe source of truth. |
| `scripts/render.py` | Quote record → 1080×1350 JPEG. |
| `scripts/verify.py` | Pre-flight gate. Exits 1 on anything Instagram would reject. |
| `scripts/publish.js` | The daily publish, run by Actions. |
| `.github/workflows/publish.yml` | `workflow_dispatch` target for cron-job.org. |
| `assets/plates/` | Optional Canva-designed backgrounds. Drop a JPEG in, point a post's `plate` at it. |

## Secrets

| Where | Name | Scope |
|---|---|---|
| GitHub Secrets | `IG_USER_ID` | `17841475193055501` |
| GitHub Secrets | `IG_ACCESS_TOKEN` | long-lived Meta token — **never leaves GitHub** |
| GitHub Secrets | `GH_PAT` | fine-grained, `secrets:write`, this repo only (token refresh) |
| cron-job.org | bearer token | fine-grained PAT, **`actions:write` on this repo only** |

That last scope matters: worst case if cron-job.org is ever breached is someone
triggering a workflow that was going to run anyway. The credential that can
actually post as you never goes near them.

## cron-job.org job

```
POST https://api.github.com/repos/shridevihakkak-prog/the-kind-truth/actions/workflows/publish.yml/dispatches
Authorization: Bearer <PAT>
Accept: application/vnd.github+json
Content-Type: application/json

{"ref":"main"}      → 204 No Content
```

> `workflow_dispatch` only becomes triggerable once `publish.yml` is on the
> **default branch**. Dispatching before that returns a misleading 404.

## Local use

```bash
pip install -r requirements.txt
python3 scripts/render.py --queue content/queue.json --out assets/rendered
python3 scripts/verify.py

# preview a single line without touching the queue
python3 scripts/render.py --text "Begin badly. Begin anyway." --kicker "reminder" --palette dusk --out /tmp
```

## Safety rails

- **Idempotent** — an id already in `published.json` is never republished, so a double trigger is harmless.
- **Approval gate** — `status != "approved"` exits cleanly and posts nothing.
- **Dry run** — dispatch with `dry_run: true` to see the resolved image URL and caption.
- **Pinned image URL** — built from the commit SHA, so it can't drift or 404 mid-publish.
- **JPEG enforced** — the Graph API rejects PNG; `verify.py` fails the build if one slips in.
- **Friday health check** — opens an issue if next week isn't approved.
- **Monthly token refresh** — the 60-day expiry is handled before it bites.
