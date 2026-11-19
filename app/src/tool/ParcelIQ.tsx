// ParcelIQ: the chat, opened from the map's ParcelIQ button. On desktop and laptop it stands at the right edge (its
// left edge drags its width), or beside the Details panel (ToolPage, with the drag bar between them). Same Ask backend and browser tools
// as AskBox. An answer waits at least MIN_THINK_MS behind the thinking pill, so a fast reply does not flash.
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowUp, ArrowUpRight, Eraser, ListPlus, Sparkles, X } from 'lucide-react';
import { cx } from '../lib/cx';
import { ask, type Turn } from '../agent/client';
import { browserProvider } from '../agent/browserProvider';
import { askReply, askTags, type AskTags } from './askTags';
import { Answer, useAskContext } from './AskBox';
import { ThinkingPill } from './ThinkingPill';
import { CHAT_W_DEFAULT, useChatOpen } from './layout';
import { useTool } from './store';

/** The least time the thinking pill shows before an answer, in ms. */
export const MIN_THINK_MS = 4000;
export const EXPLAIN_MORE = 'Explain more';

const TOPICS = ['What is an ADU?', 'Which towns allow ADUs by right?', 'What would the state bill change?', 'How much would a backyard cottage cost?', 'Can I rent it out?'];
export const LOT_TOPIC = 'Can I build an ADU on this lot?';

interface Msg {
  role: 'user' | 'assistant';
  text: string;
  tools?: string[];
  error?: boolean;
  tags?: AskTags;
}

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** The chat's conversation, kept while the chat is closed and opened again (a module store, one per page). */
const memory: { msgs: Msg[]; history: Turn[] } = { msgs: [], history: [] };

/** `resize`: ParcelIQ stands alone and its left edge drags its width. */
export default function ParcelIQ({ style, onClose, resize }: { style?: CSSProperties; onClose: () => void; resize?: { width: number; min: number; max: number; onWidth: (w: number, save?: boolean) => void } }) {
  const [msgs, setMsgsState] = useState<Msg[]>(memory.msgs);
  const [history, setHistoryState] = useState<Turn[]>(memory.history);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState('');
  const { context } = useAskContext();
  const hasLot = useTool((s) => !!s.spot);
  const reduce = useReducedMotion();
  const listRef = useRef<HTMLDivElement>(null);
  const boxRef = useRef<HTMLTextAreaElement>(null);
  const setMsgs = (f: (m: Msg[]) => Msg[]) =>
    setMsgsState((m) => {
      const next = f(m);
      memory.msgs = next;
      return next;
    });
  const setHistory = (h: Turn[]) => {
    memory.history = h;
    setHistoryState(h);
  };

  // Newest message in view.
  useEffect(() => {
    const el = listRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: reduce ? 'auto' : 'smooth' });
  }, [msgs.length, busy, reduce]);
  useEffect(() => boxRef.current?.focus(), []);

  // Escape closes the chat (not while another dialog, such as the Lot report, is open). Captured first, so the
  // page's own Escape (which deselects the lot) does not also run.
  useEffect(() => {
    const esc = (e: KeyboardEvent) => {
      if (e.key !== 'Escape' || document.querySelector('[aria-modal="true"]')) return;
      e.stopImmediatePropagation();
      onClose();
    };
    window.addEventListener('keydown', esc, true);
    return () => window.removeEventListener('keydown', esc, true);
  }, [onClose]);

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setQ('');
    setMsgs((m) => [...m, { role: 'user', text: question }]);
    setBusy(true);
    const started = Date.now();
    const out = await ask(question, history, context, browserProvider);
    // An answer waits behind the pill for at least MIN_THINK_MS. An error shows at once.
    if (out.ok) await wait(Math.max(0, MIN_THINK_MS - (Date.now() - started)));
    if (out.ok) setHistory(out.history);
    const tags = out.ok ? askTags(out.history.slice(history.length) as { role: string; content: unknown }[]) : undefined;
    setMsgs((m) => [...m, { role: 'assistant', text: askReply(out), tools: out.tools, error: !out.ok, tags }]);
    setBusy(false);
  };

  const reset = () => {
    setMsgs(() => []);
    setHistory([]);
    setQ('');
    boxRef.current?.focus();
  };

  const lastAnswer = [...msgs].reverse().find((m) => m.role === 'assistant');
  const topics = hasLot ? [LOT_TOPIC, ...TOPICS] : TOPICS;

  return (
    <motion.section
      role="dialog"
      aria-label="ParcelIQ"
      initial={{ opacity: 0, y: 10, scale: 0.985 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 10, scale: 0.985 }}
      transition={{ duration: reduce ? 0 : 0.22, ease: [0.22, 1, 0.36, 1] }}
      className="absolute z-30 flex flex-col overflow-visible rounded-2xl bg-white shadow-[0_18px_50px_-18px_rgba(15,23,42,0.35),0_2px_6px_-2px_rgba(15,23,42,0.08)] ring-1 ring-slate-900/[0.06]"
      style={style}
    >
      {resize && <WidthHandle {...resize} />}
      {/* Header: name, what it does, Clear Chat and close. */}
      <header className="flex shrink-0 items-center gap-3 border-b border-stone-100 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 className="text-[15px] font-semibold leading-5 tracking-[-0.01em] text-slate-900">ParcelIQ</h2>
          <p className="truncate text-[12px] leading-4 text-slate-500">Zoning and buildable answers for PA lots</p>
        </div>
        {msgs.length > 0 && (
          <button type="button" onClick={reset} title="Clear the conversation" className="tap inline-flex h-8 items-center gap-1.5 rounded-lg px-2.5 text-[12px] font-semibold text-slate-600 ring-1 ring-stone-200 transition-colors hover:bg-stone-50 hover:text-slate-900">
            <Eraser className="h-3.5 w-3.5" /> Clear Chat
          </button>
        )}
        <button type="button" onClick={onClose} aria-label="Close ParcelIQ" title="Close (Esc)" className="tap grid h-8 w-8 place-items-center rounded-lg text-slate-400 transition-colors hover:bg-stone-100 hover:text-slate-800">
          <X className="h-4 w-4" />
        </button>
      </header>

      {/* Messages, or the welcome with suggested questions. */}
      <div ref={listRef} className="scroll-quiet min-h-0 flex-1 overflow-y-auto overscroll-contain bg-gradient-to-b from-stone-50/80 to-white px-4 py-4" aria-live="polite">
        {msgs.length === 0 ? (
          <div className="flex min-h-full flex-col justify-end gap-5 pb-1">
            <div className="flex flex-col items-start gap-1.5 px-1">
              <p className="text-[19px] font-semibold leading-7 tracking-[-0.02em] text-slate-900">Hi there!</p>
              <p className="text-[13px] leading-5 text-slate-500">{hasLot ? 'Ask what you can build on this lot, or pick a question.' : 'Pick a lot on the map, or ask about any town in PA.'}</p>
            </div>
            <div role="group" aria-label="Suggested questions" className="flex flex-col gap-1.5">
              {topics.map((t) => (
                <button key={t} type="button" onClick={() => void send(t)} className={cx('tap group flex min-h-10 items-center justify-between gap-3 rounded-xl px-3.5 py-2 text-left text-[13px] font-medium transition-all duration-150 active:scale-[0.99]', t === LOT_TOPIC ? 'bg-violet-600 text-white shadow-[0_6px_16px_-8px_rgba(109,40,217,0.7)] hover:bg-violet-700' : 'bg-white text-slate-700 ring-1 ring-stone-200 hover:text-violet-800 hover:ring-violet-300')}>
                  <span>{t}</span>
                  <ArrowUpRight className={cx('h-3.5 w-3.5 shrink-0 transition-transform group-hover:-translate-y-px group-hover:translate-x-px', t === LOT_TOPIC ? 'text-violet-200' : 'text-slate-300 group-hover:text-violet-500')} />
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-4">
            {msgs.map((m, i) =>
              m.role === 'user' ? (
                <motion.div key={i} initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="ml-10 self-end rounded-2xl rounded-br-md bg-gradient-to-br from-violet-600 to-indigo-600 px-3.5 py-2 text-[13.5px] leading-[1.45] text-white shadow-[0_4px_14px_-6px_rgba(79,70,229,0.55)]">
                  {m.text}
                </motion.div>
              ) : (
                <motion.div key={i} initial={reduce ? false : { opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} className="mr-6 flex items-start gap-2 self-start" data-answer>
                  <div aria-hidden className="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 text-white">
                    <Sparkles className="h-3 w-3" />
                  </div>
                  <div className="min-w-0">
                    <div className={cx('rounded-2xl rounded-tl-md px-3.5 py-2.5 text-[13.5px] leading-[1.5]', m.error ? 'bg-amber-50 text-amber-900 ring-1 ring-amber-200' : 'bg-white text-slate-700 shadow-[0_1px_2px_rgba(15,23,42,0.05)] ring-1 ring-stone-200/80')}>
                      <Answer text={m.text} />
                    </div>
                    {(m.tags?.unverified || (m.tags?.confidence.length ?? 0) > 0) && (
                      <div className="mt-1.5 flex flex-wrap gap-1" data-ask-tags>
                        {m.tags?.unverified && <span className="rounded-md bg-amber-50 px-1.5 py-0.5 text-[10.5px] font-semibold text-amber-800 ring-1 ring-amber-200">Unverified text search</span>}
                        {m.tags?.confidence.map((c) => (
                          <span key={c} className="rounded-md bg-stone-100 px-1.5 py-0.5 text-[10.5px] font-medium text-slate-500" data-confidence>
                            {c}
                          </span>
                        ))}
                      </div>
                    )}
                    {m === lastAnswer && !m.error && !busy && (
                      <button type="button" onClick={() => void send(EXPLAIN_MORE)} className="tap mt-2 inline-flex h-7 items-center gap-1 rounded-full bg-violet-50 px-3 text-[12px] font-semibold text-violet-700 ring-1 ring-violet-200/70 transition hover:bg-violet-100">
                        <ListPlus className="h-3.5 w-3.5" /> {EXPLAIN_MORE}
                      </button>
                    )}
                  </div>
                </motion.div>
              ),
            )}
            {busy && (
              <div className="flex items-center gap-2 self-start">
                <div aria-hidden className="grid h-6 w-6 shrink-0 place-items-center rounded-lg bg-gradient-to-br from-violet-500 to-indigo-600 text-white">
                  <Sparkles className="h-3 w-3" />
                </div>
                <ThinkingPill width={132} height={36} label="Thinking" />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Composer: one line that grows with the text, send inside it. */}
      <form
        className="shrink-0 border-t border-stone-100 px-3 pb-2.5 pt-2.5"
        onSubmit={(e) => {
          e.preventDefault();
          void send(q);
        }}
      >
        <div className="flex items-end gap-2 rounded-xl bg-stone-100/80 py-1.5 pl-3.5 pr-1.5 ring-1 ring-transparent transition focus-within:bg-white focus-within:ring-violet-300 focus-within:shadow-[0_0_0_4px_rgba(139,92,246,0.10)]">
          <textarea
            ref={boxRef}
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              const t = e.target;
              t.style.height = 'auto';
              t.style.height = `${Math.min(t.scrollHeight, 120)}px`;
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(q);
                e.currentTarget.style.height = 'auto';
              }
            }}
            rows={1}
            placeholder={hasLot ? 'Ask about this lot…' : 'Ask about ADUs in PA…'}
            aria-label="Ask ParcelIQ"
            className="max-h-[120px] min-h-[28px] flex-1 resize-none bg-transparent py-1 text-[13.5px] leading-5 text-slate-900 outline-none placeholder:text-slate-400"
          />
          <motion.button type="submit" disabled={!q.trim() || busy} whileTap={{ scale: 0.9 }} aria-label="Send" className="grid h-8 w-8 shrink-0 place-items-center rounded-lg bg-violet-600 text-white shadow-sm transition-colors hover:bg-violet-700 disabled:bg-stone-200 disabled:text-slate-400 disabled:shadow-none">
            <ArrowUp className="h-4 w-4" />
          </motion.button>
        </div>
        <p className="mt-1.5 text-center text-[10.5px] text-slate-400">Answers can be wrong. Not legal advice.</p>
      </form>
    </motion.section>
  );
}

/** The drag edge on the left of ParcelIQ when it stands alone: drag, or arrow keys, for the width. Double-click resets. */
function WidthHandle({ width, min, max, onWidth }: { width: number; min: number; max: number; onWidth: (w: number, save?: boolean) => void }) {
  const drag = useRef<{ x: number; w: number; next: number } | null>(null);
  const clamp = (w: number) => Math.round(Math.min(max, Math.max(min, w)));
  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label="Resize ParcelIQ"
      aria-valuenow={width}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      title="Drag to resize. Double-click for the default width."
      onPointerDown={(e) => {
        if (e.button !== 0) return;
        e.preventDefault();
        e.currentTarget.setPointerCapture(e.pointerId);
        drag.current = { x: e.clientX, w: width, next: width };
      }}
      onPointerMove={(e) => {
        const d = drag.current;
        if (!d) return;
        d.next = clamp(d.w + (d.x - e.clientX));
        onWidth(d.next, false);
      }}
      onPointerUp={() => {
        const d = drag.current;
        drag.current = null;
        if (d) onWidth(d.next);
      }}
      onPointerCancel={() => (drag.current = null)}
      onDoubleClick={() => onWidth(CHAT_W_DEFAULT)}
      onKeyDown={(e) => {
        if (e.key === 'ArrowLeft') onWidth(clamp(width + 24));
        else if (e.key === 'ArrowRight') onWidth(clamp(width - 24));
        else return;
        e.preventDefault();
      }}
      className="group absolute inset-y-4 -left-1.5 z-10 flex w-3 cursor-col-resize touch-none items-center justify-center outline-none"
    >
      <span aria-hidden className="h-10 w-1 rounded-full bg-stone-300 opacity-0 transition group-hover:h-14 group-hover:bg-violet-500 group-hover:opacity-100 group-focus-visible:bg-violet-500 group-focus-visible:opacity-100" />
    </div>
  );
}

/** Opens ParcelIQ. */
export const openParcelIQ = () => useChatOpen.getState().setOpen(true);
