-- Schema v2: optional server-side upgrades. Paste into the Supabase SQL editor.
-- The pipeline works without this (local vector cache + sentinel); running it
-- enables pure-SQL vector search and a proper chunk_type column.

-- 1. Proper summary-chunk marking (pipeline used start_timestamp = -1 as sentinel).
alter table chunks add column if not exists chunk_type text not null default 'transcript';
update chunks set chunk_type = 'summary' where start_timestamp = -1;

-- 2. Server-side vector search for hybrid retrieval.
create or replace function match_chunks(
    query_embedding vector(1536),
    match_count int default 10
)
returns table (
    id bigint,
    content text,
    start_timestamp integer,
    video_id text,
    title text,
    channel text,
    url text,
    similarity float
)
language sql stable as $$
    select
        c.id, c.content, c.start_timestamp,
        e.video_id, e.title, e.channel, e.url,
        1 - (c.embedding <=> query_embedding) as similarity
    from chunks c
    join episodes e on e.id = c.episode_id
    where c.embedding is not null
    order by c.embedding <=> query_embedding
    limit match_count;
$$;
