# DistributionGPT

An AI research agent that ingests YouTube growth/founder interview channels and
articles, enriches them with structured metadata, and answers distribution
questions with episode citations. See [CLAUDE.md](CLAUDE.md) for the full spec.

## Setup

### 1. Python environment

```bash
make setup            # creates .venv and installs requirements.txt
```

### 2. Supabase project

1. Create a project at [supabase.com](https://supabase.com) (free tier works).
2. In the dashboard, open **SQL Editor**, paste the contents of
   [pipeline/schema.sql](pipeline/schema.sql), and run it. This enables the
   `pgvector` extension and creates the `episodes`, `chunks`, and `entities`
   tables with the ivfflat (vector) and GIN (full-text) indexes.
3. From **Project Settings → API**, copy the **Project URL** and the
   **service_role** key.

### 3. YouTube Data API key

1. Go to the [Google Cloud Console](https://console.cloud.google.com/), create
   (or pick) a project.
2. **APIs & Services → Library →** enable **YouTube Data API v3**.
3. **APIs & Services → Credentials → Create credentials → API key.**

The free quota (10,000 units/day) is plenty: listing videos costs 1 unit per
50 videos; transcripts are fetched via `youtube-transcript-api` and use no quota.

### 4. Environment variables

```bash
cp .env.example .env   # then fill in the values
```

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | embeddings + gpt-5-mini enrichment + gpt-4o chat |
| `SUPABASE_URL` | project URL from step 2 |
| `SUPABASE_SERVICE_KEY` | service_role key from step 2 |
| `YOUTUBE_API_KEY` | Data API key from step 3 |
| `EMAIL_TO` | Optional weekly notification recipient |
| `SMTP_HOST` / `SMTP_PORT` | Optional SMTP server for weekly email |
| `SMTP_USER` / `SMTP_PASSWORD` | Optional SMTP login; Gmail requires an app password |

## Ingestion (Phase 1)

```bash
make ingest CHANNEL=@starterstory LIMIT=3   # smoke test: 3 videos
make ingest CHANNEL=@starterstory           # full channel
make ingest-all                             # both channels + the website
make test                                   # unit tests
```

Raw episodes land in `data/raw/{channel}/{video_id}.json` as
`{video_id, channel, title, url, published_at, duration, transcript: [{text, start}]}`.
Website articles use the same shape (one segment, `start=0`) under
`data/raw/social_growth_engineers/`.

Ingestion is idempotent: videos with an existing JSON file or an `episodes`
row are skipped, so re-running only picks up new uploads. Videos without
transcripts are logged, marked, and skipped. Transcript fetches are
rate-limited with exponential-backoff retries; if YouTube IP-blocks the
machine, the run cools down once and then exits gracefully — blocked videos
stay pending and are picked up by the next run (`scripts/yt_retry.sh` loops
this automatically).

## Enrichment, indexing, search (Phase 2)

```bash
make enrich                 # gpt-5-mini summaries/apps/tactics/metrics -> episodes + entities
make enrich BUDGET=10       # override the default $25 spend cap
make index                  # ~800-token chunks + embeddings -> chunks table + local vector cache
make search Q="paywall optimization"   # hybrid search from the CLI
make update                 # full channel scan -> ingest missing videos -> enrich -> index
make update ARGS="--rss-only"           # faster latest-video check only
```

- Enrichment logs a cost estimate to RUN_LOG.md before spending; if the
  estimate exceeds the budget it enriches only the 150 most recent episodes.
- Hybrid search always combines vector similarity (local embedding cache in
  `data/index/`) with Postgres full-text search, merged by reciprocal rank
  fusion. Optional: run `pipeline/schema_v2.sql` in the Supabase SQL editor to
  add a proper `chunk_type` column and a server-side `match_chunks` function.

## Weekly update agent

```bash
scripts/install_weekly_agent.sh
```

Installs a macOS LaunchAgent that runs every Monday at 09:00 local time. The
agent calls `scripts/weekly_update.sh`, which runs `make update`. Weekly
updates scan each configured YouTube channel's full uploads playlist, so missed
Superwall videos are retried as well as brand-new uploads. Existing episodes
and videos marked as transcript-less are skipped, keeping runs idempotent.

Logs are written to `weekly_update.log` and `weekly_update_launchd.log`.
If SMTP settings are present in `.env`, the agent also emails a summary of
newly added videos to `EMAIL_TO`. With Gmail, set `SMTP_HOST=smtp.gmail.com`,
`SMTP_PORT=587`, and use a Gmail app password for `SMTP_PASSWORD`.

## Chat app (Phase 3)

```bash
make dev    # Next.js app on http://localhost:3000
```

Edit "My App Profile" in the sidebar (persists to `profile.json`) so every
answer is framed for your app. Questions are classified by gpt-5-mini
(broad / specific / advice-for-my-app), retrieval is hybrid, and gpt-4o streams
answers with `[Episode Title — Channel @ mm:ss]` citations that deep-link to
the YouTube timestamp. Cited episodes collect in the sidebar Source Tray.
