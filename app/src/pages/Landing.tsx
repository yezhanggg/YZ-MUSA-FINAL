import { useState, type ReactNode } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { ArrowRight, Building2, Coins, HardHat, Landmark, MapPin, Search, Sprout, TreePine } from 'lucide-react';
import LotScan from './LotScan';
import { EASE_OUT, Eyebrow, LinkButton, NumberTicker, Reveal, Segmented, SpotlightCard, Tag, WordReveal } from '../components/primitives';
import { cx } from '../lib/cx';

export default function Landing() {
  return (
    <div className="overflow-x-clip">
      <Hero />
      <StatStrip />
      <HowItWorks />
      <Audiences />
      <ClosingCta />
    </div>
  );
}

// ------------------------------------------------------------------ hero
function Hero() {
  const reduce = useReducedMotion();
  const fade = (d: number) => ({ initial: reduce ? false : { opacity: 0, y: 14 }, animate: { opacity: 1, y: 0 }, transition: { duration: 0.7, ease: EASE_OUT, delay: d } }) as const;
  return (
    <section className="relative isolate">
      <div aria-hidden className="paper-dots absolute inset-0 -z-10 [mask-image:radial-gradient(ellipse_at_top,black_30%,transparent_75%)]" />
      <div aria-hidden className="hero-aurora absolute -inset-x-20 -top-40 -z-10 h-[720px] blur-3xl" />
      <div className="mx-auto grid max-w-7xl items-center gap-14 px-4 pb-16 pt-12 sm:px-6 md:pt-20 lg:grid-cols-[1.05fr_1fr] lg:gap-10 lg:pb-24">
        <div>
          <motion.a href="#/research/5500/results" {...fade(0)} className="group inline-flex items-center gap-2 rounded-full bg-white/80 py-1 pl-1 pr-3 text-small font-medium text-slate-700 shadow-sm ring-1 ring-stone-200 backdrop-blur hover:ring-violet-300">
            <span className="rounded-full bg-violet-600 px-2 py-0.5 text-caption font-semibold text-white">HB 2186</span>
            One backyard home on every lot. What would it add?
            <ArrowRight className="h-3.5 w-3.5 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-violet-600" />
          </motion.a>
          <h1 className="mt-6 font-display text-[40px] font-bold leading-[1.04] tracking-tight text-slate-900 sm:text-[56px] lg:text-[64px]">
            <WordReveal text="Find the backyards where a second home fits, and pays." accent={['fits', 'pays']} delay={0.1} />
          </h1>
          <motion.p {...fade(0.55)} className="mt-6 max-w-xl text-lead leading-relaxed text-slate-600 sm:text-[18px]">
            Search any Pennsylvania address. See if a backyard home (ADU) is allowed, whether it fits on the lot from 2022 aerial images, and whether the rent covers the cost to build.
          </motion.p>
          <motion.div {...fade(0.7)} className="mt-8 flex flex-wrap gap-3">
            <LinkButton href="#/tool" size="lg">
              <Search className="h-4.5 w-4.5" /> Test an address
              <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </LinkButton>
            <LinkButton href="#how" variant="secondary" size="lg" onClick={(e) => { e.preventDefault(); document.getElementById('how')?.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth' }); }}>
              How it works
            </LinkButton>
          </motion.div>
          <motion.div {...fade(0.85)} className="mt-8 flex flex-wrap items-center gap-x-5 gap-y-2 text-small text-slate-500">
            <span className="inline-flex items-center gap-1.5"><MapPin className="h-4 w-4 text-violet-500" /> 3,445 tracts · 2,572 towns</span>
            <span className="inline-flex items-center gap-1.5"><Sprout className="h-4 w-4 text-emerald-500" /> 84,000 lots checked</span>
            <span className="inline-flex items-center gap-1.5"><Landmark className="h-4 w-4 text-amber-500" /> Free, no sign-up</span>
          </motion.div>
        </div>
        <LotScan />
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ stat strip
function StatStrip() {
  const stats: { label: string; value: ReactNode; sub: ReactNode }[] = [
    { label: 'Lots with room', value: <NumberTicker value={2.55} decimals={2} suffix="M" />, sub: 'single-family lots fit a 600 sq ft ADU' },
    { label: 'ADUs by 2031', value: <><span className="text-[0.6em] align-[0.28em] text-slate-400">~</span><NumberTicker value={16900} from={900} duration={2.2} /></>, sub: <>under HB 2186, vs <b className="font-semibold text-slate-700">~900</b> under today's rules</> },
    { label: 'Pays off', value: <NumberTicker value={20} suffix="%" />, sub: 'of tracts, at $250 / sq ft and 6.53% rates' },
    { label: 'Model accuracy', value: <><NumberTicker value={0.65} decimals={2} /><span className="ml-2 text-[0.5em] font-semibold text-slate-400">vs 0.36</span></>, sub: 'U-Net mean IoU vs Random Forest' },
  ];
  return (
    <section className="relative">
      <div className="mx-auto max-w-7xl px-4 sm:px-6">
        <Reveal>
          <dl className="grid grid-cols-2 overflow-hidden rounded-3xl bg-white shadow-[0_20px_60px_-36px_rgba(15,23,42,0.35)] ring-1 ring-stone-200/80 lg:grid-cols-4">
            {stats.map((s, i) => (
              <div key={s.label} className={cx('relative p-5 sm:p-7', i % 2 === 1 && 'border-l border-stone-200/80', i >= 2 && 'border-t border-stone-200/80 lg:border-t-0', i === 2 && 'lg:border-l')}>
                <dt className="flex items-center justify-between text-caption font-semibold uppercase tracking-[0.14em] text-slate-500">
                  {s.label}
                  <span className="font-mono text-[11px] font-normal tracking-normal text-slate-300">{String(i + 1).padStart(2, '0')}</span>
                </dt>
                <dd className="mt-3 font-display text-[34px] font-bold leading-none tracking-tight text-slate-900 sm:text-[44px]">{s.value}</dd>
                <dd className="mt-2.5 text-small leading-snug text-slate-600">{s.sub}</dd>
              </div>
            ))}
          </dl>
        </Reveal>
      </div>
    </section>
  );
}

// ------------------------------------------------------------------ how it works (bento)
function SectionHead({ eyebrow, title, sub, id }: { eyebrow: string; title: string; sub: string; id?: string }) {
  return (
    <Reveal className="mx-auto max-w-2xl text-center">
      <Eyebrow>{eyebrow}</Eyebrow>
      <h2 id={id} className="mt-3 scroll-mt-24 font-display text-[32px] font-bold leading-tight tracking-tight text-slate-900 sm:text-[42px]">{title}</h2>
      <p className="mt-4 text-lead text-slate-600">{sub}</p>
    </Reveal>
  );
}

function HowItWorks() {
  return (
    <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6 sm:py-32">
      <SectionHead id="how" eyebrow="How it works" title="Three questions, one answer" sub="Every spot in Pennsylvania gets the same three checks. Each one comes from a full research write-up you can read." />
      <div className="mt-14 grid gap-4 md:grid-cols-6">
        <Reveal className="md:col-span-3" delay={0}>
          <StepCard n="01" icon={<Coins className="h-4 w-4" />} tag="MUSA 5500" title="Demand and payoff" body="Jobs, people, and rent since 2010, before and after 2019. Then a simple test: does the local rent cover the monthly cost of building a 600 sq ft unit?" href="#/research/5500/results">
            <PayoffBar />
          </StepCard>
        </Reveal>
        <Reveal className="md:col-span-3" delay={0.08}>
          <StepCard n="02" icon={<TreePine className="h-4 w-4" />} tag="MUSA 6950" title="Room on the lot" body="A U-Net reads 2022 aerial images pixel by pixel: buildings, trees, open ground. A 20 x 30 ft spot has to fit behind the setbacks, with or without cutting trees." href="#/research/6950/results">
            <IouBars />
          </StepCard>
        </Reveal>
        <Reveal className="md:col-span-6" delay={0.12}>
          <RulesCard />
        </Reveal>
      </div>
    </section>
  );
}

function StepCard({ n, icon, tag, title, body, href, children }: { n: string; icon: ReactNode; tag: string; title: string; body: string; href: string; children: ReactNode }) {
  return (
    <SpotlightCard className="h-full">
      <div className="flex h-full flex-col p-6 sm:p-8">
        <div className="flex items-center justify-between">
          <span className="grid h-9 w-9 place-items-center rounded-xl bg-violet-50 text-violet-700 ring-1 ring-violet-200">{icon}</span>
          <span className="flex items-center gap-2">
            <Tag>{tag}</Tag>
            <span className="font-mono text-caption text-slate-300">{n}</span>
          </span>
        </div>
        <h3 className="mt-5 font-display text-[24px] font-bold tracking-tight text-slate-900">{title}</h3>
        <p className="mt-2 text-body leading-relaxed text-slate-600">{body}</p>
        <div className="mt-6 flex-1">{children}</div>
        <a href={href} className="mt-6 inline-flex items-center gap-1 text-small font-semibold text-violet-700 hover:text-violet-900">
          Read the results <ArrowRight className="h-3.5 w-3.5" />
        </a>
      </div>
    </SpotlightCard>
  );
}

/** Share of tracts where an ADU pays: yes / maybe / no (MUSA 5500 results). */
function PayoffBar() {
  const parts = [
    { k: 'Pays', v: 20, c: '#10b981' },
    { k: 'Close', v: 36, c: '#fbbf24' },
    { k: 'Does not', v: 44, c: '#e7e5e4' },
  ];
  return (
    <div className="rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-200/70">
      <div className="flex items-baseline justify-between text-caption text-slate-500">
        <span>3,261 tracts with rent data</span>
        <span>Break-even rent $1,562 / mo</span>
      </div>
      <div className="mt-3 flex h-9 gap-1 overflow-hidden rounded-xl">
        {parts.map((p, i) => (
          <motion.div key={p.k} className="flex items-center justify-center overflow-hidden rounded-lg text-small font-semibold" style={{ background: p.c, color: i === 2 ? '#475569' : '#fff' }} initial={{ width: '0%' }} whileInView={{ width: `${p.v}%` }} viewport={{ once: true }} transition={{ type: 'spring', stiffness: 90, damping: 18, delay: 0.15 + i * 0.12 }}>
            {p.v}%
          </motion.div>
        ))}
      </div>
      <div className="mt-2 flex gap-4 text-caption text-slate-600">
        {parts.map((p) => (
          <span key={p.k} className="inline-flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full ring-1 ring-black/10" style={{ background: p.c }} /> {p.k}
          </span>
        ))}
      </div>
    </div>
  );
}

/** IoU by class on held-out counties, Random Forest vs U-Net (MUSA 6950 results). */
function IouBars() {
  const rows = [
    { k: 'Open ground', rf: 0.485, un: 0.775 },
    { k: 'Tree', rf: 0.368, un: 0.672 },
    { k: 'Building', rf: 0.267, un: 0.543 },
  ];
  return (
    <div className="rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-200/70">
      <div className="flex items-center justify-between text-caption text-slate-500">
        <span>IoU on held-out counties</span>
        <span className="flex gap-3">
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-stone-300" />Random Forest</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-full bg-violet-600" />U-Net</span>
        </span>
      </div>
      <div className="mt-3 space-y-2.5">
        {rows.map((r, i) => (
          <div key={r.k} className="grid grid-cols-[84px_1fr] items-center gap-3 text-small">
            <span className="text-slate-700">{r.k}</span>
            <div className="space-y-1">
              {[{ v: r.rf, c: 'bg-stone-300' }, { v: r.un, c: 'bg-violet-600' }].map((b, j) => (
                <div key={j} className="flex items-center gap-2">
                  <div className="h-2 flex-1 overflow-hidden rounded-full bg-white ring-1 ring-stone-200/70">
                    <motion.div className={cx('h-full rounded-full', b.c)} initial={{ width: 0 }} whileInView={{ width: `${b.v * 100}%` }} viewport={{ once: true }} transition={{ type: 'spring', stiffness: 90, damping: 18, delay: 0.1 + i * 0.1 + j * 0.05 }} />
                  </div>
                  <span className={cx('w-9 text-right text-caption tnum', j ? 'font-semibold text-slate-900' : 'text-slate-500')}>{b.v.toFixed(2)}</span>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

/** Today vs HB 2186: the visitor flips the rule and the forecast moves. */
function RulesCard() {
  const [rule, setRule] = useState<'current' | 'hb2186'>('hb2186');
  const hb = rule === 'hb2186';
  const towns = [
    { name: 'Philadelphia', cur: 20, hb: 401 },
    { name: 'Pittsburgh', cur: 12, hb: 234 },
    { name: 'Lower Merion Twp', cur: 7, hb: 137 },
    { name: 'Haverford Twp', cur: 6, hb: 126 },
    { name: 'Abington Twp', cur: 6, hb: 121 },
  ];
  return (
    <SpotlightCard>
      <div className="grid gap-8 p-6 sm:p-8 lg:grid-cols-[1fr_1.1fr] lg:gap-12">
        <div className="flex flex-col">
          <div className="flex items-center justify-between">
            <span className="grid h-9 w-9 place-items-center rounded-xl bg-violet-50 text-violet-700 ring-1 ring-violet-200"><Landmark className="h-4 w-4" /></span>
            <span className="flex items-center gap-2">
              <Tag>Both classes</Tag>
              <span className="font-mono text-caption text-slate-300">03</span>
            </span>
          </div>
          <h3 className="mt-5 font-display text-[24px] font-bold tracking-tight text-slate-900">Rules: today vs HB 2186</h3>
          <p className="mt-2 max-w-md text-body leading-relaxed text-slate-600">Most towns limit backyard homes today. HB 2186 would allow one on every home lot. Flip the switch to see what that does to the 2031 forecast.</p>
          <div className="mt-6">
            <Segmented label="Rules" value={rule} onChange={setRule} options={[{ value: 'current', label: "Today's rules" }, { value: 'hb2186', label: 'HB 2186' }]} />
          </div>
          <div className="mt-6 flex items-end gap-3">
            <motion.span key={rule} initial={{ opacity: 0, y: 10, filter: 'blur(4px)' }} animate={{ opacity: 1, y: 0, filter: 'blur(0px)' }} transition={{ duration: 0.35, ease: EASE_OUT }} className={cx('font-display text-[56px] font-bold leading-none tracking-tight tnum', hb ? 'text-violet-700' : 'text-slate-900')}>
              {hb ? '16,861' : '928'}
            </motion.span>
            <span className="pb-2 text-small text-slate-600">ADUs by 2031, statewide<br />(mid case, range {hb ? '8,195 to 25,526' : '197 to 2,693'})</span>
          </div>
        </div>
        <div className="rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-200/70 sm:p-5">
          <div className="flex items-center justify-between text-caption text-slate-500">
            <span>Top towns, ADUs by 2031 (mid)</span>
            <span>{hb ? 'HB 2186' : "Today's rules"}</span>
          </div>
          <div className="mt-3 space-y-2.5">
            {towns.map((t, i) => {
              const v = hb ? t.hb : t.cur;
              return (
                <div key={t.name} className="grid grid-cols-[124px_1fr_40px] items-center gap-3 text-small max-sm:grid-cols-[96px_1fr_36px]">
                  <span className="truncate text-slate-700">{t.name}</span>
                  <div className="h-2.5 overflow-hidden rounded-full bg-white ring-1 ring-stone-200/70">
                    <motion.div className={cx('h-full rounded-full', hb ? 'bg-violet-600' : 'bg-slate-400')} initial={{ width: 0 }} animate={{ width: `${(v / 401) * 100}%` }} transition={{ type: 'spring', stiffness: 120, damping: 20, delay: i * 0.04 }} />
                  </div>
                  <span className="text-right font-semibold text-slate-900 tnum">{v}</span>
                </div>
              );
            })}
          </div>
          <p className="mt-4 text-caption leading-snug text-slate-500">Only 9 towns are coded today. Others are treated as limited, which drives most of the gap.</p>
        </div>
      </div>
    </SpotlightCard>
  );
}

// ------------------------------------------------------------------ audiences
function Audiences() {
  return (
    <section className="border-y border-stone-200/70 bg-white/60">
      <div className="mx-auto max-w-7xl px-4 py-24 sm:px-6 sm:py-28">
        <SectionHead eyebrow="Built for two jobs" title="One map, two kinds of answers" sub="Builders want a yes or no for one lot. Planners want the total for their town. The tool gives both." />
        <div className="mt-14 grid gap-4 lg:grid-cols-2">
          <Reveal>
            <AudienceCard icon={<HardHat className="h-5 w-5" />} who="Developers and homeowners" line="Type an address. Get a verdict for that lot in a second." points={['Is it allowed today, and under HB 2186?', 'Room for 600 sq ft, with or without cutting trees', 'Rent vs monthly cost for the tract']}>
              <MockVerdict />
            </AudienceCard>
          </Reveal>
          <Reveal delay={0.08}>
            <AudienceCard icon={<Building2 className="h-5 w-5" />} who="Planners" line="Click a town. See how many ADUs could come by 2031." points={['Low, mid, and high range for every town', 'Lots with room per tract, statewide', 'Growth in jobs, people, and permits since 2010']}>
              <MockPlanner />
            </AudienceCard>
          </Reveal>
        </div>
      </div>
    </section>
  );
}

function AudienceCard({ icon, who, line, points, children }: { icon: ReactNode; who: string; line: string; points: string[]; children: ReactNode }) {
  return (
    <SpotlightCard className="h-full">
      <div className="grid h-full gap-6 p-6 sm:grid-cols-[1fr_1.05fr] sm:p-8">
        <div>
          <span className="grid h-10 w-10 place-items-center rounded-xl bg-slate-900 text-white">{icon}</span>
          <h3 className="mt-5 font-display text-[22px] font-bold tracking-tight text-slate-900">{who}</h3>
          <p className="mt-1.5 text-body text-slate-600">{line}</p>
          <ul className="mt-5 space-y-2.5">
            {points.map((p) => (
              <li key={p} className="flex gap-2.5 text-small text-slate-700">
                <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-violet-500" />
                {p}
              </li>
            ))}
          </ul>
        </div>
        <div className="self-center">{children}</div>
      </div>
    </SpotlightCard>
  );
}

function MockVerdict() {
  const tiles = [
    ['Allowed', 'Yes', 'HB 2186'],
    ['Room on lot', 'Fits', 'U-Net + fit test'],
    ['Pays off', 'Close', 'Rent vs cost'],
    ['Jobs since 2019', '+4.2%', 'Tract'],
  ];
  return (
    <div className="rounded-2xl bg-stone-50 p-3 ring-1 ring-stone-200/70">
      <div className="rounded-xl bg-amber-50 px-3 py-2.5 ring-1 ring-amber-200">
        <div className="text-small font-semibold text-amber-900">Works with changes</div>
        <div className="text-caption text-amber-800/80">Check the rule, the trees, or the rent.</div>
      </div>
      <div className="mt-2 grid grid-cols-2 gap-2">
        {tiles.map(([t, v, s], i) => (
          <motion.div key={t} initial={{ opacity: 0, y: 8 }} whileInView={{ opacity: 1, y: 0 }} viewport={{ once: true }} transition={{ delay: 0.2 + i * 0.08, duration: 0.4, ease: EASE_OUT }} className="rounded-xl bg-white px-3 py-2 ring-1 ring-stone-200/80">
            <div className="text-caption text-slate-500">{t}</div>
            <div className="font-display text-lead font-bold text-slate-900">{v}</div>
            <div className="text-[11px] text-slate-400">{s}</div>
          </motion.div>
        ))}
      </div>
    </div>
  );
}

function MockPlanner() {
  return (
    <div className="rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-200/70">
      <div className="text-caption text-slate-500">Lower Merion township</div>
      <div className="mt-1 font-display text-title font-bold text-slate-900">ADUs by 2031</div>
      <div className="mt-4 space-y-3">
        {[
          { k: "Today's rules", v: 7, c: 'bg-slate-400' },
          { k: 'HB 2186', v: 137, c: 'bg-violet-600' },
        ].map((r, i) => (
          <div key={r.k}>
            <div className="flex justify-between text-small"><span className="text-slate-700">{r.k}</span><span className="font-semibold text-slate-900 tnum">{r.v}</span></div>
            <div className="mt-1 h-2.5 overflow-hidden rounded-full bg-white ring-1 ring-stone-200/70">
              <motion.div className={cx('h-full rounded-full', r.c)} initial={{ width: 0 }} whileInView={{ width: `${Math.max(3, (r.v / 137) * 100)}%` }} viewport={{ once: true }} transition={{ type: 'spring', stiffness: 90, damping: 18, delay: 0.2 + i * 0.15 }} />
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 text-caption text-slate-500">Range under HB 2186: 67 to 208</div>
    </div>
  );
}

// ------------------------------------------------------------------ closing call to action
function ClosingCta() {
  return (
    <section className="mx-auto max-w-7xl px-4 py-24 sm:px-6">
      <Reveal>
        <div className="relative isolate overflow-hidden rounded-[32px] bg-slate-950 px-6 py-14 text-center sm:px-12 sm:py-20">
          <div aria-hidden className="absolute inset-0 -z-10 bg-[radial-gradient(60%_80%_at_50%_0%,rgba(124,58,237,0.55),transparent_70%)]" />
          <div aria-hidden className="absolute inset-0 -z-10 opacity-30 [background-image:radial-gradient(rgba(255,255,255,0.25)_1px,transparent_1px)] [background-size:22px_22px] [mask-image:radial-gradient(ellipse_at_center,black_20%,transparent_70%)]" />
          <h2 className="mx-auto max-w-2xl font-display text-[32px] font-bold leading-tight tracking-tight text-white sm:text-[44px]">Is there a backyard home in your backyard?</h2>
          <p className="mx-auto mt-4 max-w-lg text-lead text-violet-100/80">Search an address or click anywhere in Pennsylvania. Lot checks cover Philadelphia and Cumberland County. Tract numbers cover the whole state.</p>
          <div className="mt-8 flex flex-wrap justify-center gap-3">
            <LinkButton href="#/tool" size="lg" className="bg-white text-slate-900 shadow-none hover:bg-violet-50">
              Open the tool <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
            </LinkButton>
            <LinkButton href="#/research/6950/results" size="lg" variant="ghost" className="text-white ring-1 ring-white/20 hover:bg-white/10">
              Read the research
            </LinkButton>
          </div>
        </div>
      </Reveal>
    </section>
  );
}
