// Explore areas, top of the right panel: one plain answer for a tract and its town, read off the payoff estimate
// (lib/adu tractPayoff) and the town rule (lib/rules ruleFor). Nothing here decides a rule or a payoff.
import type { Answer } from '../lib/lot/answer';
import type { Pays } from '../lib/adu';
import type { RuleResult } from '../lib/rules';
import { placeAnswer, type PlaceRow } from './places';

export interface AreaAnswer {
  answer: Answer;
  /** One word or two: Yes, Maybe, No, Not sure. */
  title: string;
  /** "Pays off · Allowed in Pittsburgh city". */
  sub: string;
  pay: string;
  rule: string;
}

export const PAY_PHRASE: Record<Pays | 'none', string> = {
  yes: 'Pays off',
  maybe: 'Close to paying off',
  no: 'Does not pay off',
  none: 'No payoff estimate',
};

/**
 * The town's rule from the statewide places table (pa_places.json): a town with a rule file (verified or drafted) or a
 * dated record has an answer there, even when the older town layer (towns.geojson) has no rule coded. null when the
 * table has no checked answer for the town, so the caller keeps the town layer's rule.
 */
export function placeRule(r: PlaceRow | undefined): RuleResult | null {
  if (!r || r.status === 'unknown' || (r.tier !== 'verified' && r.tier !== 'drafted' && r.tier !== 'reported')) return null;
  const a = placeAnswer(r, 'current');
  const tone = a.answer === 'yes' ? 'good' : a.answer === 'approval' ? 'warn' : 'bad';
  return { label: a.title.replace(/ today$/, ''), sub: a.sub, tone, ok: tone === 'good', blocked: tone === 'bad', why: null, fromLot: false };
}

/** The town rule in a few words: "Allowed in Pittsburgh city", "Not allowed in X", "Rules not on file". */
export function rulePhrase(rule: Pick<RuleResult, 'label' | 'tone'>, town: string | null): string {
  if (rule.tone === 'none') return 'Town rules not on file';
  return town ? `${rule.label} in ${town}` : rule.label;
}

/**
 * Yes: pays off and allowed. No: not allowed, or does not pay off. Not sure: no payoff number and no town rule on file.
 * Maybe: anything in between (close to paying off, limited, or one of the two unknown).
 */
export function areaAnswer(pays: Pays | null, rule: Pick<RuleResult, 'label' | 'tone' | 'blocked'>, town: string | null): AreaAnswer {
  const pay = PAY_PHRASE[pays ?? 'none'];
  const ruleText = rulePhrase(rule, town);
  let answer: Answer;
  if (rule.blocked || pays === 'no') answer = 'no';
  else if (pays === 'yes' && rule.tone === 'good') answer = 'yes';
  else if (pays === null && rule.tone === 'none') answer = 'unknown';
  else answer = 'approval';
  const title = { yes: 'Yes', approval: 'Maybe', no: 'No', unknown: 'Not sure' }[answer];
  return { answer, title, sub: `${pay} · ${ruleText}`, pay, rule: ruleText };
}
