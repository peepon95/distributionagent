import { readdirSync } from "node:fs";
import { resolve } from "node:path";
import { NextResponse } from "next/server";
import { PROJECT_ROOT } from "@/lib/retrieval";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export async function GET() {
  let episodes = 0;
  try {
    const rawDir = resolve(PROJECT_ROOT, "data/raw");
    for (const channel of readdirSync(rawDir, { withFileTypes: true })) {
      if (!channel.isDirectory()) continue;
      episodes += readdirSync(resolve(rawDir, channel.name)).filter((f) =>
        f.endsWith(".json"),
      ).length;
    }
  } catch {
    // data dir may not exist yet
  }
  return NextResponse.json({ episodes });
}
