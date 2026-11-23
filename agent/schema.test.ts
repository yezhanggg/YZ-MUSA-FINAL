// The system prompt covers each trap the eval set tests, and the tool list stays valid.
import { describe, expect, it } from 'vitest';
import { SYSTEM_PROMPT, TOOLS } from './schema';

describe('system prompt', () => {
  it.each([
    ['cites only what tools returned', /Cite only code sections and links that a tool returned/],
    ['says when a field is missing', /not on file.*not in your data/s],
    ['says bills are not law', /bills, not law/],
    ['corrects a wrong premise', /wrong premise, correct it/],
    ['never gives owner names', /Never give owner names/],
    ['adds the notice once', /Once per conversation, add the short line: "Not legal advice/],
    ['answers short: yes or no, why, what to do', /\*\*Yes\*\*, \*\*No\*\* or \*\*Not sure yet\*\*[\s\S]*\*\*What to do:\*\*/],
    ['keeps the testing mode rule', /scenario and unit/],
    ['sends parcel, document and contact questions to get_parcel_info', /parcel and records[\s\S]*call get_parcel_info/],
    ['sends tax questions to get_property_tax with year and source', /Property tax[\s\S]*call get_property_tax\. Give each rate with its year and source/],
    ['sends what-next questions to get_next_steps', /What to do next[\s\S]*call get_next_steps/],
    ['owner, assessment and tax bill are not in the data, with the county record', /assessed value and tax bill[\s\S]*"not in my data"[\s\S]*property_record/],
    ['answers district yards, height and coverage from district_rules, with the section, and says not on file', /district_rules, with the value and its section[\s\S]*not_on_file[\s\S]*"not on file"[\s\S]*Never give a typical/],
    ['keeps district rules and ADU rules apart', /District rules and ADU rules are not the same/],
    ['says what a flag means and who reviews it', /flags_that_matter/],
    ['sends HB 2186 for this lot to get_lot_rules changes_from_today', /HB 2186[\s\S]*get_lot_rules with scenario state_reform[\s\S]*changes_from_today/],
    ['redraws the unit with set_unit, then tests it', /action set_unit[\s\S]*then test_unit_on_lot/],
  ])('%s', (_name, re) => expect(SYSTEM_PROMPT).toMatch(re));

  it('names only tools that exist', () => {
    const names = new Set(TOOLS.map((t) => t.name));
    for (const m of SYSTEM_PROMPT.matchAll(/\b(get_[a-z_]+|test_[a-z_]+|compare_[a-z_]+|lot_money|explain_limit|find_lots|set_map)\b/g)) expect(names.has(m[1]), m[1]).toBe(true);
  });

  it('tool names are unique', () => {
    expect(new Set(TOOLS.map((t) => t.name)).size).toBe(TOOLS.length);
  });
});
