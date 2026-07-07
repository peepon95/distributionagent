import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import { resolve } from "node:path";

const projectRoot = process.cwd();
const source = resolve(projectRoot, "web", ".next");
const target = resolve(projectRoot, ".next");

if (!existsSync(source)) {
  console.error(`Next build output not found at ${source}`);
  process.exit(1);
}

rmSync(target, { recursive: true, force: true });
mkdirSync(target, { recursive: true });
cpSync(source, target, { recursive: true });
