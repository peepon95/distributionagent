import { existsSync } from "node:fs";
import { resolve } from "node:path";
import OpenAI from "openai";

function resolveProjectRoot() {
  const cwd = process.cwd();
  if (existsSync(resolve(cwd, "pipeline"))) return cwd;
  const parent = resolve(cwd, "..");
  if (existsSync(resolve(parent, "pipeline"))) return parent;
  return cwd;
}

export const PROJECT_ROOT = resolveProjectRoot();

const SUMMARY_SENTINEL = -1;
const RRF_K = 60;
const CANDIDATES_PER_LEG = 40;

export interface RetrievedChunk {
  chunk_id: number;
  content: string;
  start_timestamp: number;
  is_summary: boolean;
  video_id: string;
  title: string;
  channel: string;
  url: string;
  timestamp_url: string;
  score: number;
}

interface VectorRow {
  id: number;
  content: string;
  start_timestamp: number;
  video_id: string;
  title: string;
  channel: string;
  url: string;
  similarity?: number;
}

interface FtsRow {
  id: number;
  content: string;
  start_timestamp: number;
  episodes:
    | {
        video_id: string;
        title: string;
        channel: string;
        url: string;
      }
    | Array<{
        video_id: string;
        title: string;
        channel: string;
        url: string;
      }>;
}

interface EntityRow {
  name: string;
  episode_ids: string[] | null;
}

function env(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is not configured`);
  return value;
}

function openaiClient() {
  return new OpenAI({ apiKey: env("OPENAI_API_KEY") });
}

function supabaseHeaders() {
  const key = env("SUPABASE_SERVICE_KEY");
  return {
    apikey: key,
    Authorization: `Bearer ${key}`,
    "Content-Type": "application/json",
  };
}

async function supabaseJson<T>(path: string, init?: RequestInit): Promise<T> {
  const base = env("SUPABASE_URL").replace(/\/$/, "");
  const response = await fetch(`${base}/rest/v1/${path}`, {
    ...init,
    headers: {
      ...supabaseHeaders(),
      ...(init?.headers ?? {}),
    },
    cache: "no-store",
  });
  if (!response.ok) {
    const text = await response.text();
    throw new Error(`Supabase ${response.status}: ${text || response.statusText}`);
  }
  return response.json() as Promise<T>;
}

function normalizeChunk(result: Omit<RetrievedChunk, "score">): RetrievedChunk {
  return { ...result, score: 0 };
}

function timestampUrl(url: string, startTimestamp: number) {
  return url.includes("youtube.com") ? `${url}&t=${Math.max(startTimestamp, 0)}s` : url;
}

function fromVectorRow(row: VectorRow): RetrievedChunk {
  const start = Number(row.start_timestamp) || 0;
  return normalizeChunk({
    chunk_id: Number(row.id),
    content: row.content,
    start_timestamp: Math.max(start, 0),
    is_summary: start === SUMMARY_SENTINEL,
    video_id: row.video_id,
    title: row.title,
    channel: row.channel,
    url: row.url,
    timestamp_url: timestampUrl(row.url, start),
  });
}

function fromFtsRow(row: FtsRow): RetrievedChunk | null {
  const episode = Array.isArray(row.episodes) ? row.episodes[0] : row.episodes;
  if (!episode) return null;
  const start = Number(row.start_timestamp) || 0;
  return normalizeChunk({
    chunk_id: Number(row.id),
    content: row.content,
    start_timestamp: Math.max(start, 0),
    is_summary: start === SUMMARY_SENTINEL,
    video_id: episode.video_id,
    title: episode.title,
    channel: episode.channel,
    url: episode.url,
    timestamp_url: timestampUrl(episode.url, start),
  });
}

function keepChunk(
  chunk: RetrievedChunk,
  allowedVideoIds: Set<string> | null,
  summariesOnly: boolean,
) {
  if (summariesOnly && !chunk.is_summary) return false;
  if (allowedVideoIds && !allowedVideoIds.has(chunk.video_id)) return false;
  return true;
}

async function embed(query: string): Promise<number[]> {
  const response = await openaiClient().embeddings.create({
    model: "text-embedding-3-small",
    input: query,
  });
  return response.data[0]?.embedding ?? [];
}

async function vectorLeg(query: string, k: number): Promise<RetrievedChunk[]> {
  try {
    const queryEmbedding = await embed(query);
    const rows = await supabaseJson<VectorRow[]>("rpc/match_chunks", {
      method: "POST",
      body: JSON.stringify({
        query_embedding: queryEmbedding,
        match_count: k,
      }),
    });
    return rows.map(fromVectorRow);
  } catch {
    return [];
  }
}

async function ftsLeg(query: string): Promise<RetrievedChunk[]> {
  const params = new URLSearchParams({
    select: "id,content,start_timestamp,episodes!inner(video_id,title,channel,url)",
    limit: String(CANDIDATES_PER_LEG),
  });
  params.set("tsv", `wfts(english).${query}`);

  const rows = await supabaseJson<FtsRow[]>(`chunks?${params.toString()}`);
  return rows.map(fromFtsRow).filter((row): row is RetrievedChunk => Boolean(row));
}

function mergeRrf(legs: RetrievedChunk[][], k: number): RetrievedChunk[] {
  const scores = new Map<number, number>();
  const byId = new Map<number, RetrievedChunk>();

  for (const leg of legs) {
    leg.forEach((result, rank) => {
      scores.set(result.chunk_id, (scores.get(result.chunk_id) ?? 0) + 1 / (RRF_K + rank + 1));
      if (!byId.has(result.chunk_id)) byId.set(result.chunk_id, result);
    });
  }

  return Array.from(scores.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, k)
    .map(([chunkId, score]) => ({
      ...(byId.get(chunkId) as RetrievedChunk),
      score: Number(score.toFixed(5)),
    }));
}

function normalizeName(value: string) {
  return value.trim().toLowerCase();
}

async function findEpisodeIdsAbout(appName: string): Promise<Set<string>> {
  const rows = await supabaseJson<EntityRow[]>("entities?select=name,episode_ids&type=eq.app");
  const target = normalizeName(appName);

  const exact = rows.find((row) => normalizeName(row.name) === target);
  if (exact?.episode_ids?.length) return new Set(exact.episode_ids);

  const partial = rows.find((row) => {
    const name = normalizeName(row.name);
    return name.includes(target) || target.includes(name);
  });
  return new Set(partial?.episode_ids ?? []);
}

async function hybridSearch(
  query: string,
  opts: {
    k?: number;
    app?: string;
    summariesOnly?: boolean;
  } = {},
): Promise<RetrievedChunk[]> {
  const k = opts.k ?? 10;
  const summariesOnly = opts.summariesOnly ?? false;
  const allowedVideoIds = opts.app ? await findEpisodeIdsAbout(opts.app) : null;

  const [vector, fts] = await Promise.all([vectorLeg(query, CANDIDATES_PER_LEG), ftsLeg(query)]);

  const legs = [vector, fts].map((leg) =>
    leg.filter((chunk) => keepChunk(chunk, allowedVideoIds, summariesOnly)),
  );

  return mergeRrf(legs, k);
}

function mergeAcrossQueries(results: RetrievedChunk[][], k: number): RetrievedChunk[] {
  const scores = new Map<number, number>();
  const byId = new Map<number, RetrievedChunk>();

  for (const resultSet of results) {
    resultSet.forEach((result, rank) => {
      scores.set(result.chunk_id, (scores.get(result.chunk_id) ?? 0) + 1 / (RRF_K + rank + 1));
      if (!byId.has(result.chunk_id)) byId.set(result.chunk_id, result);
    });
  }

  return Array.from(scores.entries())
    .sort((a, b) => b[1] - a[1])
    .slice(0, k)
    .map(([chunkId, score]) => ({
      ...(byId.get(chunkId) as RetrievedChunk),
      score: Number(score.toFixed(5)),
    }));
}

export async function search(
  query: string,
  opts: {
    k?: number;
    app?: string;
    summariesOnly?: boolean;
    extraQueries?: string[];
  } = {},
): Promise<RetrievedChunk[]> {
  const k = opts.k ?? 10;
  if (opts.extraQueries?.length) {
    const queries = [query, ...opts.extraQueries];
    const results = await Promise.all(
      queries.map((currentQuery) =>
        hybridSearch(currentQuery, {
          k,
          app: opts.app,
          summariesOnly: opts.summariesOnly,
        }),
      ),
    );
    return mergeAcrossQueries(results, k);
  }
  return hybridSearch(query, opts);
}
