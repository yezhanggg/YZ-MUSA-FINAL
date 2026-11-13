// "Ask about this site": a compact input that grows into a conversation. Tools run here in the browser.
import { useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowUp, Loader2, MessageCircle, X } from 'lucide-react';
import { cx } from '../lib/cx';
import { BED_LABEL } from '../lib/numbers';
import { SCENARIO_NAME, TYPE_TITLE } from '../lib/lot/words';
import { ask, splitLinks, type Turn } from '../agent/client';
import { browserProvider, selectLotById } from '../agent/browserProvider';
import { mapRef, useTool } from './store';
import { askTags, type AskTags } from './askTags';

const SUGGESTED = ["Could I build a 2 BR here?", "What's the biggest ADU that fits?", 'Is it legal here today?', 'Which lots near here fit a 1 BR without cutting trees?'];
const TOOL_TEXT: Record<string, string> = {
  get_site: 'Reading the site',
  test_adu: 'Testing the ADU',
  compare_sizes: 'Comparing sizes',
  get_rules: 'Checking the rules',
  find_lots: 'Searching nearby lots',
  set_map: 'Updating the map',
  get_lot_facts: 'Reading the lot',
  get_lot_rules: 'Checking the lot rules',
  test_unit_on_lot: 'Testing the unit',
  compare_scenarios: 'Comparing scenarios',
  lot_money: 'Working out the money',
  explain_limit: 'Finding the limit',
  get_place_answer: 'Looking up the town',
  search_zoning_text: 'Searching the zoning text',
};
const TEST_SUGGESTED = ['Does this unit fit here?', 'What limits it on this lot?', 'How do the three scenarios compare?', 'Does it pay off?'];

interface Msg {
  role: 'user' | 'assistant';
  text: string;
  tools?: string[];
  error?: boolean;
  /** What the tool results say about how sure the answer is (askTags). */
  tags?: AskTags;
}

function useContext() {
  const spot = useTool((s) => s.spot);
  const adu = useTool((s) => s.adu);
  const rule = useTool((s) => s.rule);
  const view = useTool((s) => s.view);
  const scenario = useTool((s) => s.scenario);
  const unit = useTool((s) => s.unit);
  const map = mapRef.current;
  const test = view === 'test';
  const lotId = spot?.record?.lot.id ?? spot?.parcel?.id ?? null;
  const where = spot ? (lotId ? `Lot ${lotId}` : (spot.tract.NAMELSAD ?? 'Tract')) : 'No lot selected';
  return {
    test,
    chips: test
      ? [where, `${TYPE_TITLE[unit.type]} · ${unit.width} x ${unit.depth} ft · ${unit.stories} ${unit.stories === 2 ? 'stories' : 'story'}`, SCENARIO_NAME[scenario]]
      : [where, `${BED_LABEL[adu.bed]} · ${adu.size.toLocaleString('en-US')} sq ft · ${adu.stories} ${adu.stories === 2 ? 'stories' : 'story'}`, rule === 'hb2186' ? 'State bill' : 'Today'],
    context: {
      selected: spot ? { lot_id: lotId, tract_geoid: spot.tract.GEOID, town_geoid: (spot.town.GEOID as string | undefined) ?? null, town: (spot.town.NAMELSAD as string | undefined) ?? null, label: spot.label } : null,
      adu: { bedrooms: adu.bed, size_sqft: adu.size, stories: adu.stories },
      rule,
      scenario: test ? scenario : null,
      unit: test ? { type: unit.type, width_ft: unit.width, depth_ft: unit.depth, stories: unit.stories, height_ft: unit.height, units: unit.units } : null,
      map: map ? { center: [map.getCenter().lng, map.getCenter().lat] as [number, number], zoom: map.getZoom() } : null,
    },
  };
}

/** `flat`: no box of its own, when it already sits in one (the right panel's chat box). */
export default function AskBox({ expanded: forceOpen, flat }: { expanded?: boolean; flat?: boolean }) {
  const [q, setQ] = useState('');
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [history, setHistory] = useState<Turn[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [open, setOpen] = useState(false);
  const { chips, context, test } = useContext();
  const input = useRef<HTMLInputElement>(null);
  const showConvo = forceOpen || open || msgs.length > 0;

  const send = async (text: string) => {
    const question = text.trim();
    if (!question || busy) return;
    setQ('');
    setOpen(true);
    setMsgs((m) => [...m, { role: 'user', text: question }]);
    setBusy('Thinking');
    const out = await ask(question, history, context, browserProvider, { onTool: (n) => setBusy(TOOL_TEXT[n] ?? 'Working') });
    setBusy(null);
    if (out.ok) setHistory(out.history);
    // The turns this answer added (its tool calls and results), for the tags under it.
    const tags = out.ok ? askTags(out.history.slice(history.length) as { role: string; content: unknown }[]) : undefined;
    setMsgs((m) => [...m, { role: 'assistant', text: out.text, tools: out.tools, error: !out.ok, tags }]);
  };

  return (
    <section aria-label="Ask about this site" className={cx(!flat && 'rounded-xl bg-stone-50 p-2.5 ring-1 ring-stone-200/80')}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void send(q);
        }}
        className="flex items-center gap-2 rounded-lg bg-white pl-2.5 pr-1 ring-1 ring-stone-300 focus-within:ring-violet-400 focus-within:shadow-[0_0_0_4px_rgba(124,58,237,0.12)]"
      >
        <MessageCircle className="h-4 w-4 shrink-0 text-violet-600" />
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} onFocus={() => setOpen(true)} placeholder="Ask about this site" aria-label="Ask about this site" className="h-10 min-w-0 flex-1 bg-transparent text-body text-slate-900 outline-none placeholder:text-slate-500" />
        <button type="submit" disabled={!q.trim() || !!busy} aria-label="Send" className="tap grid h-8 w-8 shrink-0 place-items-center rounded-md bg-violet-600 text-white transition hover:bg-violet-700 disabled:bg-stone-200 disabled:text-slate-400">
          {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <ArrowUp className="h-4 w-4" />}
        </button>
      </form>
      {/* What the assistant will read, shown once the box is in use. */}
      {showConvo && (
        <div className="mt-2 flex flex-wrap gap-1">
          {chips.map((c) => (
            <span key={c} className="max-w-full truncate rounded-full bg-white px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-stone-200">
              {c}
            </span>
          ))}
        </div>
      )}
      <AnimatePresence initial={false}>
        {showConvo && (
          <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
            <div className="mt-2 space-y-2">
              {msgs.length === 0 && (
                <div className="flex flex-wrap gap-1.5">
                  {(test ? TEST_SUGGESTED : SUGGESTED).map((s) => (
                    <button key={s} type="button" onClick={() => void send(s)} className="tap rounded-lg bg-white px-2.5 py-1.5 text-left text-caption font-medium text-slate-700 ring-1 ring-stone-200 transition hover:bg-violet-50 hover:text-violet-800 hover:ring-violet-200">
                      {s}
                    </button>
                  ))}
                </div>
              )}
              {msgs.map((m, i) => (
                <div key={i} className={cx('rounded-lg px-3 py-2 text-small leading-snug', m.role === 'user' ? 'ml-6 bg-violet-600 text-white' : m.error ? 'bg-amber-50 text-amber-900 ring-1 ring-amber-200' : 'bg-white text-slate-800 ring-1 ring-stone-200')}>
                  {m.role === 'assistant' ? <Answer text={m.text} /> : m.text}
                  {m.tags && (m.tags.unverified || m.tags.confidence.length > 0) && (
                    <div className="mt-1.5 flex flex-wrap gap-1" data-ask-tags>
                      {m.tags.unverified && (
                        <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-800 ring-1 ring-amber-200" title="Passages copied word for word from the public zoning text, found by a word search. Not a checked rule file.">
                          Unverified text search
                        </span>
                      )}
                      {m.tags.confidence.map((c) => (
                        <span key={c} className="rounded-full bg-stone-50 px-2 py-0.5 text-[11px] font-medium text-slate-600 ring-1 ring-stone-200" data-confidence>
                          {c}
                        </span>
                      ))}
                    </div>
                  )}
                  {m.tools && m.tools.length > 0 && <div className="mt-1 text-[11px] text-slate-400">From: {[...new Set(m.tools)].join(', ')}</div>}
                </div>
              ))}
              {busy && <div className="shimmer-text px-1 text-caption font-medium">{busy}…</div>}
              {msgs.length > 0 && !busy && !forceOpen && (
                <button type="button" onClick={() => (setMsgs([]), setHistory([]), setOpen(false))} className="inline-flex items-center gap-1 px-1 text-caption font-semibold text-slate-500 hover:text-slate-800">
                  <X className="h-3 w-3" /> Clear
                </button>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
}

/** An answer with lot links that select the lot on the map. */
function Answer({ text }: { text: string }) {
  return (
    <span className="whitespace-pre-line">
      {splitLinks(text).map((p, i) =>
        p.t === 'text' ? (
          <span key={i}>{p.v}</span>
        ) : (
          <button key={i} type="button" onClick={() => void selectLotById(p.id)} className="font-semibold text-violet-700 underline decoration-violet-300 underline-offset-2 hover:decoration-violet-700">
            {p.label}
          </button>
        ),
      )}
    </span>
  );
}
