"use client";

import { motion } from "framer-motion";
import type { Source } from "./types";

/** Renders assistant text: paragraphs, bullets, bold, **citation pills**,
 *  and a word-by-word fade for the currently streaming message. */

const CITATION = /\[([^\[\]]+ — [^\[\]]+ @ \d+:\d{2})\]/g;

function findSource(label: string, sources: Source[]): Source | undefined {
  const title = label.split(" — ")[0]?.trim().toLowerCase();
  return sources.find((s) => s.title.toLowerCase() === title);
}

function timestampUrl(label: string, source: Source): string {
  const match = label.match(/@ (\d+):(\d{2})$/);
  if (!match || source.is_web) return source.url;
  const seconds = parseInt(match[1], 10) * 60 + parseInt(match[2], 10);
  return `${source.url}&t=${seconds}s`;
}

function CitationPill({ label, sources }: { label: string; sources: Source[] }) {
  const source = findSource(label, sources);
  const short = label.length > 58 ? label.slice(0, 55) + "…" : label;
  if (!source) {
    return (
      <span className="mx-0.5 inline-block rounded-full bg-ink/5 px-2 py-0.5 text-xs font-medium text-ink/60">
        {short}
      </span>
    );
  }
  return (
    <motion.a
      href={timestampUrl(label, source)}
      target="_blank"
      rel="noreferrer"
      whileHover={{ y: -1.5, scale: 1.03 }}
      className="mx-0.5 inline-block max-w-full truncate rounded-full bg-blueberry/12 px-2 py-0.5 align-middle text-xs font-semibold text-[#4A66D9] shadow-sm transition-colors hover:bg-blueberry/25"
      title={label}
    >
      ▶ {short}
    </motion.a>
  );
}

function InlineText({ text, animate }: { text: string; animate: boolean }) {
  // split out **bold** spans
  const parts = text.split(/(\*\*[^*]+\*\*)/g).filter(Boolean);
  return (
    <>
      {parts.map((part, i) => {
        const bold = part.startsWith("**") && part.endsWith("**");
        const content = bold ? part.slice(2, -2) : part;
        if (!animate) {
          return bold ? <strong key={i}>{content}</strong> : <span key={i}>{content}</span>;
        }
        const words = content.split(/(\s+)/);
        const node = words.map((w, j) =>
          w.trim() ? (
            <motion.span
              key={j}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.25 }}
            >
              {w}
            </motion.span>
          ) : (
            <span key={j}>{w}</span>
          ),
        );
        return bold ? <strong key={i}>{node}</strong> : <span key={i}>{node}</span>;
      })}
    </>
  );
}

function Line({
  line,
  sources,
  animate,
}: {
  line: string;
  sources: Source[];
  animate: boolean;
}) {
  const segments: React.ReactNode[] = [];
  let last = 0;
  let match: RegExpExecArray | null;
  const re = new RegExp(CITATION.source, "g");
  while ((match = re.exec(line)) !== null) {
    if (match.index > last) {
      segments.push(
        <InlineText key={last} text={line.slice(last, match.index)} animate={animate} />,
      );
    }
    segments.push(<CitationPill key={match.index} label={match[1]} sources={sources} />);
    last = match.index + match[0].length;
  }
  if (last < line.length) {
    segments.push(<InlineText key={last} text={line.slice(last)} animate={animate} />);
  }
  return <>{segments}</>;
}

export default function MessageBody({
  content,
  sources,
  streaming,
}: {
  content: string;
  sources: Source[];
  streaming: boolean;
}) {
  const blocks = content.split("\n");
  return (
    <div className="space-y-2 leading-relaxed">
      {blocks.map((line, i) => {
        const trimmed = line.trim();
        if (!trimmed) return null;
        const isBullet = /^[-•*]\s+/.test(trimmed);
        const isHeading = /^#{1,4}\s+/.test(trimmed) || /^What this means for/i.test(trimmed);
        const text = isBullet
          ? trimmed.replace(/^[-•*]\s+/, "")
          : trimmed.replace(/^#{1,4}\s+/, "");
        if (isHeading) {
          return (
            <p key={i} className="pt-2 font-display text-base font-bold tracking-tight text-tangerine">
              <Line line={text} sources={sources} animate={streaming} />
            </p>
          );
        }
        if (isBullet) {
          return (
            <p key={i} className="flex gap-2 pl-1">
              <span className="mt-[9px] h-1.5 w-1.5 shrink-0 rounded-full bg-tangerine" />
              <span>
                <Line line={text} sources={sources} animate={streaming} />
              </span>
            </p>
          );
        }
        return (
          <p key={i}>
            <Line line={text} sources={sources} animate={streaming} />
          </p>
        );
      })}
    </div>
  );
}
