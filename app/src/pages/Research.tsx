// The two Research pages. Each has three short sections: Purpose, Data, Methods.
// Written from musa*/docs/proposal.md, data.md and methods.md. Scores and totals come from lib/numbers.ts.
import type { ReactNode } from 'react';
import { motion } from 'motion/react';
import { BookOpen } from 'lucide-react';
import figUnet from '../../../musa6950/docs/figures/03_example_prediction.png';
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
}

const PAGES: Record<Course, Page> = {
  '6950': {
    name: 'MUSA 6950',
    title: 'Room on the lot',
    purpose: [
      'HB 2186 would allow one backyard home (ADU) on every home lot in Pennsylvania.',
      'No one knows how many lots actually have room for one.',
      'Backyards hold a lot of trees, so building there has a cost.',
      'This part finds open ground on each lot from aerial images, then tests if a 600 sq ft unit fits.',
      'It also checks if AI on images does better than building outlines alone.',
    ],
    data: [
      ['NAIP aerial images (USDA)', 'Red, green, blue, near-infrared', '2022', '0.6 m pixels. 173 sample boxes of 1 km'],
      ['Chesapeake Bay land cover (USGS)', 'Training labels', '2022', '1 m. 43 PA counties'],
      ['Microsoft building footprints', 'Building outlines', '2026', 'Polygons. ODbL'],
      ['Philadelphia parcels', 'Lot lines', 'Current', 'Polygons'],
      ['Cumberland County parcels (PASDA)', 'Lot lines', '2026', 'Polygons'],
      ['USDA RUCA codes', 'Urban, suburban, rural', '2020', 'Tract'],
      ['ACS 5-year, table B25024', 'Single-family homes', '2020-24', 'Tract'],
    ],
    methods: [
      { title: 'Sample and labels', body: 'Pick 1 km boxes in urban, suburban and rural tracts. Group the 56 Chesapeake classes into 4: building, tree, open ground, other. Cumberland and Centre counties are held out for testing.' },
      { title: 'Random Forest baseline', body: 'Classify each pixel from its 4 bands plus NDVI. This is the simple model to beat.' },
      { title: 'U-Net', body: <>Train a U-Net with a pretrained ResNet-34 encoder on 384 x 384 crops to label every pixel. On the held-out counties it scores a mean IoU of {NUMBERS.unetMiou}, against {NUMBERS.rfMiou} for the Random Forest.</> },
      { title: 'Pick single-family lots', body: 'Keep lots with one main house outline. Smaller outlines count as garages or sheds.' },
      { title: 'Fit test', body: 'Take each lot, minus 5 ft from the lot lines and 10 ft around the house. A 20 x 30 ft spot has to fit in open ground, in either direction. Run it again with trees not allowed.' },
      { title: 'Statewide', body: <>Fit rates from the pilot lots are applied to single-family homes in every tract, by urban, suburban and rural. That gives about {NUMBERS.lotsWithRoom} lots with room.</> },
      { title: 'Other sizes', body: 'In the tool you can change the ADU. Its footprint is size divided by stories, and a lot has room if its largest open spot is at least that big.' },
    ],
    figure: { src: figUnet, caption: 'A test box in Cumberland County: image, label, Random Forest, U-Net.', after: 2 },
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
      { title: 'Growth before and after 2019', body: 'Yearly growth in people, homes, jobs and rent, for 2010-19 and for 2019 on. The change between them shows where growth sped up or slowed.' },
      { title: 'Group places by trend', body: 'K-means on the growth rates puts tracts into 5 trend groups.' },
      { title: 'Land and job access', body: 'Share of developed land from NLCD rasters. Jobs within 30 minutes by car from OSMnx, for Philadelphia.' },
      { title: 'Does an ADU pay off?', body: <>A 600 sq ft unit at $175, $250 or $300 per sq ft, borrowed over 30 years. It pays if local rent, minus 30% for costs, covers the monthly payment. That is true in about {NUMBERS.paysShare} of tracts at the mid cost.</> },
      { title: 'ADUs by 2031', body: <>A random forest ranks where housing grows. Combine it with permit rates from cities that allow ADUs, the payoff, lots with room and each town's rule. The mid case is {NUMBERS.adusHb2186} under HB 2186 vs {NUMBERS.adusToday} under today's rules.</> },
      { title: 'Other sizes', body: 'In the tool you pick bedrooms, size and stories. Rent comes from ACS rent for that bedroom count, and cost from that size, with the same loan and the same yes, close or no rule. The town forecast stays at 600 sq ft.' },
    ],
    figure: { src: figPayoff, caption: 'Where an ADU pays off at the mid build cost.', after: 4 },
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

      <Credits />
    </motion.article>
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
        Map data © <a className="underline hover:text-slate-800" href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap</a> contributors (ODbL). Basemap <a className="underline hover:text-slate-800" href="https://openfreemap.org/" target="_blank" rel="noreferrer">OpenFreeMap</a>. Search <a className="underline hover:text-slate-800" href="https://photon.komoot.io/" target="_blank" rel="noreferrer">Photon</a> by komoot. Building outlines © Microsoft (ODbL). Parcels: City of Philadelphia (PWD), Cumberland County GIS. Map by <a className="underline hover:text-slate-800" href="https://maplibre.org/" target="_blank" rel="noreferrer">MapLibre</a>.
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
