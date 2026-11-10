import type { ReactNode } from 'react';
import { ArrowUpRight, Bot, BookOpen, Database, FolderGit2, Map as MapIcon, Scale } from 'lucide-react';
import { Eyebrow, Reveal, Tag } from '../components/primitives';
import { GITHUB_URL, QUARTO_URL } from '../lib/router';

type Row = { name: string; what: string; license: string; url?: string; part: '5500' | '6950' | 'Tool' | 'Both' };

const DATA: Row[] = [
  { name: 'American Community Survey 5-year', what: 'Population, rent, home value, income, renters, single-family homes', license: 'Public domain (U.S. Census)', url: 'https://www.census.gov/programs-surveys/acs', part: 'Both' },
  { name: 'Decennial Census + Population Estimates', what: 'Housing units 2010 and 2020, town population 2010 to 2025', license: 'Public domain (U.S. Census)', url: 'https://www.census.gov/', part: '5500' },
  { name: 'LEHD LODES8', what: 'Jobs by block, 2010 to 2024', license: 'Public domain (U.S. Census)', url: 'https://lehd.ces.census.gov/data/', part: '5500' },
  { name: 'Building Permits Survey', what: 'New homes permitted by town', license: 'Public domain (U.S. Census)', url: 'https://www.census.gov/construction/bps/', part: '5500' },
  { name: 'IRS SOI migration', what: 'People moving in and out, by county', license: 'Public domain (IRS)', url: 'https://www.irs.gov/statistics/soi-tax-stats-migration-data', part: '5500' },
  { name: 'Freddie Mac PMMS', what: '30-year mortgage rate', license: 'Freddie Mac terms of use', url: 'https://www.freddiemac.com/pmms', part: '5500' },
  { name: 'Annual NLCD', what: 'Developed land, 30 m, 2010 / 2019 / 2025', license: 'Public domain (USGS)', url: 'https://www.usgs.gov/centers/eros/science/annual-national-land-cover-database', part: '5500' },
  { name: 'Census TIGER', what: 'Tracts, towns, counties, block crosswalk', license: 'Public domain (U.S. Census)', url: 'https://www.census.gov/geographies/mapping-files.html', part: 'Both' },
  { name: 'NAIP aerial images 2022', what: 'Red, green, blue, near-infrared at 0.6 m, via Microsoft Planetary Computer', license: 'Public domain (USDA)', url: 'https://planetarycomputer.microsoft.com/dataset/naip', part: '6950' },
  { name: 'Chesapeake Bay land cover', what: 'Training labels, 1 m, 2022', license: 'Public (USGS ScienceBase)', url: 'https://www.sciencebase.gov/', part: '6950' },
  { name: 'Microsoft Global ML Building Footprints', what: 'Building outlines', license: 'ODbL 1.0', url: 'https://github.com/microsoft/GlobalMLBuildingFootprints', part: '6950' },
  { name: 'Philadelphia parcels', what: 'Lot lines (Philadelphia Water Department)', license: 'City of Philadelphia open data terms', url: 'https://opendataphilly.org/', part: '6950' },
  { name: 'Cumberland County parcels', what: 'Lot lines via PASDA', license: 'County terms', url: 'https://www.pasda.psu.edu/', part: '6950' },
  { name: 'USDA RUCA codes', what: 'Urban, suburban, rural by tract', license: 'Public domain (USDA ERS)', url: 'https://www.ers.usda.gov/data-products/rural-urban-commuting-area-codes/', part: '6950' },
  { name: 'OpenStreetMap via OSMnx', what: 'Street network for job access', license: 'ODbL 1.0, © OpenStreetMap contributors', url: 'https://www.openstreetmap.org/copyright', part: '5500' },
];

const TOOL: Row[] = [
  { name: 'OpenFreeMap', what: 'Positron basemap tiles, free, no key', license: 'OpenFreeMap terms · OpenMapTiles · © OpenStreetMap contributors', url: 'https://openfreemap.org/', part: 'Tool' },
  { name: 'Photon by komoot', what: 'Address search, limited to Pennsylvania', license: 'Apache-2.0 service · OpenStreetMap data (ODbL)', url: 'https://photon.komoot.io/', part: 'Tool' },
  { name: 'MapLibre GL JS', what: 'The map', license: 'BSD-3-Clause', url: 'https://maplibre.org/', part: 'Tool' },
  { name: 'React, motion, Tailwind CSS, lucide', what: 'Interface', license: 'MIT / ISC', part: 'Tool' },
];

export default function About() {
  return (
    <div className="mx-auto max-w-5xl px-4 py-12 sm:px-6 sm:py-16">
      <Reveal>
        <Eyebrow>About</Eyebrow>
        <h1 className="mt-3 font-display text-[36px] font-bold leading-tight tracking-tight text-slate-900 sm:text-[48px]">Who made this, and from what</h1>
        <p className="mt-4 max-w-2xl text-lead text-slate-600">Backyard Homes PA is the final project of Ye Zhang for two classes in the Master of Urban Spatial Analytics program at the University of Pennsylvania, Fall 2026. MUSA 5500 covers demand and payoff. MUSA 6950 covers room on the lot.</p>
      </Reveal>

      <div className="mt-10 grid gap-3 sm:grid-cols-3">
        <Reveal delay={0}>
          <LinkCard icon={<FolderGit2 className="h-5 w-5" />} title="Code on GitHub" sub="Scripts, notebooks, tool" href={GITHUB_URL} external />
        </Reveal>
        <Reveal delay={0.06}>
          <LinkCard icon={<BookOpen className="h-5 w-5" />} title="Class version (Quarto)" sub="The MUSA 5500 site as submitted" href={QUARTO_URL} />
        </Reveal>
        <Reveal delay={0.12}>
          <LinkCard icon={<MapIcon className="h-5 w-5" />} title="Open the tool" sub="Search an address" href="#/tool" />
        </Reveal>
      </div>

      <Section icon={<Bot className="h-5 w-5" />} title="AI use">
        <div className="rounded-2xl bg-violet-50/70 p-5 text-body text-slate-800 ring-1 ring-violet-200/80">Claude Code wrote the scripts, tool, docs, and notebook code at my request. I set the question, design, and checks.</div>
      </Section>

      <Section icon={<Database className="h-5 w-5" />} title="Data sources">
        <Table rows={DATA} />
      </Section>

      <Section icon={<MapIcon className="h-5 w-5" />} title="Map, search, and software">
        <Table rows={TOOL} />
        <p className="mt-4 text-small text-slate-600">Map data © OpenStreetMap contributors, available under the Open Database License. Building outlines © Microsoft, ODbL. Lot results in the tool show only sizes and a yes or no. No owner data is used.</p>
      </Section>

      <Section icon={<Scale className="h-5 w-5" />} title="License and limits">
        <ul className="space-y-2 text-body text-slate-700">
          <li>Code is under the Apache-2.0 license. Data keeps the license of its source.</li>
          <li>Lot checks cover single-family lots in Philadelphia and Cumberland County. Other places show tract-level shares.</li>
          <li>Fit means room, not demand. Slope, septic, town setbacks, and owner choice are not in the rule.</li>
          <li>This is a class project, not legal or financial advice. Check your town's zoning office before building.</li>
        </ul>
      </Section>
    </div>
  );
}

function Section({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <Reveal as="section" className="mt-14">
      <h2 className="mb-5 flex items-center gap-3 font-display text-[24px] font-bold tracking-tight text-slate-900">
        <span className="grid h-9 w-9 place-items-center rounded-xl bg-white text-violet-700 ring-1 ring-stone-200">{icon}</span>
        {title}
      </h2>
      {children}
    </Reveal>
  );
}

function LinkCard({ icon, title, sub, href, external }: { icon: ReactNode; title: string; sub: string; href: string; external?: boolean }) {
  return (
    <a href={href} target={external ? '_blank' : undefined} rel={external ? 'noreferrer' : undefined} className="group flex h-full items-center gap-4 rounded-2xl bg-white p-4 ring-1 ring-stone-200 transition hover:-translate-y-0.5 hover:shadow-[0_14px_30px_-18px_rgba(76,29,149,0.4)] hover:ring-violet-300">
      <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-slate-900 text-white">{icon}</span>
      <span className="min-w-0 flex-1">
        <span className="block font-semibold text-slate-900 group-hover:text-violet-700">{title}</span>
        <span className="block text-small text-slate-500">{sub}</span>
      </span>
      <ArrowUpRight className="h-4 w-4 text-slate-400 transition group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-violet-600" />
    </a>
  );
}

function Table({ rows }: { rows: Row[] }) {
  return (
    <div className="overflow-hidden rounded-2xl bg-white ring-1 ring-stone-200/80">
      <ul className="divide-y divide-stone-100">
        {rows.map((r) => (
          <li key={r.name} className="grid gap-1 px-4 py-3 sm:grid-cols-[1.2fr_1.5fr_1.2fr_auto] sm:items-center sm:gap-4">
            <span className="font-semibold text-slate-900">
              {r.url ? (
                <a href={r.url} target="_blank" rel="noreferrer" className="hover:text-violet-700">
                  {r.name}
                </a>
              ) : (
                r.name
              )}
            </span>
            <span className="text-small text-slate-600">{r.what}</span>
            <span className="text-small text-slate-500">{r.license}</span>
            <span>
              <Tag tone={r.part === '5500' ? 'amber' : r.part === '6950' ? 'emerald' : r.part === 'Tool' ? 'sky' : 'violet'}>{r.part === 'Both' || r.part === 'Tool' ? r.part : `MUSA ${r.part}`}</Tag>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
