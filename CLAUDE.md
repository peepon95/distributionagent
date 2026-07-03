# Project: DistributionGPT

An AI research agent ("Claude for distribution") that ingests YouTube growth/founder
interview channels and articles, enriches them with structured metadata, and lets me
chat with the corpus to get distribution advice with episode citations.

## Sources to ingest
- YouTube: https://www.youtube.com/@SuperwallHQ
- YouTube: https://www.youtube.com/@starterstory
- Website: https://www.socialgrowthengineers.com/

## Architecture (do not deviate without asking)
- **Backend/pipeline:** Python 3.11+, scripts in `/pipeline`
- **Database:** Supabase (Postgres + pgvector) — tables: `episodes`, `chunks`, `entities`
- **Embeddings:** OpenAI text-embedding-3-small (1536 dims)
- **LLM:** Anthropic API — claude-haiku for enrichment, claude-sonnet for chat answers
- **Frontend:** Next.js 14 (App Router) + Tailwind + Framer Motion, in `/web`
- **Env vars** in `.env` (never hardcode keys): ANTHROPIC_API_KEY, OPENAI_API_KEY,
  SUPABASE_URL, SUPABASE_SERVICE_KEY, YOUTUBE_API_KEY

## Data model
- `episodes`: id, video_id, channel, title, url, published_at, duration,
  summary (text), apps_mentioned (jsonb), tactics (jsonb), metrics (jsonb),
  ingested_at
- `chunks`: id, episode_id (fk), content, start_timestamp (seconds),
  embedding (vector 1536), tsv (tsvector for keyword search)
- `entities`: id, name, type (app | founder | channel_tactic), episode_ids (jsonb)

## Core principles
- Idempotent ingestion: re-running scripts must skip already-ingested videos.
- Hybrid retrieval: always combine vector similarity + Postgres full-text search,
  because app names embed poorly.
- Every chat answer must cite: episode title, channel, and a clickable YouTube
  timestamp link (url + &t={seconds}s).
- Enrichment prompts live in `/pipeline/prompts/` as versioned .txt files so they
  can be improved and re-run over the whole corpus later.
- My app profile lives in `profile.json` (my app's name, category, target audience,
  competitor apps). The chat system prompt injects it so every answer is framed
  as advice for MY app.

## Style
- Type hints everywhere, small focused modules, a Makefile with targets:
  `make ingest`, `make enrich`, `make index`, `make dev`.
