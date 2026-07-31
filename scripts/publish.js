/**
 * scripts/publish.js — publishes today's approved post to Instagram.
 *
 * Runs inside GitHub Actions, triggered by cron-job.org via workflow_dispatch.
 * No server, no third party holding the Meta token: IG_ACCESS_TOKEN lives in
 * GitHub Secrets and is only ever exposed to this job.
 *
 * Env:
 *   IG_USER_ID       numeric Instagram professional account id
 *   IG_ACCESS_TOKEN  long-lived token (GitHub Secret)
 *   GITHUB_REPOSITORY / GITHUB_SHA   provided automatically by Actions
 *   TZ_OFFSET_MIN    330 for IST
 *   INPUT_DATE       optional YYYY-MM-DD override
 *   INPUT_DRY_RUN    "true" to resolve everything but not publish
 *
 * Exit codes: 0 = published or intentionally skipped, 1 = real failure.
 */
import fs from "node:fs";

const GRAPH = "https://graph.facebook.com/v21.0";
const QUEUE = "content/queue.json";
const PUBLISHED = "content/published.json";

const env = (k, d) => process.env[k] ?? d;
const read = (p) => JSON.parse(fs.readFileSync(p, "utf8"));
const write = (p, o) => fs.writeFileSync(p, JSON.stringify(o, null, 2) + "\n");
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function today(offsetMin) {
  return new Date(Date.now() + Number(offsetMin) * 60000).toISOString().slice(0, 10);
}

// GitHub Actions convention: write a line to $GITHUB_STEP_SUMMARY so failures
// are readable without digging through raw logs.
function summary(md) {
  const f = process.env.GITHUB_STEP_SUMMARY;
  if (f) fs.appendFileSync(f, md + "\n");
  console.log(md);
}

async function igPublish(imageUrl, caption) {
  const uid = env("IG_USER_ID");
  const tok = env("IG_ACCESS_TOKEN");
  if (!uid || !tok) throw new Error("IG_USER_ID or IG_ACCESS_TOKEN missing from secrets");

  const c = await (
    await fetch(`${GRAPH}/${uid}/media`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ image_url: imageUrl, caption, access_token: tok }),
    })
  ).json();
  if (!c.id) throw new Error(`container creation failed: ${JSON.stringify(c)}`);

  // Instagram fetches the image asynchronously; publishing before it reports
  // FINISHED fails with a misleading "media not ready" error.
  for (let i = 1; i <= 20; i++) {
    await sleep(3000);
    const s = await (
      await fetch(`${GRAPH}/${c.id}?fields=status_code,status&access_token=${tok}`)
    ).json();
    if (s.status_code === "FINISHED") break;
    if (s.status_code === "ERROR") throw new Error(`ingest error: ${JSON.stringify(s)}`);
    if (i === 20) throw new Error("container never reached FINISHED after 60s");
  }

  const p = await (
    await fetch(`${GRAPH}/${uid}/media_publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ creation_id: c.id, access_token: tok }),
    })
  ).json();
  if (!p.id) throw new Error(`publish failed: ${JSON.stringify(p)}`);
  return p.id;
}

async function main() {
  const date = env("INPUT_DATE") || today(env("TZ_OFFSET_MIN", "330"));
  const dry = env("INPUT_DRY_RUN", "false") === "true";

  const queue = read(QUEUE);
  const published = read(PUBLISHED);

  if (queue.status !== "approved") {
    summary(`⏭️ Skipped — week \`${queue.week_of}\` is \`${queue.status}\`, not approved.`);
    return;
  }

  const post = queue.posts.find((p) => p.date === date);
  if (!post) {
    summary(`⏭️ Skipped — nothing scheduled for ${date}.`);
    return;
  }
  if (published.posts.some((p) => p.id === post.id)) {
    summary(`⏭️ Skipped — \`${post.id}\` already published. (Duplicate trigger is harmless.)`);
    return;
  }
  if (!post.image || !fs.existsSync(post.image)) {
    throw new Error(`image missing for ${post.id} — run scripts/render.py`);
  }

  // Pin to this exact commit so the URL can never drift or 404 mid-publish.
  const imageUrl = `https://raw.githubusercontent.com/${env("GITHUB_REPOSITORY")}/${env("GITHUB_SHA")}/${post.image}`;
  const caption = [post.caption, "", (post.hashtags || []).join(" ")].join("\n").trim();

  if (dry) {
    summary(`🧪 Dry run — ${post.id}\n\n- image: ${imageUrl}\n- caption: ${caption.length} chars`);
    return;
  }

  const mediaId = await igPublish(imageUrl, caption);

  published.posts.push({ ...post, media_id: mediaId, published_at: new Date().toISOString() });
  write(PUBLISHED, published);
  queue.posts = queue.posts.filter((p) => p.id !== post.id);
  write(QUEUE, queue);

  summary(`✅ Published \`${post.id}\` — media ${mediaId}\n\n> ${post.text}`);
}

main().catch((e) => {
  summary(`❌ ${e.message}`);
  process.exit(1);
});
