import OpenAI from "openai";
import { readProfile } from "@/lib/profile";
import { search, type RetrievedChunk } from "@/lib/retrieval";

export const runtime = "nodejs";
export const maxDuration = 120;

const CLASSIFY_MODEL = "gpt-5-mini";
const ANSWER_MODEL = "gpt-4o";

type Mode = "broad" | "specific" | "my_app";

interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

function jsonError(error: string, status = 500) {
  return new Response(JSON.stringify({ error }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function mmss(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = seconds % 60;
  return `${m}:${String(s).padStart(2, "0")}`;
}

async function classify(
  client: OpenAI,
  question: string,
): Promise<{ mode: Mode; app: string | null }> {
  try {
    const response = await client.chat.completions.create({
      model: CLASSIFY_MODEL,
      reasoning_effort: "low",
      response_format: { type: "json_object" },
      messages: [
        {
          role: "user",
          content:
            `Classify this question about startup growth/distribution. Reply as JSON: ` +
            `{"mode": "broad" | "specific" | "my_app", "app": string | null}.\n` +
            `- "broad": thematic/general (e.g. "what are the best TikTok tactics?")\n` +
            `- "specific": about a particular app, founder, or tactic — set "app" to the app name if one is named\n` +
            `- "my_app": asking for advice for the asker's OWN app (phrases like "my app", "should I", "how do I grow")\n\n` +
            `Question: ${question}`,
        },
      ],
    });
    const parsed = JSON.parse(response.choices[0].message.content ?? "{}");
    const mode: Mode = ["broad", "specific", "my_app"].includes(parsed.mode)
      ? parsed.mode
      : "broad";
    return { mode, app: typeof parsed.app === "string" ? parsed.app : null };
  } catch {
    return { mode: "broad", app: null };
  }
}

/** The corpus is heavily skewed toward one channel, so raw top-k retrieval is
 *  almost all that channel. Cap how many chunks any single channel contributes
 *  to the front of the list (keeping rank order within and across channels),
 *  then append the overflow so nothing is lost. Lets Starter Story / Superwall
 *  surface when they're relevant instead of being crowded out. */
function diversifyByChannel(
  chunks: RetrievedChunk[],
  maxPerChannel: number,
  k: number,
): RetrievedChunk[] {
  const perChannel = new Map<string, number>();
  const front: RetrievedChunk[] = [];
  const overflow: RetrievedChunk[] = [];
  for (const chunk of chunks) {
    const count = perChannel.get(chunk.channel) ?? 0;
    if (count < maxPerChannel) {
      perChannel.set(chunk.channel, count + 1);
      front.push(chunk);
    } else {
      overflow.push(chunk);
    }
  }
  return [...front, ...overflow].slice(0, k);
}

async function retrieve(
  question: string,
  mode: Mode,
  app: string | null,
  competitors: string[],
): Promise<RetrievedChunk[]> {
  if (mode === "broad") {
    // Pull a wider candidate pool, then rebalance across channels down to 10.
    const summaries = await search(question, { k: 20, summariesOnly: true });
    const pool =
      summaries.length >= 4
        ? summaries
        : [...summaries, ...(await search(question, { k: 20 - summaries.length }))];
    return diversifyByChannel(pool, 4, 10);
  }
  if (mode === "specific") {
    // An app-filtered search is intentionally narrow — leave it as-is.
    const filtered = app ? await search(question, { k: 10, app }) : [];
    if (filtered.length > 0) return filtered;
    return diversifyByChannel(await search(question, { k: 20 }), 4, 10);
  }
  // my_app: fan the question out across the user's competitors, then rebalance.
  const fanned = await search(question, {
    k: 20,
    extraQueries: competitors.slice(0, 4).map((c) => `${question} ${c}`),
  });
  return diversifyByChannel(fanned, 4, 10);
}

function buildSystemPrompt(
  profile: ReturnType<typeof readProfile>,
  chunks: RetrievedChunk[],
): string {
  const excerpts = chunks
    .map((c, i) => {
      const label = `[${c.title} — ${c.channel} @ ${mmss(c.start_timestamp)}]`;
      return `EXCERPT ${i + 1} ${label}\nLINK: ${c.timestamp_url}\n${c.content}`;
    })
    .join("\n\n---\n\n");

  return `You are DistributionGPT, a distribution and growth advisor. You answer using ONLY the episode excerpts below, drawn from founder interviews and growth breakdowns.

THE USER'S APP (frame advice for it):
- Name: ${profile.app_name}
- What it is: ${profile.one_liner}
- Category: ${profile.category}
- Target audience: ${profile.target_audience}
- Competitor apps: ${profile.competitors.join(", ")}

RULES:
1. Ground every claim in the excerpts. If the excerpts don't cover the question, say so plainly — never invent facts, numbers, or episodes.
2. Cite as you go, using EXACTLY this format: [Episode Title — Channel @ mm:ss]. Use the labels provided with each excerpt verbatim. Cite at least once per distinct claim.
3. Prefer concrete tactics, numbers, and mechanisms over generalities. When several excerpts from different episodes or channels are relevant, draw on that range rather than leaning on a single source.
4. When the question is about growing the user's own app (or advice clearly applies), end with a short section titled "What this means for ${profile.app_name}" — 2-4 bullet points translating the findings to their app and audience.
5. Keep answers tight: short paragraphs, bullets where natural, no filler.

EXCERPTS:
${excerpts}`;
}

export async function POST(request: Request) {
  if (!process.env.OPENAI_API_KEY) {
    return jsonError("OPENAI_API_KEY is not configured in Vercel environment variables");
  }

  let messages: ChatMessage[];
  try {
    const body = (await request.json()) as { messages: ChatMessage[] };
    messages = body.messages;
  } catch {
    return jsonError("invalid request body", 400);
  }

  const question = messages?.filter((m) => m.role === "user").at(-1)?.content;
  if (!question) return jsonError("no user message", 400);

  const client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  let profile: ReturnType<typeof readProfile>;
  try {
    profile = readProfile();
  } catch (err) {
    return jsonError(`Profile failed: ${err instanceof Error ? err.message : String(err)}`);
  }

  const { mode, app } = await classify(client, question);

  let chunks: RetrievedChunk[] = [];
  try {
    chunks = await retrieve(question, mode, app, profile.competitors);
  } catch (err) {
    return jsonError(`Retrieval failed: ${err instanceof Error ? err.message : String(err)}`);
  }

  let stream: Awaited<ReturnType<typeof client.chat.completions.create>>;
  try {
    stream = await client.chat.completions.create({
      model: ANSWER_MODEL,
      stream: true,
      temperature: 0.4,
      messages: [
        { role: "system", content: buildSystemPrompt(profile, chunks) },
        ...messages.slice(-8),
      ],
    });
  } catch (err) {
    return jsonError(`Answer generation failed: ${err instanceof Error ? err.message : String(err)}`);
  }

  const encoder = new TextEncoder();
  const sources = dedupeSources(chunks);

  const body = new ReadableStream({
    async start(controller) {
      const send = (obj: unknown) =>
        controller.enqueue(encoder.encode(`data: ${JSON.stringify(obj)}\n\n`));
      send({ type: "sources", mode, sources });
      try {
        for await (const part of stream) {
          const delta = part.choices[0]?.delta?.content;
          if (delta) send({ type: "delta", text: delta });
        }
        send({ type: "done" });
      } catch (err) {
        send({ type: "error", message: err instanceof Error ? err.message : String(err) });
      } finally {
        controller.close();
      }
    },
  });

  return new Response(body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}

function dedupeSources(chunks: RetrievedChunk[]) {
  const seen = new Map<string, object>();
  for (const c of chunks) {
    if (!seen.has(c.video_id)) {
      seen.set(c.video_id, {
        video_id: c.video_id,
        title: c.title,
        channel: c.channel,
        url: c.url,
        timestamp_url: c.timestamp_url,
        start_timestamp: c.start_timestamp,
        is_web: !c.url.includes("youtube.com"),
      });
    }
  }
  return Array.from(seen.values());
}
