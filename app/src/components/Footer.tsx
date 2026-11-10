import { ExternalLink } from 'lucide-react';
import { GITHUB_URL, QUARTO_URL } from '../lib/router';
import { Logo } from './SiteNav';

export default function Footer() {
  return (
    <footer className="border-t border-stone-200/70 bg-white/60">
      <div className="mx-auto grid max-w-7xl gap-8 px-4 py-10 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr_1fr]">
        <div>
          <div className="flex items-center gap-2.5">
            <Logo className="h-7 w-7" />
            <span className="font-display text-body font-bold text-slate-900">Backyard Homes PA</span>
          </div>
          <p className="mt-3 max-w-xs text-small text-slate-600">Where Pennsylvania could add backyard homes, and where they would pay off. Ye Zhang, MUSA 5500 + MUSA 6950, Fall 2026.</p>
        </div>
        <FooterCol title="Product">
          <a href="#/tool">Tool</a>
          <a href="#/">Overview</a>
          <a href="#/about">About and credits</a>
        </FooterCol>
        <FooterCol title="Research">
          <a href="#/research/5500/results">MUSA 5500: Demand and payoff</a>
          <a href="#/research/6950/results">MUSA 6950: Room on the lot</a>
          <a href={QUARTO_URL}>Class version (Quarto)</a>
        </FooterCol>
        <FooterCol title="Code">
          <a href={GITHUB_URL} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1">
            GitHub <ExternalLink className="h-3 w-3" />
          </a>
          <span className="text-slate-500">Apache-2.0</span>
        </FooterCol>
      </div>
      <div className="border-t border-stone-200/70">
        <div className="mx-auto flex max-w-7xl flex-wrap justify-between gap-2 px-4 py-4 text-caption text-slate-500 sm:px-6">
          <span>© 2026 Ye Zhang · University of Pennsylvania, MUSA</span>
          <span>Map data © OpenStreetMap contributors · Basemap OpenFreeMap · Footprints Microsoft (ODbL)</span>
        </div>
      </div>
    </footer>
  );
}

function FooterCol({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <div className="text-caption font-semibold uppercase tracking-[0.14em] text-slate-500">{title}</div>
      <div className="mt-3 flex flex-col gap-2 text-small text-slate-700 [&_a:hover]:text-violet-700">{children}</div>
    </div>
  );
}
