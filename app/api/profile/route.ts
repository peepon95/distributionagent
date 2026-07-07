import { NextResponse } from "next/server";
import { readProfile, writeProfile, type AppProfile } from "@/lib/profile";

export const runtime = "nodejs";

export async function GET() {
  return NextResponse.json(readProfile());
}

export async function PUT(request: Request) {
  const profile = (await request.json()) as AppProfile;
  if (!profile.app_name || !Array.isArray(profile.competitors)) {
    return NextResponse.json({ error: "invalid profile" }, { status: 400 });
  }
  writeProfile(profile);
  return NextResponse.json(profile);
}
