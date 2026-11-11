// Address search with Photon (komoot): free, no key, limited to the Pennsylvania bounding box.
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Loader2, MapPin, Search as SearchIcon, X } from 'lucide-react';
import { cx } from '../lib/cx';
import { PA_BBOX, type LngLat } from './geo';
import { clearSpot, testSpot } from './actions';
import { useTool } from './store';

interface Hit {
  coords: LngLat;
  main: string;
  sub: string;
}

interface PhotonFeature {
  geometry: { coordinates: LngLat };
  properties: { state?: string; housenumber?: string; street?: string; name?: string; city?: string; district?: string; county?: string };
}

async function photon(text: string, signal: AbortSignal): Promise<Hit[]> {
  const url = `https://photon.komoot.io/api/?q=${encodeURIComponent(text)}&bbox=${PA_BBOX.join(',')}&limit=6&lang=en`;
  const data = (await fetch(url, { signal }).then((r) => r.json())) as { features: PhotonFeature[] };
  return data.features
    .filter((f) => f.properties.state === 'Pennsylvania')
    .map((f) => {
      const p = f.properties;
      const main = p.housenumber ? `${p.housenumber} ${p.street ?? ''}`.trim() : (p.name ?? p.street ?? 'Place');
      return { coords: f.geometry.coordinates, main, sub: [p.city ?? p.district, p.county].filter(Boolean).join(', ') };
    });
}

export default function Search() {
  const [q, setQ] = useState('');
  const [hits, setHits] = useState<Hit[]>([]);
  const [active, setActive] = useState(0);
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const msg = useTool((s) => s.msg);
  const ready = useTool((s) => s.status === 'ready');
  const spot = useTool((s) => s.spot);
  const set = useTool((s) => s.set);
  const ctl = useRef<AbortController | null>(null);

  const run = async (text: string) => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    setLoading(true);
    try {
      const r = await photon(text, c.signal);
      if (c.signal.aborted) return r;
      setHits(r);
      setActive(0);
      setOpen(true);
      return r;
    } catch (e) {
      if ((e as Error).name !== 'AbortError') set({ msg: 'Search is not working right now. Click the map instead.' });
      return [];
    } finally {
      if (ctl.current === c) setLoading(false);
    }
  };

  useEffect(() => {
    const text = q.trim();
    if (text.length < 3) {
      ctl.current?.abort();
      setHits([]);
      setLoading(false);
      return;
    }
    const t = setTimeout(() => void run(text), 350);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (h: Hit) => {
    setQ(h.main);
    setOpen(false);
    setHits([]);
    void testSpot(h.coords, h.main);
  };

  const onKey = async (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.max(0, Math.min(hits.length - 1, a + (e.key === 'ArrowDown' ? 1 : -1))));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      let list = hits;
      if (!list.length && q.trim()) list = await run(q.trim());
      if (list.length) pick(list[Math.min(active, list.length - 1)]);
      else set({ msg: 'No match found in Pennsylvania.' });
    } else if (e.key === 'Escape') setOpen(false);
  };

  const showList = open && hits.length > 0;

  return (
    <div className="relative">
      <div className={cx('flex h-11 items-center gap-2 rounded-xl bg-white pl-3 pr-1.5 ring-1 transition-shadow', showList ? 'shadow-[0_0_0_4px_rgba(124,58,237,0.12)] ring-violet-400' : 'ring-stone-300 hover:ring-stone-400 focus-within:shadow-[0_0_0_4px_rgba(124,58,237,0.12)] focus-within:ring-violet-400')}>
        {loading ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-violet-600" /> : <SearchIcon className="h-4 w-4 shrink-0 text-slate-500" />}
        <input
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setOpen(true);
            if (msg) set({ msg: null });
          }}
          onFocus={() => setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKey}
          disabled={!ready}
          type="search"
          role="combobox"
          aria-expanded={showList}
          aria-autocomplete="list"
          aria-label="Search an address in Pennsylvania"
          placeholder={ready ? 'Search an address in PA' : 'Loading map data…'}
          autoComplete="off"
          className="min-w-0 flex-1 bg-transparent text-body text-slate-900 outline-none placeholder:text-slate-500 disabled:cursor-wait [&::-webkit-search-cancel-button]:hidden"
        />
        {(q || spot) && (
          <button
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              setQ('');
              setHits([]);
              set({ msg: null });
              clearSpot();
            }}
            className="tap grid h-8 w-8 shrink-0 place-items-center rounded-lg text-slate-500 hover:bg-stone-100 hover:text-slate-900"
            aria-label="Clear search and pin"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
      <AnimatePresence>
        {showList && (
          <motion.ul role="listbox" initial={{ opacity: 0, y: -4, scale: 0.98 }} animate={{ opacity: 1, y: 0, scale: 1 }} exit={{ opacity: 0, y: -4 }} transition={{ duration: 0.14 }} style={{ transformOrigin: 'top center' }} className="scroll-quiet absolute inset-x-0 z-50 mt-1.5 max-h-80 overflow-auto rounded-xl bg-white p-1 shadow-2xl ring-1 ring-black/5">
            {hits.map((h, i) => (
              <li key={`${h.main}-${i}`}>
                <button role="option" aria-selected={i === active} onMouseDown={(e) => e.preventDefault()} onClick={() => pick(h)} onMouseEnter={() => setActive(i)} className={cx('flex w-full items-center gap-2.5 rounded-lg px-2.5 py-2 text-left', i === active && 'bg-violet-50')}>
                  <MapPin className={cx('h-4 w-4 shrink-0', i === active ? 'text-violet-600' : 'text-slate-400')} />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-small font-medium text-slate-900">{h.main}</span>
                    {h.sub && <span className="block truncate text-caption text-slate-500">{h.sub}</span>}
                  </span>
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
      <AnimatePresence>
        {msg && (
          <motion.p role="status" initial={{ opacity: 0, height: 0 }} animate={{ opacity: 1, height: 'auto' }} exit={{ opacity: 0, height: 0 }} className="overflow-hidden text-small text-rose-700">
            <span className="block pt-2">{msg}</span>
          </motion.p>
        )}
      </AnimatePresence>
    </div>
  );
}
