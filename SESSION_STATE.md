## Session State

Date saved: 2026-07-03

### Project
DistributionGPT

AI research agent for distribution advice using YouTube and web content, with episode citations.

### Confirmed Requirements
- Backend/pipeline: Python 3.11+, scripts in `/pipeline`
- Database: Supabase with `episodes`, `chunks`, `entities`
- Embeddings: OpenAI `text-embedding-3-small`
- LLM: Anthropic Haiku for enrichment, Sonnet for chat
- Frontend: Next.js 14 App Router in `/web`
- Secrets stay in `.env`

### Sources To Ingest
- `https://www.youtube.com/@SuperwallHQ`
- `https://www.youtube.com/@starterstory`
- `https://www.socialgrowthengineers.com/`

### Core Constraints
- Keep ingestion idempotent
- Use hybrid retrieval: pgvector + Postgres full-text search
- Chat answers must cite episode title, channel, and YouTube timestamp link
- Enrichment prompts belong in `/pipeline/prompts/`
- App-specific framing should come from `profile.json`

### Workspace State
- This folder is not an isolated git repo
- The detected git root is `/Users/eevontan`, so avoid running `git add .` or committing from here
- Current workspace contents are minimal:
  - `CLAUDE.md`
  - `SESSION_STATE.md`
  - `distribution-gpt/` (present but currently empty from this workspace scan)

### Resume Plan
1. Inspect `distribution-gpt/` and confirm whether project files were generated elsewhere.
2. If missing, scaffold:
   - `/pipeline`
   - `/pipeline/prompts`
   - `/web`
   - `profile.json`
   - `Makefile`
   - `.env.example`
3. Implement ingestion pipeline first, then enrichment, then indexing, then chat UI.

### Safe Restart Commands
```bash
cd "/Users/eevontan/Desktop/Vibecoding/Distribution Agent"
ls -la
find distribution-gpt -maxdepth 3 -type f | sort
sed -n '1,220p' CLAUDE.md
sed -n '1,220p' SESSION_STATE.md
```
