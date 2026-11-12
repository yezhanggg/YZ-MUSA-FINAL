// The two Research pages. Each has three short sections: Purpose, Data, Methods.
// Written from musa*/docs/proposal.md, data.md and methods.md. Scores and totals come from lib/numbers.ts.
import { useState, type ReactNode } from 'react';
import { motion } from 'motion/react';
import { BookOpen } from 'lucide-react';
import figLots from '../../../musa6950/docs/figures/09_pittsburgh_lot_sheet.png';
import figPayoff from '../../../musa5500/docs/figures/04_payoff_map.png';
import { NUMBERS } from '../lib/numbers';
import { QUARTO_URL, type Course } from '../lib/router';
import { EASE_OUT } from '../components/primitives';

interface Page {
  name: string;
  title: string;
  purpose: ReactNode[];
  data: [string, string, string, string][];
  methods: { title: string; body: ReactNode }[];
  figure: { src: string; caption: string; after: number };
  /** Link the interactive tract explorer (MUSA 5500). */
  explorer?: boolean;
}

const PAGES: Record<Course, Page> = {
  '6950': {
    name: 'MUSA 6950',
    title: 'Room on the lot',
    purpose: [
      'On a given lot in Philadelphia or Pittsburgh, can a backyard home go up, where, and how big?',
      'Aerial images answer part of it: trees, open ground, paving and small buildings.',
      'Lot lines, building outlines and zoning answer the rest, under three scenarios: today, the local bill and the state bill (bills are not law).',
      <>
        Full methods and results are on the class site:{' '}
        <a className="font-semibold text-violet-700 underline-offset-2 hover:underline" href={`${QUARTO_URL}musa6950/docs/methods.html`}>methods</a>,{' '}
        <a className="font-semibold text-violet-700 underline-offset-2 hover:underline" href={`${QUARTO_URL}musa6950/docs/results.html`}>results</a>.
      </>,
    ],
    data: [
      ['NAIP aerial images (USDA)', 'Red, green, blue, near-infrared', '2022', '0.6 m. 173 boxes of 1 km'],
      ['Chesapeake Bay land cover', 'Training and test labels', '2022 epoch', '1 m. Test counties: Cumberland and Centre'],
      ['University of Vermont city land cover', 'City labels, Philadelphia lot cover', '2018 (Phila.), 2019 (Pgh.)', '2 ft'],
      ['PEMA orthophotos (PASDA)', 'Structure detector images', '2021 to 2023', '0.5 ft'],
      ['City parcels and building footprints', 'Lot lines and buildings', '2026', 'Philadelphia and Pittsburgh'],
      ['Zoning codes and bills', 'Rule files, three scenarios', 'Checked Nov 2026', 'Per lot'],
    ],
    methods: [
      { title: 'Labels', body: 'Chesapeake codes are grouped into 4 classes (other, building, tree, open), or 5 with hard surface split out. Cumberland and Centre counties are held out as the test counties.' },
      { title: 'Baselines', body: <>A Random Forest on the four bands plus NDVI (mean IoU {NUMBERS.rfMiou}), and a first plain U-Net.</> },
      { title: 'U-Net', body: <>A U-Net with a pretrained ResNet-34 encoder. Every variant lands near {NUMBERS.unetMiou} test mean IoU. Seeds, NDVI, Dice and more epochs barely move it. The error analysis says the labels are the limit.</> },
      { title: 'The two cities', body: 'In Pittsburgh the model transfers without city training, about 0.70 on clean test pixels. A first fine-tune score of 0.719 came from test boxes that overlapped training boxes and is withdrawn. In Philadelphia the spring photos hide trees and lawns (tree IoU about 0.26), so the lot tool uses the city\'s 2018 land cover raster there.' },
      { title: 'Structure detector', body: 'A YOLO model for garages, sheds, other outbuildings and pools on PEMA images. It is scored against first-pass labels that no one has checked, so its scores are agreement, not accuracy. It is not used in the lot records.' },
      { title: 'Fit test', body: 'A vector test on the lot lines, building outlines and streets. The lot shrinks by the setbacks of the rules, the house and garages are cut out, and the largest rectangle that fits is the room for a unit. Land cover adds context and does not change the answer.' },
      { title: 'Lot results', body: <>{NUMBERS.lotsPittsburgh} {NUMBERS.lotsPhiladelphia}</> },
      { title: 'Not checked yet', body: 'No hand-labeled lot exists yet (0 of 250), so the fit answers have not been checked against a person looking at the lot.' },
    ],
    figure: { src: figLots, caption: 'Twenty random Pittsburgh lots from the final build. Gray: house. Brown: garage. Green: buildable ground today. Blue: the suggested unit.', after: 6 },
  },
  '5500': {
    name: 'MUSA 5500',
    title: 'Demand and payoff',
    purpose: [
      'Legal does not mean built. Philadelphia has allowed ADUs in parts of the city since 2012, and only about 10 were built legally.',
      'ADUs get built where demand is growing and the rent covers the cost.',
      'This part asks where people and jobs are growing, and if that changed after 2019.',
      'It tests where an ADU would pay off, and how many could be built by 2031.',
    ],
    data: [
      ['ACS 5-year (Census API)', 'People, rent, home value, renters', '2010-14 to 2020-24', 'Tract'],
      ['ACS 5-year, table B25031', 'Rent by bedroom count', '2020-24', 'Tract, county ratios'],
      ['Decennial Census', 'Housing units', '2010, 2020', 'Tract'],
      ['Population Estimates', 'Town population', '2010-2025', 'Town'],
      ['LEHD LODES8', 'Jobs', '2010 to 2024', 'Block, summed to tract'],
      ['Building Permits Survey', 'New homes permitted', '2010-2025', 'Town'],
      ['Freddie Mac PMMS', '30-year mortgage rate', 'Weekly', 'State'],
      ['Annual NLCD (USGS)', 'Developed land', '2010, 2019, 2025', '30 m raster'],
      ['OpenStreetMap (OSMnx)', 'Street network', 'Current', 'Metro area'],
      ['MUSA 6950', 'Lots with room', '2022 images', 'Tract'],
    ],
    methods: [
      { title: 'Put everything on 2020 tracts', body: 'Move 2010-tract counts to 2020 tracts with the Census block crosswalk. Rent and values are in 2024 dollars.' },
      { title: 'Growth before and after 2019', body: 'Yearly growth in people, homes and rent across three ACS 5-year windows that do not overlap: 2010-14, 2015-19 and 2020-24 (midpoints 2012, 2017, 2022). Jobs compare 2010-19 with 2019-24. Where a change is smaller than its margin of error, the map says so.' },
      { title: 'Group places by trend', body: <>K-means on the growth rates gives {NUMBERS.groups} stable groups. The structure is weak (silhouette {NUMBERS.groupsSilhouette}), so the groups describe tracts. They are not a discovery.</> },
      { title: 'Land and job access', body: 'Share of developed land from NLCD rasters. Jobs within 30 minutes by car from OSMnx, for Philadelphia.' },
      { title: 'Does an ADU pay off?', body: <>A 600 sq ft unit at $175, $250 or $300 per sq ft, borrowed over 30 years at 6.53%. It pays if the tract's 1-bedroom rent, minus 30% for costs, covers the monthly payment. That is true in about {NUMBERS.paysShare} of tracts at the mid cost.</> },
      { title: 'ADUs by 2031', body: <>A gradient boosting model (county-held-out R2 about {NUMBERS.forecastR2}) ranks where housing grows. Combine it with permit rates from cities that allow ADUs, the payoff, lots with room and each town's rule. The mid case is {NUMBERS.adusHb2186} under HB 2186, {NUMBERS.adusSb1346} under SB 1346 and {NUMBERS.adusToday} under today's rules. This is scenario arithmetic, not a fitted ADU forecast. Both bills die on Nov 30, 2026 if not enacted.</> },
      { title: 'Other sizes', body: 'In the tool you pick bedrooms, size and stories. Rent comes from ACS rent for that bedroom count, and cost from that size, with the same loan and the same yes, close or no rule. The town forecast stays at 600 sq ft.' },
    ],
    figure: { src: figPayoff, caption: 'Where a 600 sq ft 1-bedroom unit pays off at the mid build cost.', after: 4 },
    explorer: true,
  },
};

export default function Research({ course }: { course: Course }) {
  const p = PAGES[course];
  return (
    <motion.article key={course} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4, ease: EASE_OUT }} className="mx-auto max-w-3xl px-4 pb-12 pt-10 sm:px-6 sm:pt-14">
      <div className="text-caption font-semibold uppercase tracking-[0.16em] text-violet-700">Research · {p.name}</div>
      <h1 className="mt-2 font-display text-[34px] font-bold leading-tight tracking-tight text-slate-900 sm:text-[42px]">{p.title}</h1>

      <Section n="1" title="Purpose">
        <ul className="space-y-2">
          {p.purpose.map((b, i) => (
            <li key={i} className="flex gap-3 text-body leading-relaxed text-slate-700 sm:text-[15px]">
              <span className="mt-[0.6em] h-1.5 w-1.5 shrink-0 rounded-full bg-violet-500" />
              <span>{b}</span>
            </li>
          ))}
        </ul>
      </Section>

      <Section n="2" title="Data">
        <div className="overflow-x-auto rounded-2xl bg-white ring-1 ring-stone-200/80">
          <table className="w-full min-w-[560px] text-left text-small">
            <thead className="bg-stone-50 text-caption text-slate-500">
              <tr>
                {['Source', 'What', 'Year', 'Detail'].map((h) => (
                  <th key={h} className="px-3.5 py-2 font-semibold">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-stone-100">
              {p.data.map((r) => (
                <tr key={r[0]}>
                  <td className="px-3.5 py-2 font-medium text-slate-900">{r[0]}</td>
                  <td className="px-3.5 py-2 text-slate-700">{r[1]}</td>
                  <td className="whitespace-nowrap px-3.5 py-2 text-slate-600 tnum">{r[2]}</td>
                  <td className="px-3.5 py-2 text-slate-600">{r[3]}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Section>

      <Section n="3" title="Methods">
        <ol className="space-y-4">
          {p.methods.map((m, i) => (
            <li key={m.title}>
              <div className="flex gap-3.5">
                <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg bg-violet-50 text-small font-bold text-violet-700 ring-1 ring-violet-200 tnum">{i + 1}</span>
                <div className="pt-0.5">
                  <div className="font-semibold text-slate-900">{m.title}</div>
                  <p className="mt-0.5 text-body leading-relaxed text-slate-700 sm:text-[15px]">{m.body}</p>
                </div>
              </div>
              {i + 1 === p.figure.after && (
                <figure className="mt-5">
                  <img src={p.figure.src} alt={p.figure.caption} loading="lazy" className="w-full rounded-2xl bg-white ring-1 ring-stone-200/80" />
                  <figcaption className="mt-2 text-center text-caption text-slate-500">{p.figure.caption}</figcaption>
                </figure>
              )}
            </li>
          ))}
        </ol>
      </Section>

      {p.explorer && <Explorer />}

      <Credits />
    </motion.article>
  );
}

/** The interactive tract explorer (Altair), copied next to the site at build time. Loads only when opened. */
export const EXPLORER_URL = '/explorer/tract_explorer.html';

function Explorer() {
  const [open, setOpen] = useState(false);
  return (
    <Section n="4" title="Explore the tracts">
      <p className="text-body leading-relaxed text-slate-700 sm:text-[15px]">Click a county or brush the scatter plot to filter the bars, the histogram and the table.</p>
      {open ? (
        <iframe src={EXPLORER_URL} title="Tract explorer" loading="lazy" className="mt-3 h-[720px] w-full rounded-2xl bg-white ring-1 ring-stone-200/80" />
      ) : (
        <button type="button" onClick={() => setOpen(true)} className="tap mt-3 rounded-lg bg-violet-600 px-3 py-2 text-small font-semibold text-white hover:bg-violet-700">
          Open the explorer here
        </button>
      )}
      <p className="mt-2">
        <a href={EXPLORER_URL} target="_blank" rel="noreferrer" className="text-small font-semibold text-violet-700 hover:underline">
          Open it in a new tab
        </a>
      </p>
    </Section>
  );
}

function Section({ n, title, children }: { n: string; title: string; children: ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="mb-4 flex items-baseline gap-2.5 font-display text-[22px] font-bold tracking-tight text-slate-900">
        <span className="font-mono text-small font-normal text-slate-400">0{n}</span>
        {title}
      </h2>
      {children}
    </section>
  );
}

function Credits() {
  return (
    <footer className="mt-14 space-y-1.5 border-t border-stone-200 pt-5 text-caption leading-relaxed text-slate-500">
      <p>
        Map data © <a className="underline hover:text-slate-800" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors (ODbL). Basemap <a className="underline hover:text-slate-800" href="https://openfreemap.org/" target="_blank" rel="noreferrer">OpenFreeMap</a>. Search <a className="underline hover:text-slate-800" href="https://photon.komoot.io/" target="_blank" rel="noreferrer">Photon</a> by komoot. Building outlines © Microsoft (ODbL). Parcels: City of Philadelphia, Allegheny County. Aerial imagery: PEMA, via PASDA. Map by <a className="underline hover:text-slate-800" href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a>.
      </p>
      <p>AI use: Claude Code wrote the scripts, tool, docs, and notebook code at my request. I set the question, design, and checks.</p>
      <p className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <span>Ye Zhang · MUSA 5500 + MUSA 6950 · Fall 2026 · Apache-2.0</span>
        <a href={QUARTO_URL} className="inline-flex items-center gap-1 font-semibold text-violet-700 hover:text-violet-900">
          <BookOpen className="h-3.5 w-3.5" /> Class version (Quarto)
        </a>
      </p>
    </footer>
  );
}
