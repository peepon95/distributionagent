-- DistributionGPT schema. Run once in the Supabase SQL editor (or psql).

create extension if not exists vector;

create table if not exists episodes (
    id             bigint generated always as identity primary key,
    video_id       text not null unique,
    channel        text not null,
    title          text not null,
    url            text not null,
    published_at   timestamptz,
    duration       integer,          -- seconds
    summary        text,
    apps_mentioned jsonb not null default '[]'::jsonb,
    tactics        jsonb not null default '[]'::jsonb,
    metrics        jsonb not null default '[]'::jsonb,
    ingested_at    timestamptz not null default now()
);

create table if not exists chunks (
    id              bigint generated always as identity primary key,
    episode_id      bigint not null references episodes (id) on delete cascade,
    content         text not null,
    start_timestamp integer not null default 0,  -- seconds into the episode
    embedding       vector(1536),
    tsv             tsvector generated always as (to_tsvector('english', content)) stored
);

create table if not exists entities (
    id          bigint generated always as identity primary key,
    name        text not null,
    type        text not null check (type in ('app', 'founder', 'channel_tactic')),
    episode_ids jsonb not null default '[]'::jsonb,
    unique (name, type)
);

-- Vector similarity (cosine). Re-run `reindex` guidance: ivfflat lists ~ sqrt(rows);
-- 100 is fine for a corpus of up to ~1M chunks. Build AFTER bulk-loading embeddings
-- for best recall (it samples existing rows for centroids).
create index if not exists chunks_embedding_idx
    on chunks using ivfflat (embedding vector_cosine_ops) with (lists = 100);

-- Keyword search (hybrid retrieval requires this alongside vector search).
create index if not exists chunks_tsv_idx on chunks using gin (tsv);

create index if not exists chunks_episode_id_idx on chunks (episode_id);
create index if not exists episodes_channel_idx on episodes (channel);
