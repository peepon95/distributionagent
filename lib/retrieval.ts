import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { resolve } from "node:path";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

function resolveProjectRoot() {
  const cwd = process.cwd();
  if (existsSync(resolve(cwd, "pipeline"))) return cwd;
  const parent = resolve(cwd, "..");
  if (existsSync(resolve(parent, "pipeline"))) return parent;
  return cwd;
}

export const PROJECT_ROOT = resolveProjectRoot();
const PYTHON = resolve(PROJECT_ROOT, ".venv/bin/python");

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

/** Run pipeline/search.py (hybrid vector + FTS retrieval) as a subprocess. */
export async function search(
  query: string,
  opts: {
    k?: number;
    app?: string;
    summariesOnly?: boolean;
    extraQueries?: string[];
  } = {},
): Promise<RetrievedChunk[]> {
  const args = ["-m", "pipeline.search", query, "--json", "--k", String(opts.k ?? 10)];
  if (opts.summariesOnly) args.push("--summaries-only");
  if (opts.app) args.push("--app", opts.app);
  if (opts.extraQueries?.length)
    args.push("--extra-queries-json", JSON.stringify(opts.extraQueries));

  // One retry: the embedding call inside search.py can transiently 429 while
  // batch enrichment is saturating the OpenAI API.
  let lastError: unknown;
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      const { stdout } = await execFileAsync(PYTHON, args, {
        cwd: PROJECT_ROOT,
        timeout: 90_000,
        maxBuffer: 16 * 1024 * 1024,
      });
      return JSON.parse(stdout.trim() || "[]");
    } catch (err) {
      lastError = err;
      await new Promise((r) => setTimeout(r, 1500));
    }
  }
  const stderr =
    lastError && typeof lastError === "object" && "stderr" in lastError
      ? String((lastError as { stderr: unknown }).stderr).trim().split("\n").slice(-3).join(" | ")
      : "";
  throw new Error(
    `search subprocess failed${stderr ? `: ${stderr}` : `: ${lastError instanceof Error ? lastError.message : lastError}`}`,
  );
}
