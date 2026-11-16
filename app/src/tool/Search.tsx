// Address search. A typed address is looked up first in the lot address index of the six lot places
// (lib/lot/addressIndex, the same files the assistant's find_lot reads): a lot found there opens by its id, so the
// search never lands on the street or on the wrong house. Photon (komoot) runs alongside for everything else: free, no
// key, limited to the Pennsylvania bounding box. Photon gets 6 s; when it fails or is that slow, Enter asks
// OpenStreetMap's Nominatim once (one request per Enter, never per keystroke, as its usage policy asks).
import { useEffect, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { Loader2, MapPin, Search as SearchIcon, X } from 'lucide-react';
import { cx } from '../lib/cx';
import { PA_BBOX, type LngLat } from './geo';
import { clearSpot, openLot, testSpot } from './actions';
import { houseFirst, looksLikeAddress, lotHits, mergeHits, type PhotonFeature, type SearchHit } from './searchRank';
import { useTool } from './store';
import { addressIndexSource, type AddressIndexSource } from '../lib/lot/addressIndex';

type Hit = SearchHit;

/** The lot address index, read once and kept (5 to 40 KB per place, one small shard per street). */
let lotIndex: AddressIndexSource | null = null;

/** Lots in the lot places with the typed address. Only for a typed house number; never fails (no index: no rows). */
async function lotSearch(text: string): Promise<Hit[]> {
  if (!looksLikeAddress(text)) return [];
  lotIndex ??= addressIndexSource();
  return lotHits(await lotIndex.search(text, 3));
}

const within = <T,>(p: Promise<T>, ms: number, fallback: T) => Promise.race([p, new Promise<T>((res) => window.setTimeout(() => res(fallback), ms))]);

/** Nominatim, for Enter only when Photon is down: one request, Pennsylvania box, house-level details. */
async function nominatim(text: string, signal: AbortSignal): Promise<Hit[]> {
  const [w, s, e, n] = PA_BBOX;
  const url = `https://nominatim.openstreetmap.org/search?format=jsonv2&addressdetails=1&limit=5&countrycodes=us&bounded=1&viewbox=${w},${n},${e},${s}&q=${encodeURIComponent(text)}`;
  type Row = { lat: string; lon: string; name?: string; address?: { house_number?: string; road?: string; city?: string; town?: string; village?: string; county?: string; state?: string } };
  const rows = (await fetch(url, { signal }).then((r) => r.json())) as Row[];
  return rows
    .filter((r) => r.address?.state === 'Pennsylvania')
    .map((r) => {
      const a = r.address ?? {};
      const main = a.house_number && a.road ? `${a.house_number} ${a.road}` : (r.name || a.road || 'Place');
      return { coords: [Number(r.lon), Number(r.lat)] as LngLat, main, sub: [a.city ?? a.town ?? a.village, a.county].filter(Boolean).join(', ') };
    });
}

const PHOTON_MS = 6000;

async function photon(text: string, signal: AbortSignal): Promise<Hit[]> {
  const base = `https://photon.komoot.io/api/?q=${encodeURIComponent(text)}&bbox=${PA_BBOX.join(',')}&limit=6&lang=en`;
  const get = async (url: string) => ((await fetch(url, { signal }).then((r) => r.json())) as { features: PhotonFeature[] }).features.filter((f) => f.properties.state === 'Pennsylvania');
  // A typed house number also asks Photon's house layer (layer=house), in parallel with the usual search.
  const [houses, rest] = await Promise.all([looksLikeAddress(text) ? get(`${base}&layer=house`).catch(() => []) : Promise.resolve([]), get(base)]);
  return houseFirst(text, houses, rest)
    .slice(0, 6)
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
  // Photon failed or timed out on the last try: Enter then asks Nominatim.
  const down = useRef(false);
  // The text of the row just picked: the box shows it, and it must not search again and reopen the list.
  const picked = useRef<string | null>(null);
  // The text a search is running for: the typing debounce does not start a second one that would cancel it (Enter).
  const inflight = useRef<string | null>(null);

  const run = async (text: string, fallback = false) => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    inflight.current = text;
    setLoading(true);
    let slow = false;
    const timer = window.setTimeout(() => ((slow = true), c.abort()), PHOTON_MS);
    const lots = within(lotSearch(text).catch(() => [] as Hit[]), PHOTON_MS, [] as Hit[]);
    const show = (r: Hit[]) => {
      setHits(r);
      setActive(0);
      setOpen(picked.current === null);
    };
    // The geocoder's rows show as soon as they come; the lot index's rows join them when the index has answered.
    let geoShown: Hit[] | null = null;
    let ownNow: Hit[] = [];
    void lots.then((own) => {
      ownNow = own;
      if (own.length && geoShown && ctl.current === c) show(mergeHits(own, geoShown));
    });
    try {
      let geo: Hit[] = [];
      let failed: unknown = null;
      try {
        geo = fallback && down.current ? await nominatim(text, c.signal) : await photon(text, c.signal);
      } catch (e) {
        failed = e;
      }
      // A newer search started: this one says nothing.
      if (ctl.current !== c) return [];
      // Enter (fallback) and a failed geocoder wait for the lot index, so a lot it finds is never missed.
      const own = fallback || failed ? await lots : ownNow;
      if (ctl.current !== c) return [];
      // The geocoder failed and the lot index found nothing: the usual message.
      if (failed && !own.length) throw failed;
      if (failed) down.current = true;
      else if (!fallback) down.current = false;
      const r = mergeHits(own, geo);
      geoShown = geo;
      show(r);
      return r;
    } catch (e) {
      if (slow || (e as Error).name !== 'AbortError') {
        down.current = true;
        set({ msg: fallback ? 'Search is not working right now. Click the map instead.' : 'Search is slow right now. Press Enter to try again, or click the map.' });
      }
      return [];
    } finally {
      window.clearTimeout(timer);
      if (ctl.current === c) {
        setLoading(false);
        inflight.current = null;
      }
    }
  };

  useEffect(() => {
    const text = q.trim();
    // The box now shows the row just picked: no new search, no list.
    if (picked.current !== null && text === picked.current) return;
    if (text.length < 3) {
      ctl.current?.abort();
      setHits([]);
      setLoading(false);
      return;
    }
    const t = setTimeout(() => inflight.current !== text && void run(text), 350);
    return () => clearTimeout(t);
  }, [q]); // eslint-disable-line react-hooks/exhaustive-deps

  const pick = (h: Hit) => {
    picked.current = h.main;
    // A search still running would bring the list back: it is stopped and forgotten.
    ctl.current?.abort();
    ctl.current = null;
    setQ(h.main);
    setOpen(false);
    setHits([]);
    setLoading(false);
    set({ msg: null });
    // A lot from the address index opens by its id (its own tract), never by a geocoded point on the street.
    if (h.lot) void openLot(h.lot.id, h.lot.tract);
    else if (h.coords) void testSpot(h.coords, h.main);
  };

  const onKey = async (e: React.KeyboardEvent) => {
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      e.preventDefault();
      setOpen(true);
      setActive((a) => Math.max(0, Math.min(hits.length - 1, a + (e.key === 'ArrowDown' ? 1 : -1))));
    } else if (e.key === 'Enter') {
      e.preventDefault();
      let list = hits;
      if (!list.length && q.trim()) list = await run(q.trim(), true);
      if (list.length) pick(list[Math.min(active, list.length - 1)]);
      else if (!useTool.getState().msg) set({ msg: 'No match found in Pennsylvania.' });
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
            picked.current = null;
            setQ(e.target.value);
            setOpen(true);
            if (msg) set({ msg: null });
          }}
          onFocus={() => picked.current === null && setOpen(true)}
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
              picked.current = null;
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
