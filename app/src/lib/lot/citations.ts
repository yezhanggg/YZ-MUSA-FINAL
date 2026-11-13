// Rule citations for display: section, link, "checked on" date and how sure we are.
// Every number on the lot screens points back to one of these, or to an assumption key.
import type { Citation, CitationConfidence } from './types';
import type { UnitVerdict } from './verdict';
import { dateText } from './words';

/** Shown under every lot answer, the report and the assistant's rule answers. */
export const NOTICE =
  'Not legal advice. Not a zoning determination. Parcel lines are not a survey. Check with the city or township before you design or build.';

export const CONFIDENCE_LABEL: Record<CitationConfidence, string> = {
  verified: 'Read in the code',
  secondary: 'From an official guide or a careful reading',
  unverified: 'Not confirmed',
};

/** Rule file (or build step) -> what it is, in words. */
const SOURCE_LABEL: Record<string, string> = {
  pittsburgh: 'Pittsburgh Zoning Code',
  philadelphia: 'Philadelphia Zoning Code',
  pa_lehigh_allentown: 'Allentown Zoning Code (Ch. 660)',
  default: 'Building code default',
  hb2186: 'State bill HB 2186 (not law)',
  sb1346: 'State bill SB 1346 (not law)',
  bill250042: 'Philadelphia Bill 250042 (pending)',
  build_lots: 'Planning default',
  'rule notes': 'Rule notes',
};

export interface CitationView {
  section: string;
  /** A web link, or null when the source is not online. */
  url: string | null;
  /** ISO date the value was last checked. */
  checked_on: string | null;
  /** "Checked on Nov 10, 2026" */
  checked_text: string;
  confidence: CitationConfidence;
  confidence_label: string;
  /** "Pittsburgh Zoning Code, district table" */
  source: string | null;
  /** One line: section, source and date. */
  text: string;
}

/** "pittsburgh#districts.R2-L" -> "Pittsburgh Zoning Code, district table" */
export function sourceLabel(file: string | undefined): string | null {
  if (!file) return null;
  const [name, part] = file.split('#');
  const label = SOURCE_LABEL[name] ?? null;
  if (!label) return null;
  return part?.startsWith('districts') ? `${label}, district table` : label;
}

const webUrl = (u: string | null | undefined) => (u && /^https?:\/\//.test(u) ? u : null);

export function formatCitation(c: Citation): CitationView {
  const checked = dateText(c.verified_on);
  // A planning default the build could not check against the rule file ("not checked: ...") says so.
  const source = c.source_file === 'build_lots' && /^not checked/i.test(c.section) ? 'Not checked' : sourceLabel(c.source_file);
  const checkedText = checked ? `Checked on ${checked}` : 'Date not recorded';
  return {
    section: c.section,
    url: webUrl(c.url),
    checked_on: c.verified_on ?? null,
    checked_text: checkedText,
    confidence: c.confidence,
    confidence_label: CONFIDENCE_LABEL[c.confidence],
    source,
    text: [c.section, source, checkedText].filter(Boolean).join('. ') + '.',
  };
}

/** Distinct citations, in the order given. Two citations are the same when section and link match. */
export function sourcesOf(list: (Citation | null | undefined)[]): CitationView[] {
  const seen = new Set<string>();
  const out: CitationView[] = [];
  for (const c of list) {
    if (!c) continue;
    const key = `${c.section}|${c.url ?? ''}`;
    if (seen.has(key)) continue;
    seen.add(key);
    out.push(formatCitation(c));
  }
  return out;
}

/** The citations behind one answer: the approval path first, then the checks, then the warnings. */
export const verdictCitations = (v: UnitVerdict): (Citation | null)[] => [v.approval.citation, ...v.checks.map((c) => c.citation), ...v.warnings.map((w) => w.citation)];

/** Every source behind one answer, each once. */
export const collectSources = (v: UnitVerdict): CitationView[] => sourcesOf(verdictCitations(v));
