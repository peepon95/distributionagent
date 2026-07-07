import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

function resolveProjectRoot() {
  const cwd = process.cwd();
  if (existsSync(resolve(cwd, "pipeline"))) return cwd;
  const parent = resolve(cwd, "..");
  if (existsSync(resolve(parent, "pipeline"))) return parent;
  return cwd;
}

// Load the project-root .env (single source of truth for keys) into the
// Next.js server process without duplicating secrets into web/.env.local.
try {
  const envFile = readFileSync(resolve(resolveProjectRoot(), ".env"), "utf8");
  for (const line of envFile.split("\n")) {
    const match = line.match(/^([A-Z_]+)=(.*)$/);
    if (match && !process.env[match[1]]) {
      process.env[match[1]] = match[2].split(" #")[0].trim();
    }
  }
} catch {
  // .env missing — API routes will return a clear error.
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  images: {
    remotePatterns: [{ protocol: "https", hostname: "i.ytimg.com" }],
  },
};

export default nextConfig;
