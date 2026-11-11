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
    ['adds the notice once', /Once per conversation, add: "Not legal advice/],
    ['keeps the testing mode rule', /scenario and unit/],
  ])('%s', (_name, re) => expect(SYSTEM_PROMPT).toMatch(re));

  it('names only tools that exist', () => {
    const names = new Set(TOOLS.map((t) => t.name));
    for (const m of SYSTEM_PROMPT.matchAll(/\b(get_[a-z_]+|test_[a-z_]+|compare_[a-z_]+|lot_money|explain_limit|find_lots|set_map)\b/g)) expect(names.has(m[1]), m[1]).toBe(true);
  });

  it('tool names are unique', () => {
    expect(new Set(TOOLS.map((t) => t.name)).size).toBe(TOOLS.length);
  });
});
