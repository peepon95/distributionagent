"use client";

import { AnimatePresence, motion, useReducedMotion } from "framer-motion";
import { useCallback, useEffect, useRef, useState } from "react";
import Hero from "@/components/Hero";
import MessageBody from "@/components/MessageBody";
import ProfilePanel from "@/components/ProfilePanel";
import SourceTray from "@/components/SourceTray";
import type { Conversation, Message, Source } from "@/components/types";

const STORAGE_KEY = "distributiongpt.conversations.v1";

function newConversation(): Conversation {
  return { id: crypto.randomUUID(), title: "New chat", messages: [], updatedAt: Date.now() };
}

export default function Page() {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [input, setInput] = useState("");
  const [episodeCount, setEpisodeCount] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const recentsRef = useRef<HTMLDivElement>(null);
  const reduceMotion = useReducedMotion();

  // hydrate from localStorage
  useEffect(() => {
    try {
      const stored = JSON.parse(localStorage.getItem(STORAGE_KEY) ?? "[]");
      if (Array.isArray(stored) && stored.length) {
        setConversations(stored);
        setActiveId(stored[0].id);
        return;
      }
    } catch {}
    const fresh = newConversation();
    setConversations([fresh]);
    setActiveId(fresh.id);
  }, []);

  useEffect(() => {
    if (conversations.length) {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(conversations.slice(0, 30)));
    }
  }, [conversations]);

  useEffect(() => {
    fetch("/api/stats")
      .then((r) => r.json())
      .then((d) => setEpisodeCount(d.episodes ?? null))
      .catch(() => {});
  }, []);

  const active = conversations.find((c) => c.id === activeId) ?? null;
  const lastSources: Source[] =
    active?.messages.filter((m) => m.sources?.length).at(-1)?.sources ?? [];
  const inConversation =
    active?.messages.some((m) => m.role === "assistant") ?? false;

  const updateActive = useCallback(
    (fn: (c: Conversation) => Conversation) => {
      setConversations((all) =>
        all
          .map((c) => (c.id === activeId ? fn(c) : c))
          .sort((a, b) => b.updatedAt - a.updatedAt),
      );
    },
    [activeId],
  );

  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [active?.messages, streaming]);

  async function ask(question: string) {
    if (!question.trim() || streaming || !active) return;
    setError(null);
    setInput("");
    const history: Message[] = [...active.messages, { role: "user", content: question }];
    updateActive((c) => ({
      ...c,
      title: c.messages.length ? c.title : question.slice(0, 48),
      messages: [...history, { role: "assistant", content: "", sources: [] }],
      updatedAt: Date.now(),
    }));
    setStreaming(true);

    try {
      const res = await fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          messages: history.map(({ role, content }) => ({ role, content })),
        }),
      });
      if (!res.ok || !res.body) {
        const detail = await res.json().catch(() => ({}));
        throw new Error(detail.error ?? `HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let text = "";
      let sources: Source[] = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const events = buffer.split("\n\n");
        buffer = events.pop() ?? "";
        for (const event of events) {
          if (!event.startsWith("data: ")) continue;
          const payload = JSON.parse(event.slice(6));
          if (payload.type === "sources") sources = payload.sources;
          if (payload.type === "delta") text += payload.text;
          if (payload.type === "error") throw new Error(payload.message);
          updateActive((c) => ({
            ...c,
            messages: [
              ...c.messages.slice(0, -1),
              { role: "assistant", content: text, sources },
            ],
            updatedAt: Date.now(),
          }));
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      updateActive((c) => ({
        ...c,
        messages: c.messages.filter(
          (m, i) => !(i === c.messages.length - 1 && m.role === "assistant" && !m.content),
        ),
      }));
    } finally {
      setStreaming(false);
    }
  }

  function startNew() {
    const fresh = newConversation();
    setConversations((all) => [fresh, ...all]);
    setActiveId(fresh.id);
    setError(null);
    setSidebarOpen(false);
  }

  function deleteConversation(id: string) {
    const remaining = conversations.filter((c) => c.id !== id);
    if (remaining.length === 0) {
      const fresh = newConversation();
      setConversations([fresh]);
      setActiveId(fresh.id);
      return;
    }
    setConversations(remaining);
    // conversations are kept sorted newest-first, so remaining[0] is the
    // most recent one left.
    if (id === activeId) setActiveId(remaining[0].id);
  }

  /** Wordmark click: go to the empty/home state without piling up
   *  duplicate empty conversations. */
  function goHome() {
    setError(null);
    setSidebarOpen(false);
    if (active && active.messages.length === 0) return; // already home
    const empty = conversations.find((c) => c.messages.length === 0);
    if (empty) {
      setActiveId(empty.id);
      return;
    }
    startNew();
  }

  function focusRecents() {
    recentsRef.current?.focus({ preventScroll: true });
    recentsRef.current?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "nearest",
    });
  }

  return (
    <div className="flex h-dvh">
      {/* Sidebar */}
      <aside
        className={`${
          sidebarOpen ? "flex" : "hidden"
        } absolute inset-y-0 left-0 z-40 w-72 flex-col gap-5 overflow-y-auto bg-white/85 p-4 shadow-lift backdrop-blur-md md:static md:flex md:bg-transparent md:shadow-none`}
      >
        <div className="px-1">
          <motion.button
            whileHover={{ y: -1 }}
            whileTap={{ scale: 0.98 }}
            onClick={goHome}
            aria-label="DistributionGPT — go to home"
            className="cursor-pointer rounded-md font-display text-lg font-extrabold tracking-tight transition-opacity hover:opacity-75"
          >
            Distribution<span className="text-tangerine">GPT</span>
          </motion.button>
        </div>

        <nav className="space-y-0.5 px-1" aria-label="Sidebar">
          <button
            onClick={startNew}
            className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm font-semibold transition-colors hover:bg-ink/5"
          >
            <span
              aria-hidden
              className="flex h-5 w-5 items-center justify-center rounded-full bg-tangerine text-sm font-bold leading-none text-white"
            >
              +
            </span>
            New chat
          </button>
          <button
            onClick={focusRecents}
            className="flex w-full items-center gap-2.5 rounded-xl px-2.5 py-2 text-left text-sm font-semibold transition-colors hover:bg-ink/5"
          >
            <svg
              aria-hidden
              viewBox="0 0 20 20"
              fill="none"
              stroke="currentColor"
              strokeWidth="1.8"
              className="h-5 w-5 text-ink/60"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                d="M17 9.5c0 3.3-3.1 6-7 6-.9 0-1.8-.15-2.6-.42L3.5 16.5l1-2.8C3.6 12.6 3 11.1 3 9.5c0-3.3 3.1-6 7-6s7 2.7 7 6Z"
              />
            </svg>
            Chats
          </button>
        </nav>

        <div
          ref={recentsRef}
          tabIndex={-1}
          className="rounded-card bg-white p-3 shadow-card outline-none"
        >
          <h3 className="mb-2 px-1 font-display text-xs font-bold uppercase tracking-wider text-ink/50">
            Recents
          </h3>
          <ul className="space-y-1">
            {conversations.slice(0, 10).map((c) => (
              <li key={c.id} className="group relative">
                <button
                  onClick={() => {
                    setActiveId(c.id);
                    setSidebarOpen(false);
                  }}
                  className={`w-full truncate rounded-xl py-1.5 pl-2.5 pr-8 text-left text-xs transition-colors ${
                    c.id === activeId
                      ? "bg-tangerine/15 font-semibold"
                      : "hover:bg-ink/5"
                  }`}
                >
                  {c.title}
                </button>
                <button
                  onClick={() => deleteConversation(c.id)}
                  aria-label="Delete conversation"
                  className="absolute right-1.5 top-1/2 flex h-5 w-5 -translate-y-1/2 items-center justify-center rounded-full text-sm leading-none text-ink/40 opacity-0 transition-opacity hover:bg-bubblegum/20 hover:text-ink focus-visible:opacity-100 group-focus-within:opacity-100 group-hover:opacity-100"
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
        </div>

        <AnimatePresence initial={false}>
          {inConversation && (
            <motion.div
              key="source-tray"
              initial={reduceMotion ? { opacity: 0 } : { opacity: 0, x: 48 }}
              animate={{ opacity: 1, x: 0 }}
              exit={
                reduceMotion
                  ? { opacity: 0, transition: { duration: 0.1 } }
                  : { opacity: 0, x: -32, transition: { duration: 0.18 } }
              }
              transition={{ type: "spring", stiffness: 260, damping: 24 }}
              className="rounded-card bg-white p-3 shadow-card"
            >
              <SourceTray sources={lastSources} />
            </motion.div>
          )}
        </AnimatePresence>

        <div className="mt-auto rounded-card bg-white p-3 shadow-card">
          <ProfilePanel />
        </div>
      </aside>

      {/* Main column */}
      <main className="relative flex min-w-0 flex-1 flex-col">
        <button
          onClick={() => setSidebarOpen(!sidebarOpen)}
          className="absolute left-3 top-3 z-30 rounded-full bg-white px-3 py-1.5 text-xs font-semibold shadow-card md:hidden"
          aria-label="Toggle sidebar"
        >
          ☰
        </button>

        {active && active.messages.length === 0 ? (
          <Hero episodeCount={episodeCount} onAsk={ask} />
        ) : (
          <div ref={scrollRef} className="chat-scroll flex-1 overflow-y-auto px-4 pb-8 pt-14 md:px-10">
            <div className="mx-auto max-w-2xl space-y-5">
              {active?.messages.map((message, i) => {
                const isLast = i === active.messages.length - 1;
                return message.role === "user" ? (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="ml-auto max-w-[85%] rounded-card rounded-br-md bg-ink px-4 py-3 text-sm text-paper shadow-card"
                  >
                    {message.content}
                  </motion.div>
                ) : (
                  <motion.div
                    key={i}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="max-w-[95%] rounded-card rounded-bl-md bg-white px-5 py-4 text-sm shadow-card"
                  >
                    {message.content ? (
                      <MessageBody
                        content={message.content}
                        sources={message.sources ?? []}
                        streaming={streaming && isLast}
                      />
                    ) : (
                      <ThinkingDots />
                    )}
                  </motion.div>
                );
              })}
              {error && (
                <div className="rounded-card bg-bubblegum/20 px-4 py-3 text-sm text-ink">
                  <strong>Something broke:</strong> {error}
                </div>
              )}
            </div>
          </div>
        )}

        {/* Composer */}
        <div className="px-4 pb-5 md:px-10">
          <form
            onSubmit={(e) => {
              e.preventDefault();
              ask(input);
            }}
            className="mx-auto flex max-w-2xl items-end gap-2 rounded-big bg-white p-2 shadow-lift"
          >
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  ask(input);
                }
              }}
              rows={1}
              placeholder={
                streaming ? "Answering…" : "Ask about growth, paywalls, TikTok, your app…"
              }
              disabled={streaming}
              className="max-h-40 min-h-[44px] flex-1 resize-none bg-transparent px-3 py-2.5 text-sm outline-none placeholder:text-ink/35 disabled:opacity-60"
            />
            <motion.button
              type="submit"
              whileHover={{ y: -2 }}
              whileTap={{ scale: 0.95 }}
              disabled={streaming || !input.trim()}
              className="rounded-2xl bg-tangerine px-5 py-3 text-sm font-bold text-white shadow-card transition-shadow hover:shadow-lift disabled:opacity-40"
            >
              Ask
            </motion.button>
          </form>
        </div>
      </main>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex gap-1.5 py-1" aria-label="Thinking">
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          className="h-2 w-2 rounded-full bg-tangerine"
          animate={{ y: [0, -5, 0], opacity: [0.4, 1, 0.4] }}
          transition={{ duration: 0.9, repeat: Infinity, delay: i * 0.15 }}
        />
      ))}
    </div>
  );
}
