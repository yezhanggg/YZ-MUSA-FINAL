// The hero picture: an aerial tile of one lot. A scan line sweeps down and turns the photo into land cover (the
// U-Net step), the setback line draws in, then a 20 x 30 ft backyard home settles into the open ground (the fit test).
// Under reduced motion it shows the final frame.
import { useEffect, useMemo, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Check, ScanLine } from 'lucide-react';
import { EASE_OUT } from '../components/primitives';

type Cls = 'tree' | 'open' | 'building' | 'other';
const N = 24;
const C = 16; // px per cell
const SIZE = N * C;

const PHOTO: Record<Cls, string[]> = {
  tree: ['#3f5d34', '#48663a', '#4f6f3f', '#3a5530'],
  open: ['#9cab7f', '#a4b386', '#95a578', '#aab98c'],
  building: ['#8c8a8f', '#97959a', '#85838a', '#9a989c'],
  other: ['#b9b5ae', '#c2beb6', '#b2aea7', '#bdb9b2'],
};
export const CLASS_COLOR: Record<Cls, string> = { tree: '#16a34a', open: '#fde68a', building: '#475569', other: '#d6d3d1' };

/** A fixed little neighbourhood: one lot with a house, a driveway, two tree clumps, neighbours and a street. */
function classify(x: number, y: number): Cls {
  const d = (cx: number, cy: number) => Math.hypot(x - cx, y - cy);
  if (y >= 20) return 'other'; // sidewalk + street
  if (x <= 1 || x >= 22 || y <= 1) {
    // neighbours
    if (d(0, 8) < 3 || d(23, 14) < 3.2 || d(10, 0) < 2.6 || d(19, 0) < 2) return 'tree';
    if ((x <= 1 && y >= 13) || (x >= 22 && y <= 7)) return 'building';
    return 'open';
  }
  if (x >= 5 && x <= 12 && y >= 12 && y <= 17) return 'building'; // house
  if (x >= 14 && x <= 16 && y >= 13) return 'other'; // driveway
  if (d(4.5, 4.5) < 2.6 || d(18, 5) < 3.4 || d(20, 11) < 1.6) return 'tree';
  return 'open';
}

const LOT = { x: 2, y: 2, w: 20, h: 18 };
const ADU = { x: 8, y: 4, w: 6, h: 4 };

export default function LotScan() {
  const reduce = useReducedMotion();
  const cells = useMemo(() => {
    const out: { x: number; y: number; cls: Cls; photo: string }[] = [];
    for (let y = 0; y < N; y++) for (let x = 0; x < N; x++) {
      const cls = classify(x, y);
      const p = PHOTO[cls];
      out.push({ x, y, cls, photo: p[(x * 7 + y * 13 + ((x * y) % 5)) % p.length] });
    }
    return out;
  }, []);
  // 0 photo, 1 scanning, 2 classified, 3 setback, 4 ADU placed
  const [stage, setStage] = useState(reduce ? 4 : 0);
  useEffect(() => {
    if (reduce) return setStage(4);
    const t = [setTimeout(() => setStage(1), 700), setTimeout(() => setStage(2), 2700), setTimeout(() => setStage(3), 3000), setTimeout(() => setStage(4), 3900)];
    return () => t.forEach(clearTimeout);
  }, [reduce]);

  const scanning = stage === 1;
  const classified = stage >= 2;

  return (
    <div className="relative mx-auto w-full max-w-[520px]">
      {/* glow behind the card */}
      <div aria-hidden className="absolute -inset-6 rounded-[40px] bg-gradient-to-br from-violet-300/40 via-fuchsia-200/20 to-emerald-200/30 blur-2xl" />
      <motion.div initial={reduce ? false : { opacity: 0, y: 24, rotate: -1.5 }} animate={{ opacity: 1, y: 0, rotate: 0 }} transition={{ duration: 0.9, ease: EASE_OUT, delay: 0.15 }} className="relative overflow-hidden rounded-[28px] bg-white p-3 shadow-[0_30px_80px_-30px_rgba(76,29,149,0.45)] ring-1 ring-black/5">
        {/* card header */}
        <div className="flex items-center justify-between gap-2 px-1.5 pb-3 pt-1">
          <div className="min-w-0">
            <div className="truncate text-small font-semibold text-slate-900">Single-family lot · sample</div>
            <div className="text-caption text-slate-500">2022 aerial image · 0.6 m pixels</div>
          </div>
          <AnimatePresence mode="wait" initial={false}>
            {stage < 4 ? (
              <motion.span key="scan" initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }} className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-stone-100 px-2.5 py-1 text-caption font-semibold text-slate-600 ring-1 ring-stone-200">
                <ScanLine className="h-3.5 w-3.5" />
                <span className={stage > 0 ? 'shimmer-text' : ''}>{stage === 0 ? 'Aerial image' : stage === 1 ? 'U-Net land cover…' : 'Fit test…'}</span>
              </motion.span>
            ) : (
              <motion.span key="fits" initial={{ opacity: 0, scale: 0.8 }} animate={{ opacity: 1, scale: 1 }} transition={{ type: 'spring', stiffness: 500, damping: 24 }} className="inline-flex shrink-0 items-center gap-1.5 rounded-full bg-emerald-50 px-2.5 py-1 text-caption font-semibold text-emerald-700 ring-1 ring-emerald-200">
                <Check className="h-3.5 w-3.5" /> Fits · 600 sq ft
              </motion.span>
            )}
          </AnimatePresence>
        </div>

        <div className="relative overflow-hidden rounded-2xl">
          <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="block h-auto w-full" role="img" aria-label="An aerial tile of one lot. The model colours trees, open ground and buildings, then places a 20 by 30 foot backyard home in the open ground.">
            <defs>
              <clipPath id="scan-clip">
                <motion.rect x={0} y={0} width={SIZE} initial={false} animate={{ height: classified ? SIZE : scanning ? SIZE : 0 }} transition={{ duration: scanning ? 2 : 0, ease: 'linear' }} />
              </clipPath>
              <pattern id="adu-hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
                <rect width="6" height="6" fill="#7c3aed" />
                <rect width="2" height="6" fill="#8b5cf6" />
              </pattern>
            </defs>
            {/* photo layer */}
            <g>
              {cells.map((c) => (
                <rect key={`p${c.x}-${c.y}`} x={c.x * C} y={c.y * C} width={C + 0.5} height={C + 0.5} fill={c.photo} />
              ))}
            </g>
            {/* land cover layer, revealed by the scan */}
            <g clipPath="url(#scan-clip)">
              {cells.map((c) => (
                <rect key={`c${c.x}-${c.y}`} x={c.x * C} y={c.y * C} width={C + 0.5} height={C + 0.5} fill={CLASS_COLOR[c.cls]} opacity={0.92} />
              ))}
              {/* faint pixel grid */}
              <g stroke="#ffffff" strokeOpacity={0.25} strokeWidth={0.6}>
                {Array.from({ length: N + 1 }, (_, i) => (
                  <g key={i}>
                    <line x1={i * C} y1={0} x2={i * C} y2={SIZE} />
                    <line x1={0} y1={i * C} x2={SIZE} y2={i * C} />
                  </g>
                ))}
              </g>
            </g>
            {/* scan line */}
            {scanning && (
              <motion.g initial={{ y: 0 }} animate={{ y: SIZE }} transition={{ duration: 2, ease: 'linear' }}>
                <rect x={0} y={-28} width={SIZE} height={28} fill="url(#scan-glow)" />
                <rect x={0} y={-2} width={SIZE} height={2.5} fill="#a78bfa" />
              </motion.g>
            )}
            <linearGradient id="scan-glow" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0" stopColor="#a78bfa" stopOpacity="0" />
              <stop offset="1" stopColor="#a78bfa" stopOpacity="0.45" />
            </linearGradient>
            {/* lot line */}
            <rect x={LOT.x * C} y={LOT.y * C} width={LOT.w * C} height={LOT.h * C} fill="none" stroke="#fff" strokeWidth={2.5} rx={2} />
            {/* setback: 5 ft from lot lines */}
            {stage >= 3 && (
              <motion.rect x={(LOT.x + 1) * C} y={(LOT.y + 1) * C} width={(LOT.w - 2) * C} height={(LOT.h - 2) * C} fill="none" stroke="#6d28d9" strokeWidth={1.6} strokeDasharray="6 5" rx={2} initial={reduce ? false : { pathLength: 0, opacity: 0 }} animate={{ pathLength: 1, opacity: 0.9 }} transition={{ duration: 0.8, ease: 'easeInOut' }} />
            )}
            {/* the ADU */}
            {stage >= 4 && (
              <motion.g initial={reduce ? false : { opacity: 0, scale: 1.35, y: -14 }} animate={{ opacity: 1, scale: 1, y: 0 }} transition={{ type: 'spring', stiffness: 260, damping: 20 }} style={{ transformOrigin: `${(ADU.x + ADU.w / 2) * C}px ${(ADU.y + ADU.h / 2) * C}px` }}>
                <rect x={ADU.x * C} y={ADU.y * C} width={ADU.w * C} height={ADU.h * C} rx={3} fill="url(#adu-hatch)" stroke="#fff" strokeWidth={2.5} />
                <text x={(ADU.x + ADU.w / 2) * C} y={(ADU.y + ADU.h / 2) * C + 4} textAnchor="middle" fontSize={12} fontWeight={700} fill="#fff" fontFamily="DM Sans, sans-serif">
                  20 × 30 ft
                </text>
              </motion.g>
            )}
          </svg>
        </div>

        {/* legend */}
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 px-1.5 pt-3 text-caption text-slate-600">
          {(['building', 'tree', 'open', 'other'] as Cls[]).map((k) => (
            <span key={k} className="inline-flex items-center gap-1.5">
              <span className="h-2.5 w-2.5 rounded-[3px] ring-1 ring-black/10" style={{ background: CLASS_COLOR[k] }} />
              {k === 'open' ? 'Open ground' : k === 'other' ? 'Paving' : k[0].toUpperCase() + k.slice(1)}
            </span>
          ))}
          <span className="inline-flex items-center gap-1.5">
            <span className="h-2.5 w-2.5 rounded-[3px] bg-violet-600" /> ADU
          </span>
        </div>
      </motion.div>

      {/* floating chips */}
      <Chip show={stage >= 2} className="-left-4 top-24 max-sm:-left-1" delay={0}>
        <span className="text-caption text-slate-500">U-Net mean IoU</span>
        <span className="font-display text-lead font-bold text-slate-900">0.65</span>
      </Chip>
      <Chip show={stage >= 4} className="-right-5 bottom-28 max-sm:-right-1" delay={0.25}>
        <span className="text-caption text-slate-500">Break-even rent</span>
        <span className="font-display text-lead font-bold text-emerald-700">$1,562 / mo</span>
      </Chip>
      <Chip show={stage >= 4} className="-right-3 top-14 max-sm:right-1" delay={0.45}>
        <span className="text-caption text-slate-500">HB 2186</span>
        <span className="font-display text-lead font-bold text-violet-700">Allowed</span>
      </Chip>
    </div>
  );
}

function Chip({ show, className, children, delay }: { show: boolean; className: string; children: React.ReactNode; delay: number }) {
  return (
    <AnimatePresence>
      {show && (
        <motion.div initial={{ opacity: 0, y: 10, scale: 0.92 }} animate={{ opacity: 1, y: 0, scale: 1 }} transition={{ type: 'spring', stiffness: 380, damping: 26, delay }} className={`absolute z-10 flex flex-col rounded-2xl bg-white/95 px-3.5 py-2 shadow-[0_14px_40px_-16px_rgba(15,23,42,0.4)] ring-1 ring-black/5 backdrop-blur ${className}`}>
          {children}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
