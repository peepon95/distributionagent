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

export function readProfile(): AppProfile {
  return JSON.parse(readFileSync(PROFILE_PATH, "utf8"));
}

export function writeProfile(profile: AppProfile): void {
  writeFileSync(PROFILE_PATH, JSON.stringify(profile, null, 2) + "\n");
}
