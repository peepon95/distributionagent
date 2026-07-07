import { readFileSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { PROJECT_ROOT } from "./retrieval";

export interface AppProfile {
  app_name: string;
  one_liner: string;
  category: string;
  target_audience: string;
  competitors: string[];
}

const PROFILE_PATH = resolve(PROJECT_ROOT, "profile.json");

declare global {
  var __distributiongpt_profile: AppProfile | undefined;
}

export function readProfile(): AppProfile {
  if (globalThis.__distributiongpt_profile) {
    return globalThis.__distributiongpt_profile;
  }
  const profile = JSON.parse(readFileSync(PROFILE_PATH, "utf8")) as AppProfile;
  globalThis.__distributiongpt_profile = profile;
  return profile;
}

export function writeProfile(profile: AppProfile): void {
  globalThis.__distributiongpt_profile = profile;
  try {
    writeFileSync(PROFILE_PATH, JSON.stringify(profile, null, 2) + "\n");
  } catch {
    // Vercel's deployment filesystem is read-only. Keep the in-memory value
    // for the current instance instead of throwing a 500.
  }
}
