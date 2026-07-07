"use client";

import { useEffect, useState } from "react";
import { motion } from "framer-motion";

interface Profile {
  app_name: string;
  one_liner: string;
  category: string;
  target_audience: string;
  competitors: string[];
}

export default function ProfilePanel() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    fetch("/api/profile")
      .then((r) => r.json())
      .then(setProfile)
      .catch(() => {});
  }, []);

  async function save() {
    if (!profile) return;
    setSaving(true);
    await fetch("/api/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    setSaving(false);
    setSaved(true);
    setTimeout(() => setSaved(false), 1600);
  }

  if (!profile) return null;

  const field =
    "w-full rounded-xl border border-ink/10 bg-paper px-2.5 py-1.5 text-xs focus:border-blueberry";

  return (
    <div>
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-1 font-display text-xs font-bold uppercase tracking-wider text-ink/50 transition-colors hover:text-ink"
        aria-expanded={open}
      >
        <span>
          My App Profile
          <span className="ml-2 rounded-full bg-blueberry/15 px-2 py-0.5 text-[10px] normal-case tracking-normal text-[#4A66D9]">
            {profile.app_name}
          </span>
        </span>
        <span aria-hidden>{open ? "−" : "+"}</span>
      </button>
      {open && (
        <motion.div
          initial={{ opacity: 0, height: 0 }}
          animate={{ opacity: 1, height: "auto" }}
          className="mt-2 space-y-2 overflow-hidden px-1"
        >
          {(
            [
              ["app_name", "App name"],
              ["one_liner", "One-liner"],
              ["category", "Category"],
              ["target_audience", "Target audience"],
            ] as const
          ).map(([key, label]) => (
            <label key={key} className="block text-[10px] font-medium text-ink/50">
              {label}
              <input
                className={field}
                value={profile[key]}
                onChange={(e) => setProfile({ ...profile, [key]: e.target.value })}
              />
            </label>
          ))}
          <label className="block text-[10px] font-medium text-ink/50">
            Competitors (comma-separated)
            <input
              className={field}
              value={profile.competitors.join(", ")}
              onChange={(e) =>
                setProfile({
                  ...profile,
                  competitors: e.target.value.split(",").map((s) => s.trim()).filter(Boolean),
                })
              }
            />
          </label>
          <motion.button
            whileHover={{ y: -1 }}
            whileTap={{ scale: 0.97 }}
            onClick={save}
            disabled={saving}
            className="w-full rounded-xl bg-tangerine px-3 py-1.5 text-xs font-semibold text-white shadow-card transition-shadow hover:shadow-lift disabled:opacity-60"
          >
            {saved ? "Saved ✓" : saving ? "Saving…" : "Save profile"}
          </motion.button>
        </motion.div>
      )}
    </div>
  );
}
