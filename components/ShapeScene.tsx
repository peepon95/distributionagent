"use client";

import { motion, useReducedMotion } from "framer-motion";
import { useEffect, useState } from "react";

/** Clay-style scene: a few deliberate, tactile shapes floating over the hero. */

interface ShapeSpec {
  key: string;
  className: string;
  style: React.CSSProperties;
  depth: number; // parallax multiplier
  float: number; // ambient float amplitude (px)
  duration: number;
}

const SHAPES: ShapeSpec[] = [
  {
    key: "coin",
    className: "absolute rounded-full",
    style: {
      width: 92,
      height: 92,
      left: "8%",
      top: "12%",
      background:
        "radial-gradient(circle at 32% 28%, #FFD9A8 0%, #FF8A3D 58%, #E06A1F 100%)",
      boxShadow:
        "inset 0 2px 6px rgba(255,255,255,0.55), 0 18px 36px rgba(224,106,31,0.28)",
    },
    depth: 1.6,
    float: 12,
    duration: 9,
  },
  {
    key: "card",
    className: "absolute rounded-2xl",
    style: {
      width: 120,
      height: 84,
      right: "10%",
      top: "8%",
      rotate: "8deg",
      background:
        "linear-gradient(135deg, #FFFFFF 0%, #FFE9D6 78%, #FFD9BC 100%)",
      border: "1px solid rgba(255,138,61,0.25)",
      boxShadow: "0 2px 4px rgba(33,29,22,0.06), 0 20px 44px rgba(224,106,31,0.18)",
    },
    depth: 1.1,
    float: 9,
    duration: 11,
  },
  {
    key: "orb",
    className: "absolute rounded-full",
    style: {
      width: 64,
      height: 64,
      right: "22%",
      bottom: "16%",
      background:
        "radial-gradient(circle at 30% 30%, #C9D6FF 0%, #6C8CFF 62%, #4A66D9 100%)",
      boxShadow:
        "inset 0 2px 5px rgba(255,255,255,0.6), 0 16px 32px rgba(76,102,217,0.3)",
    },
    depth: 2.1,
    float: 14,
    duration: 8,
  },
  {
    key: "ring",
    className: "absolute rounded-full",
    style: {
      width: 110,
      height: 110,
      left: "16%",
      bottom: "8%",
      border: "18px solid #FF9EC2",
      boxShadow:
        "0 16px 36px rgba(255,158,194,0.35), inset 0 2px 4px rgba(255,255,255,0.4)",
    },
    depth: 0.8,
    float: 10,
    duration: 12,
  },
  {
    key: "pill",
    className: "absolute rounded-full",
    style: {
      width: 96,
      height: 44,
      left: "42%",
      top: "4%",
      rotate: "-12deg",
      background: "linear-gradient(120deg, #A7E8C5 0%, #5FC98F 100%)",
      boxShadow:
        "inset 0 2px 5px rgba(255,255,255,0.55), 0 14px 30px rgba(95,201,143,0.3)",
    },
    depth: 1.4,
    float: 11,
    duration: 10,
  },
  {
    key: "spark",
    className: "absolute",
    style: {
      width: 48,
      height: 48,
      right: "38%",
      bottom: "4%",
      background: "#FFC93D",
      clipPath:
        "polygon(50% 0%, 61% 35%, 98% 35%, 68% 57%, 79% 91%, 50% 70%, 21% 91%, 32% 57%, 2% 35%, 39% 35%)",
      filter: "drop-shadow(0 12px 22px rgba(255,201,61,0.45))",
    },
    depth: 2.4,
    float: 13,
    duration: 7,
  },
];

export default function ShapeScene() {
  const reduceMotion = useReducedMotion();
  const [mouse, setMouse] = useState({ x: 0, y: 0 });

  useEffect(() => {
    if (reduceMotion) return;
    const onMove = (e: MouseEvent) => {
      setMouse({
        x: (e.clientX / window.innerWidth - 0.5) * 2,
        y: (e.clientY / window.innerHeight - 0.5) * 2,
      });
    };
    window.addEventListener("mousemove", onMove);
    return () => window.removeEventListener("mousemove", onMove);
  }, [reduceMotion]);

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-visible">
      {SHAPES.map((shape, i) => (
        <motion.div
          key={shape.key}
          className={shape.className}
          style={shape.style}
          initial={{ opacity: 0, scale: 0.6, y: 24 }}
          animate={{
            opacity: 1,
            scale: 1,
            y: reduceMotion ? 0 : [0, -shape.float, 0],
            x: reduceMotion ? 0 : mouse.x * shape.depth * 6,
          }}
          transition={{
            opacity: { duration: 0.5, delay: 0.08 * i },
            scale: { type: "spring", stiffness: 160, damping: 14, delay: 0.08 * i },
            y: reduceMotion
              ? undefined
              : {
                  duration: shape.duration,
                  repeat: Infinity,
                  ease: "easeInOut",
                  delay: 0.08 * i,
                },
            x: { type: "spring", stiffness: 60, damping: 20 },
          }}
        />
      ))}
    </div>
  );
}
