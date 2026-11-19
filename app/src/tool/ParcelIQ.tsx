// ParcelIQ: the chat, opened from the map's ParcelIQ button. On desktop and laptop it fills the map area on its own,
// or splits it with the Details panel (ToolPage, with the drag bar between them). Same Ask backend and browser tools
// as AskBox. An answer waits at least MIN_THINK_MS behind the thinking pill, so a fast reply does not flash.
import { useEffect, useRef, useState, type CSSProperties } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowUp, MessageCircleDashed, RefreshCw, X } from 'lucide-react';
import { PANEL } from '../components/Panel';
import { cx } from '../lib/cx';
import { ask, type Turn } from '../agent/client';
import { browserProvider } from '../agent/browserProvider';
import { askReply, askTags, type AskTags } from './askTags';
import { Answer, useAskContext } from './AskBox';
import { ThinkingPill } from './ThinkingPill';
import { useChatOpen } from './layout';
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

export default function ParcelIQ({ style, onClose }: { style?: CSSProperties; onClose: () => void }) {
  const [msgs, setMsgsState] = useState<Msg[]>(memory.msgs);
  const [history, setHistoryState] = useState<Turn[]>(memory.history);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState('');
  const [spins, setSpins] = useState(0);
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
    setSpins((n) => n + 1);
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
      initial={{ opacity: 0, y: 12, scale: 0.99 }}
      animate={{ opacity: 1, y: 0, scale: 1 }}
      exit={{ opacity: 0, y: 12, scale: 0.99 }}
      transition={{ duration: reduce ? 0 : 0.22, ease: [0.22, 1, 0.36, 1] }}
      className={cx(PANEL, 'absolute z-30')}
      style={style}
    >
      {/* Header */}
      <div className="flex shrink-0 items-start justify-between gap-4 border-b border-stone-200 px-5 pb-4 pt-5">
        <div className="min-w-0">
          <h2 className="text-[16px] font-semibold leading-6 text-slate-900">ParcelIQ</h2>
          <p className="mt-0.5 text-small leading-5 text-slate-500">Parcel intelligence: zoning, limits and what you can build on any PA lot</p>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <motion.button type="button" onClick={reset} whileTap={{ scale: 0.9 }} aria-label="Start a new conversation" title="Start a new conversation" className="tap grid h-[30px] w-[30px] place-items-center rounded-[18px] bg-white text-slate-500 ring-1 ring-stone-200 transition-colors hover:text-slate-900">
            <motion.span animate={{ rotate: spins * 360 }} transition={{ type: 'spring', bounce: 0.2, duration: reduce ? 0 : 0.7 }} className="flex">
              <RefreshCw className="h-4 w-4" />
            </motion.span>
          </motion.button>
          <button type="button" onClick={onClose} aria-label="Close ParcelIQ" title="Close (Esc)" className="tap grid h-[30px] w-[30px] place-items-center rounded-[18px] bg-white text-slate-500 ring-1 ring-stone-200 transition-colors hover:text-slate-900">
            <X className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Messages, or the empty state with topics */}
      <div ref={listRef} className="scroll-quiet min-h-0 flex-1 overflow-y-auto overscroll-contain px-5 py-5" aria-live="polite">
        {msgs.length === 0 ? (
          <div className="mx-auto flex h-full max-w-xl flex-col items-center justify-center py-6 text-center">
            <motion.div animate={reduce ? undefined : { y: [0, -3, 0] }} transition={{ duration: 3, repeat: Infinity, ease: 'easeInOut' }} className="grid h-10 w-10 place-items-center rounded-[14px] bg-violet-50 ring-1 ring-violet-100">
              <MessageCircleDashed className="h-5 w-5 text-violet-700" />
            </motion.div>
            <p className="mt-4 text-[18px] font-semibold leading-7 tracking-[-0.45px] text-slate-900">Hi there!</p>
            <p className="mt-1.5 max-w-[300px] text-small leading-[22px] text-slate-500">Ask whether an ADU fits a lot, or pick a topic below.</p>
            <div role="group" aria-label="Suggested questions" className="mt-6 flex max-w-lg flex-wrap items-center justify-center gap-2">
              {topics.map((t) => (
                <button key={t} type="button" onClick={() => void send(t)} className={cx('tap h-8 rounded-full px-4 text-small transition-all duration-150 active:scale-[0.99]', t === LOT_TOPIC ? 'bg-violet-600 font-semibold text-white hover:bg-violet-700' : 'bg-stone-100 text-slate-800 hover:bg-stone-200')}>
                  {t}
                </button>
              ))}
            </div>
          </div>
        ) : (
          <div className="mx-auto flex max-w-2xl flex-col gap-3">
            {msgs.map((m, i) =>
              m.role === 'user' ? (
                <div key={i} className="ml-12 self-end rounded-[18px] rounded-br-md bg-violet-600 px-4 py-2.5 text-body leading-snug text-white">
                  {m.text}
                </div>
              ) : (
                <div key={i} className="mr-12 self-start" data-answer>
                  <div className="mb-1 pl-1 text-[11px] font-semibold uppercase tracking-wide text-violet-700">ParcelIQ</div>
                  <div className={cx('rounded-[18px] rounded-bl-md px-4 py-2.5 text-body leading-snug', m.error ? 'bg-amber-50 text-amber-900 ring-1 ring-amber-200' : 'bg-stone-100 text-slate-800')}>
                    <Answer text={m.text} />
                  </div>
                  {(m.tags?.unverified || (m.tags?.confidence.length ?? 0) > 0 || (m.tools?.length ?? 0) > 0) && (
                    <div className="mt-1.5 flex flex-wrap gap-1 pl-1" data-ask-tags>
                      {m.tags?.unverified && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 ring-1 ring-amber-200">Unverified text search</span>}
                      {m.tags?.confidence.map((c) => (
                        <span key={c} className="rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-stone-200" data-confidence>
                          {c}
                        </span>
                      ))}
                    </div>
                  )}
                  {m === lastAnswer && !m.error && !busy && (
                    <button type="button" onClick={() => void send(EXPLAIN_MORE)} className="tap mt-2 h-8 rounded-full bg-white px-4 text-small font-semibold text-violet-700 ring-1 ring-violet-200 transition hover:bg-violet-50">
                      {EXPLAIN_MORE}
                    </button>
                  )}
                </div>
              ),
            )}
            {busy && (
              <div className="self-start">
                <ThinkingPill width={160} height={44} label="Thinking" />
              </div>
            )}
          </div>
        )}
      </div>

      {/* Composer, always at the bottom */}
      <form
        className="shrink-0 px-5 pb-5"
        onSubmit={(e) => {
          e.preventDefault();
          void send(q);
        }}
      >
        <div className="mx-auto max-w-2xl rounded-[18px] bg-stone-200/50 p-3 transition-colors focus-within:bg-stone-200/80">
          <textarea
            ref={boxRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                void send(q);
              }
            }}
            rows={2}
            placeholder={hasLot ? 'Ask about this lot, or anything about ADUs in PA' : 'Ask anything about ADUs in PA'}
            aria-label="Ask ParcelIQ"
            className="max-h-40 w-full resize-none bg-transparent text-body leading-5 text-slate-900 outline-none placeholder:text-slate-500"
          />
          <div className="mt-2 flex items-center justify-end">
            <motion.button type="submit" disabled={!q.trim() || busy} whileHover={{ scale: 1.08 }} whileTap={{ scale: 0.88 }} aria-label="Send" className="group grid h-[30px] w-[30px] place-items-center rounded-[18px] bg-slate-950 text-white disabled:bg-stone-300 disabled:text-white">
              <ArrowUp className="h-4 w-4 transition-transform duration-200 group-hover:-translate-y-px" />
            </motion.button>
          </div>
        </div>
      </form>
    </motion.section>
  );
}

/** Opens ParcelIQ. */
export const openParcelIQ = () => useChatOpen.getState().setOpen(true);
