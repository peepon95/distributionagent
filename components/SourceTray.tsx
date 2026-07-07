"use client";

import { AnimatePresence, motion } from "framer-motion";
import type { Source } from "./types";

/** Signature element: cited episodes slide into the tray like collected
 *  trading cards — springy entrance, slight desk-toss rotation. */

const ROTATIONS = [-2.2, 1.6, -1.2, 2.4, -1.8, 1.1];

function thumb(source: Source): string | null {
  return source.is_web ? null : `https://i.ytimg.com/vi/${source.video_id}/mqdefault.jpg`;
}

export default function SourceTray({ sources }: { sources: Source[] }) {
  return (
    <div>
      <h3 className="mb-2 px-1 font-display text-xs font-bold uppercase tracking-wider text-ink/50">
        Sources{" "}
        {sources.length > 0 && (
          <span className="ml-1 rounded-full bg-bubblegum/30 px-1.5 py-0.5 text-[10px] text-ink">
            {sources.length}
          </span>
        )}
      </h3>
      {sources.length === 0 ? (
        <p className="px-1 text-xs text-ink/40">
          Episodes cited in the answer collect here, like trading cards.
        </p>
      ) : (
        <ul className="space-y-2.5">
          <AnimatePresence initial={false}>
            {sources.map((source, i) => (
              <motion.li
                key={source.video_id}
                initial={{ opacity: 0, x: 60, rotate: 6 }}
                animate={{ opacity: 1, x: 0, rotate: ROTATIONS[i % ROTATIONS.length] }}
                exit={{ opacity: 0, x: -40 }}
                transition={{ type: "spring", stiffness: 260, damping: 22, delay: i * 0.06 }}
              >
                <motion.a
                  href={source.timestamp_url}
                  target="_blank"
                  rel="noreferrer"
                  whileHover={{ y: -3, rotate: 0, scale: 1.02 }}
                  className="block overflow-hidden rounded-2xl bg-white shadow-card transition-shadow hover:shadow-lift"
                >
                  {thumb(source) ? (
                    // eslint-disable-next-line @next/next/no-img-element
                    <img
                      src={thumb(source)!}
                      alt=""
                      className="aspect-video w-full object-cover"
                      loading="lazy"
                    />
                  ) : (
                    <div className="flex aspect-video w-full items-center justify-center bg-gradient-to-br from-blueberry/25 via-bubblegum/25 to-tangerine/25 font-display text-2xl font-extrabold text-ink/30">
                      Aa
                    </div>
                  )}
                  <div className="p-2.5">
                    <p className="line-clamp-2 text-xs font-semibold leading-snug">
                      {source.title}
                    </p>
                    <span className="mt-1.5 inline-block rounded-full bg-tangerine/15 px-2 py-0.5 text-[10px] font-medium text-ink/70">
                      {source.channel}
                    </span>
                  </div>
                </motion.a>
              </motion.li>
            ))}
          </AnimatePresence>
        </ul>
      )}
    </div>
  );
}
