// "Pick an ADU": four sample units with small line drawings, plus "Custom" when the controls match none.
import { motion } from 'motion/react';
import { SAMPLES, footprint, sampleOf } from '../lib/adu';
import { cx } from '../lib/cx';
import { BED_LABEL } from '../lib/numbers';
import { SPRING_TAB } from '../components/primitives';
import { useTool } from './store';

const S = { fill: 'none', stroke: 'currentColor', strokeWidth: 1.6, strokeLinejoin: 'round' as const, strokeLinecap: 'round' as const };

/** Line drawings, one per sample: a ground line, the unit, a door and windows. */
function Drawing({ id }: { id: string }) {
  return (
    <svg viewBox="0 0 64 40" className="h-10 w-16" aria-hidden>
      <path d="M2 36h60" {...S} strokeOpacity={0.35} />
      {id === 'studio' && (
        <>
          <path d="M22 36V22l10-8 10 8v14z" {...S} />
          <rect x="29" y="27" width="6" height="9" rx="1" {...S} />
          <path d="M45 34c2-4 6-4 8 0" {...S} strokeOpacity={0.45} />
        </>
      )}
      {id === 'br1' && (
        <>
          <path d="M14 36V21l14-9 14 9v15z" {...S} />
          <rect x="18" y="25" width="6" height="5" rx="1" {...S} />
          <rect x="30" y="27" width="6" height="9" rx="1" {...S} />
          <path d="M46 34c2-5 8-5 10 0" {...S} strokeOpacity={0.45} />
        </>
      )}
      {id === 'br2' && (
        <>
          <path d="M8 36V22l12-8h22l12 8v14z" {...S} />
          <rect x="13" y="25" width="7" height="5" rx="1" {...S} />
          <rect x="24" y="25" width="7" height="5" rx="1" {...S} />
          <rect x="40" y="27" width="6" height="9" rx="1" {...S} />
        </>
      )}
      {id === 'garage' && (
        <>
          <path d="M18 36V16l14-9 14 9v20z" {...S} />
          <rect x="22" y="25" width="20" height="11" rx="1" {...S} />
          <path d="M22 29h20M22 32.5h20" {...S} strokeOpacity={0.45} />
          <rect x="25" y="15" width="6" height="5" rx="1" {...S} />
          <rect x="33" y="15" width="6" height="5" rx="1" {...S} />
        </>
      )}
      {id === 'custom' && (
        <>
          <path d="M16 36V22l16-10 16 10v14z" {...S} strokeDasharray="3 2.5" />
          <path d="M28 26h8M32 22v8" {...S} />
        </>
      )}
    </svg>
  );
}

function Card({ id, name, line, on, onClick }: { id: string; name: string; line: string; on: boolean; onClick?: () => void }) {
  return (
    <button type="button" onClick={onClick} aria-pressed={on} disabled={!onClick} className={cx('tap relative flex flex-col items-start rounded-xl p-2.5 text-left transition', on ? 'text-violet-800' : 'bg-white text-slate-700 ring-1 ring-stone-200 hover:ring-violet-300', !onClick && 'cursor-default')}>
      {on && <motion.span layoutId="adu-sample" className="absolute inset-0 rounded-xl bg-violet-50 ring-2 ring-violet-500" transition={SPRING_TAB} />}
      <span className="relative">
        <Drawing id={id} />
      </span>
      <span className="relative mt-1 text-small font-semibold leading-tight">{name}</span>
      <span className="relative text-[11px] leading-tight text-slate-500">{line}</span>
    </button>
  );
}

/** `bare`: without its own heading, inside a Fold that already says "Pick an ADU". */
export default function AduSamples({ bare }: { bare?: boolean }) {
  const adu = useTool((s) => s.adu);
  const setAdu = useTool((s) => s.setAdu);
  const current = sampleOf(adu);
  return (
    <section aria-label="Pick an ADU">
      {!bare && <h3 className="mb-2 text-caption font-semibold uppercase tracking-[0.12em] text-slate-500">Pick an ADU</h3>}
      <div className="grid grid-cols-2 gap-2">
        {SAMPLES.map((s) => (
          <Card key={s.id} id={s.id} name={s.name} line={`${s.adu.size} sq ft · ${s.adu.stories} ${s.adu.stories === 2 ? 'stories' : 'story'}${s.adu.stories === 2 ? ` (${footprint(s.adu)} footprint)` : ''}`} on={current?.id === s.id} onClick={() => setAdu(s.adu)} />
        ))}
        {!current && <Card id="custom" name="Custom" line={`${BED_LABEL[adu.bed]} · ${adu.size} sq ft · ${adu.stories} ${adu.stories === 2 ? 'stories' : 'story'}`} on />}
      </div>
    </section>
  );
}
