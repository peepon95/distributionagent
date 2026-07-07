"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useState } from "react";
import ShapeScene from "./ShapeScene";

/** Pool of example prompts spanning the corpus — 4 shown at a time,
 *  the shuffle button swaps in the others. Keep each under ~8 words. */
const PROMPTS: string[] = [
  "Viral TikTok format for my dating app",
  "Best paywall tactics from Superwall?",
  "What makes UGC ads convert?",
  "How do founders pick their first channel?",
  "ASO tactics that actually move downloads",
  "Reddit marketing lessons from founders",
  "How did Cal AI's competitors grow?",
  "Hard paywall or free trial first?",
];

const CHIP_COLORS = [
  "bg-tangerine/15 hover:bg-tangerine/25",
  "bg-blueberry/15 hover:bg-blueberry/25",
  "bg-bubblegum/20 hover:bg-bubblegum/30",
  "bg-[#5FC98F]/15 hover:bg-[#5FC98F]/25",
];

export default function Hero({
  episodeCount,
  onAsk,
}: {
  episodeCount: number | null;
  onAsk: (q: string) => void;
}) {
  const reduceMotion = useReducedMotion();
  const [visible, setVisible] = useState<string[]>(() => PROMPTS.slice(0, 4));
  const [hasShuffled, setHasShuffled] = useState(false);

  function shuffle() {
    setHasShuffled(true);
    setVisible((current) => {
      const rest = PROMPTS.filter((p) => !current.includes(p));
      return [...rest].sort(() => Math.random() - 0.5).slice(0, 4);
    });
  }

  return (
    <div className="relative flex h-full flex-col items-center justify-center px-6 py-16">
      <ShapeScene />
      <motion.span
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        className="relative z-10 mb-4 flex items-center gap-2 rounded-full bg-white px-3.5 py-1.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-ink/60 shadow-card"
      >
        <span className="h-1.5 w-1.5 rounded-full bg-tangerine" aria-hidden />
        Your distribution research agent
      </motion.span>
      <motion.h1
        initial={{ opacity: 0, y: 16 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ type: "spring", stiffness: 120, damping: 16 }}
        className="relative z-10 max-w-2xl text-center font-display text-5xl font-extrabold leading-[1.05] tracking-tight md:text-6xl"
      >
        Ask{" "}
        <span className="text-tangerine">
          {episodeCount ? episodeCount.toLocaleString() : "hundreds of"}
        </span>{" "}
        episodes of growth advice
      </motion.h1>
      <motion.p
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ delay: 0.12, type: "spring", stiffness: 120, damping: 16 }}
        className="relative z-10 mt-5 max-w-md text-center text-lg text-ink/60"
      >
        Founder interviews and growth breakdowns, distilled — every answer cites
        the exact minute of the episode.
      </motion.p>
      <div className="relative z-10 mt-10 flex max-w-xl flex-col items-center gap-3">
        <motion.div
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.2 }}
          className="flex items-center gap-2"
        >
          <span className="text-[11px] font-semibold uppercase tracking-[0.14em] text-ink/40">
            Try asking
          </span>
          <motion.button
            type="button"
            onClick={shuffle}
            whileTap={reduceMotion ? undefined : { rotate: 180, scale: 0.9 }}
            aria-label="Shuffle example prompts"
            title="Show other example prompts"
            className="flex h-6 w-6 items-center justify-center rounded-full bg-white text-sm text-ink/50 shadow-card transition-colors hover:bg-blueberry/15 hover:text-ink"
          >
            ↻
          </motion.button>
        </motion.div>
        <div className="flex flex-wrap items-center justify-center gap-3">
          <AnimatePresence mode="popLayout">
            {visible.map((q, i) => (
              <motion.button
                key={q}
                layout
                initial={
                  reduceMotion
                    ? { opacity: 0 }
                    : { opacity: 0, y: 14, scale: 0.95 }
                }
                animate={{ opacity: 1, y: 0, scale: 1 }}
                exit={
                  reduceMotion
                    ? { opacity: 0, transition: { duration: 0.1 } }
                    : {
                        opacity: 0,
                        y: -10,
                        scale: 0.9,
                        transition: { duration: 0.15 },
                      }
                }
                transition={{
                  delay: (hasShuffled ? 0 : 0.25) + i * (hasShuffled ? 0.04 : 0.07),
                  type: "spring",
                  stiffness: 200,
                  damping: 15,
                }}
                whileHover={reduceMotion ? undefined : { y: -3 }}
                whileTap={{ scale: 0.97 }}
                onClick={() => onAsk(q)}
                className={`rounded-full px-4 py-2 text-sm font-medium text-ink shadow-card transition-colors ${CHIP_COLORS[i % CHIP_COLORS.length]}`}
              >
                {q}
              </motion.button>
            ))}
          </AnimatePresence>
        </div>
      </div>
    </div>
  );
}
