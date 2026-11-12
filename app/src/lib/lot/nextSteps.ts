// "Next Step": the build checklist (buildSteps.ts) folded into at most six plain steps for a homeowner, each with
// what to do, who to contact, how long, what it costs (when the assumptions file knows) and an official link
// (nextLinks.ts). Nothing here adds a process fact: every sentence restates a step from buildSteps, the approval
// path of the verdict, or the scenario rows. When the answer is No, it says what would have to change instead.
import { answerOf } from './answer';
import { ASK_TIME, type BuildChecklist, type BuildStep, type StepId } from './buildSteps';
import { linkFor, type NextKind, type NextLink } from './nextLinks';
import type { ScenarioVerdict, UnitVerdict } from './verdict';
import { SCENARIO_NAME } from './words';

export interface NextStep {
  kind: NextKind;
  title: string;
  /** One or two short sentences. */
  text: string;
  who: string;
  time: string;
  cost: string | null;
  link: NextLink | null;
}

export interface NextPlan {
  /** "6 steps, through an Administrator's Exception. How long: ask the city." */
  summary: string;
  steps: NextStep[];
  /** Answer No: what would have to change. Then `steps` is empty. */
  change: { title: string; items: { text: string; link: NextLink | null }[] } | null;
}

const PATH_PHRASE: Record<string, string> = {
  by_right: 'allowed by right (no hearing)',
  administrator_exception: "through an Administrator's Exception (the zoning official decides, no hearing)",
  special_exception: 'through a special exception (a public hearing)',
  conditional_use: 'through a conditional use (a public hearing)',
  variance: 'only with a variance (a rule exception for hardship)',
};

const TIME = 'Ask the city how long this takes.';
const time = (steps: BuildStep[]) => steps.find((s) => s.time !== ASK_TIME)?.time ?? TIME;
const costOf = (steps: BuildStep[]) => {
  const fees = steps.filter((s) => s.fee).map((s) => `${s.title}: ${s.fee}`);
  return fees.length ? fees.join(' ') : null;
};

/** The plan for one unit on one lot under one scenario. */
export function nextSteps(b: BuildChecklist, v: UnitVerdict, rows: ScenarioVerdict[], place: string | null | undefined): NextPlan {
  const by = (ids: StepId[]) => b.steps.filter((s) => ids.includes(s.id));
  const one = (id: StepId) => b.steps.find((s) => s.id === id);
  const answer = answerOf(v).answer;
  const path = v.approval.path ?? null;

  if (answer === 'no' || b.stop) {
    const items: { text: string; link: NextLink | null }[] = [];
    if (v.changes.length) items.push({ text: `Change the unit. ${v.changes[0]}`, link: null });
    if (path === 'variance') items.push({ text: 'Ask the Zoning Board for a variance (a rule exception for hardship). It is hard to get, and many owners hire a lawyer.', link: linkFor(place, 'variance') });
    for (const r of rows) {
      if (r.scenario === v.scenario || r.scenario === 'today') continue;
      const a = answerOf(r.verdict).answer;
      if (a === 'yes' || a === 'approval') items.push({ text: `Under the ${SCENARIO_NAME[r.scenario]} it would be allowed, but that bill is not law yet.`, link: r.scenario === 'state_reform' ? linkFor(place, 'bill') : null });
    }
    if (!items.length) items.push({ text: 'Try another kind of unit or a smaller size in ADU Design, or ask the zoning office what would be allowed.', link: linkFor(place, 'rules') });
    return { summary: 'As drawn, this unit cannot be built here today.', steps: [], change: { title: 'What would have to change', items } };
  }

  const steps: NextStep[] = [];
  const confirm = one('confirm');
  if (confirm) {
    const notLaw = one('not_law');
    steps.push({ kind: 'rules', title: 'Check the rules', text: `${notLaw ? 'This uses a bill that is not law yet. ' : ''}Ask the zoning office to confirm what you can build on your lot.`, who: confirm.who, time: TIME, cost: null, link: notLaw && v.scenario === 'state_reform' ? linkFor(place, 'bill') : linkFor(place, 'rules') });
  }
  const plans = by(['survey', 'design', 'site_risk', 'flood']);
  if (plans.length) {
    const extra = [one('survey') && 'A land surveyor marks your exact lot lines first.', (one('site_risk') || one('flood')) && 'Your lot is on a slope or in a flood zone, so expect extra review.'].filter(Boolean).join(' ');
    steps.push({ kind: 'plans', title: 'Get plans drawn', text: `Hire a designer to draw the unit and where it sits on the lot.${extra ? ` ${extra}` : ''}`, who: one('survey') ? 'A designer and a land surveyor' : 'A designer or architect', time: time(plans), cost: costOf(plans), link: null });
  }
  const zoning = one('zoning');
  if (zoning) {
    const hist = one('historic');
    steps.push({ kind: 'zoning', title: zoning.title, text: `Your unit is ${PATH_PHRASE[path ?? ''] ?? 'allowed, but ask which approval it needs'}.${path === 'administrator_exception' ? ' Talk to your next-door neighbors early.' : ''}${hist ? ' Your lot is in a historic district, so the design needs historic review too.' : ''}`, who: zoning.who, time: time([zoning]), cost: costOf([zoning]), link: linkFor(place, 'zoning') });
  }
  const permit = by(['water_sewer', 'electric', 'building_permit', 'owner_occupancy']);
  const bp = one('building_permit');
  if (bp) {
    steps.push({ kind: 'permit', title: 'Get the building permit', text: `The city checks the plans against the building code. Check that water, sewer and power can serve the unit.${one('owner_occupancy') ? ' The owner must live on the lot, and you sign a statement for that.' : ''}`, who: bp.who, time: time(permit), cost: costOf(permit), link: linkFor(place, 'permit') });
  }
  const build = by(['inspections', 'occupancy']);
  if (build.length) steps.push({ kind: 'build', title: 'Build and pass inspections', text: 'Inspectors visit at each stage. At the end you get a certificate of occupancy (the OK to live there).', who: build[0].who, time: time(build), cost: costOf(build), link: linkFor(place, 'build') });
  const rent = by(['tax', 'rental_license']);
  if (rent.length) {
    const tax = one('tax');
    steps.push({ kind: 'rent', title: 'Before you rent it out', text: `Get a rental license.${tax ? ` ${tax.title.replace(/^Apply for the tax abatement$/, 'Apply for the tax break on new homes in time').replace(/^Expect a new tax value$/, 'Expect a new property tax value')}.` : ''}`, who: one('rental_license')?.who ?? rent[0].who, time: time(rent), cost: costOf(by(['rental_license'])), link: linkFor(place, 'rent') });
  }
  const how = PATH_PHRASE[path ?? ''] ?? 'with an approval to confirm';
  return { summary: `${steps.length} steps, ${how.replace(/ \(.*\)$/, '')}. How long: ask the city.`, steps, change: null };
}
