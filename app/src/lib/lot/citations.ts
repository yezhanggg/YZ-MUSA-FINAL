// Rule citations for display: section, link, "checked on" date and how sure we are.
// Every number on the lot screens points back to one of these, or to an assumption key.
import type { Citation, CitationConfidence } from './types.js';
import type { UnitVerdict } from './verdict.js';
import { dateText } from './words.js';
import { lotTownByFile, townShortName } from './towns.js';

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
  pa_chester_west_chester: 'West Chester Zoning Code (Ch. 112)',
  pa_chester_phoenixville: 'Phoenixville Zoning Code (Ch. 27)',
  pa_chester_west_vincent: 'West Vincent Zoning Code (Ch. 390)',
  pa_chester_malvern: 'Malvern Zoning Code (Ch. 220)',
  pa_chester_east_brandywine: 'East Brandywine Zoning Code (Ch. 399)',
  pa_centre_college: 'College Township Zoning Code (Ch. 200)',
  pa_montgomery_lower_merion: 'Lower Merion Zoning Code (Ch. 155)',
  pa_montgomery_narberth: 'Narberth Zoning Code (Ch. 500)',
  pa_montgomery_upper_dublin: 'Upper Dublin Zoning Code (Ch. 255)',
  pa_centre_state_college: 'State College Zoning Code (Ch. XIX)',
  pa_chester_north_coventry: 'North Coventry Zoning Code (Ch. 370)',
  pa_chester_east_coventry: 'East Coventry Zoning Code (Ch. 27)',
  pa_chester_honey_brook: 'Honey Brook Township Zoning Code (Ch. 27)',
  pa_chester_schuylkill: 'Schuylkill Township Zoning Code (Ch. 370)',
  pa_chester_west_caln: 'West Caln Zoning Code (Ch. 350)',
  pa_chester_west_goshen: 'West Goshen Zoning Code (Ch. 84)',
  pa_chester_east_goshen: 'East Goshen Zoning Code (Ch. 240)',
  pa_chester_westtown: 'Westtown Zoning Code (Ch. 170)',
  pa_chester_east_nottingham: 'East Nottingham Zoning Code (Ch. 27)',
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
  /** The section is a sentence (a planning default of the build), not a code section: it takes a full stop. */
  prose: boolean;
}

/** "pittsburgh#districts.R2-L" -> "Pittsburgh Zoning Code, district table" */
export function sourceLabel(file: string | undefined): string | null {
  if (!file) return null;
  const [name, part] = file.split('#');
  // A lot town with no hand label: "<town> Zoning Code", from the lot town list (lib/lot/towns.ts).
  const town = SOURCE_LABEL[name] ? null : lotTownByFile(name);
  const label = SOURCE_LABEL[name] ?? (town ? `${townShortName(town)} Zoning Code` : null);
  if (!label) return null;
  return part?.startsWith('districts') ? `${label}, district table` : label;
}

const webUrl = (u: string | null | undefined) => (u && /^https?:\/\//.test(u) ? u : null);

/**
 * A build step's own note as a sentence: a capital first letter, and "so no limit is applied" (the build used 0 ft
 * where the rule file gives no number) said as what it is, never as "no limit".
 */
function buildNote(section: string): string {
  const t = section.trim().replace(/,? so no limit is applied$/i, ', so the fit used 0 ft and it is not checked').replace(/\.$/, '');
  return `${t.charAt(0).toUpperCase()}${t.slice(1)}`;
}

export function formatCitation(c: Citation): CitationView {
  const checked = dateText(c.verified_on);
  const build = c.source_file === 'build_lots';
  // A planning default the build could not check against the rule file ("not checked: ...") says so once, in its
  // own words, with no date: it is a step of the build, not a reading of the code.
  const notChecked = build && /^not checked/i.test(c.section);
  const section = build ? buildNote(c.section) : c.section;
  const source = notChecked ? null : sourceLabel(c.source_file);
  const checkedText = notChecked ? '' : checked ? `Checked on ${checked}` : 'Date not recorded';
  return {
    section,
    url: webUrl(c.url),
    checked_on: c.verified_on ?? null,
    checked_text: checkedText,
    confidence: c.confidence,
    confidence_label: CONFIDENCE_LABEL[c.confidence],
    source,
    text: [section, source, checkedText].filter(Boolean).join('. ') + '.',
    prose: build,
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
