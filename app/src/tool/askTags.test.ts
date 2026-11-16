import { describe, expect, it } from 'vitest';
import { askTags } from './askTags';

const use = (id: string, name: string) => ({ role: 'assistant', content: [{ type: 'tool_use', id, name, input: {} }] });
const result = (id: string, body: unknown) => ({ role: 'user', content: [{ type: 'tool_result', tool_use_id: id, content: JSON.stringify(body) }] });
const LABEL = 'Unverified text search: passages copied word for word from the public zoning text.';

describe('chat tags', () => {
  it('a text search with passages is tagged unverified; one with none is not', () => {
    expect(askTags([use('a', 'search_zoning_text'), result('a', { label: LABEL, found: true, results: [{ quote: 'x' }] })]).unverified).toBe(true);
    expect(askTags([use('a', 'search_zoning_text'), result('a', { label: LABEL, found: false, results: [] })]).unverified).toBe(false);
  });

  it('the ladder: the confidence label as the tool wrote it, once each, and its own text search', () => {
    const t = askTags([
      use('p', 'get_place_answer'),
      result('p', { tier: 'verified', confidence: 'Checked rule file, verified on 2026-11-11.' }),
      use('q', 'get_place_answer'),
      result('q', { tier: 'text_search', confidence: "Unverified text search of the town's public zoning text. No verdict.", text_search: { label: LABEL, passages: [{ quote: 'y' }] } }),
      use('r', 'get_place_answer'),
      result('r', { tier: 'verified', confidence: 'Checked rule file, verified on 2026-11-11.' }),
    ]);
    expect(t.confidence).toEqual(['Checked rule file, verified on 2026-11-11.', "Unverified text search of the town's public zoning text. No verdict."]);
    expect(t.unverified).toBe(true);
  });

  it('other tools and broken results add nothing', () => {
    const t = askTags([use('a', 'get_lot_facts'), result('a', { confidence: 'x' }), { role: 'user', content: [{ type: 'tool_result', tool_use_id: 'z', content: 'not json' }] }, { role: 'user', content: 'plain question' }]);
    expect(t).toEqual({ unverified: false, confidence: [] });
  });
});

describe('what Ask shows around the answers (smoke test of Nov 16)', () => {
  it('a site with no assistant set up says so in plain words, never about keys or hosting', async () => {
    const { ASK_OFF, askReply } = await import('./askTags');
    const off = askReply({ ok: false, text: 'Agent not set up yet (needs ANTHROPIC_API_KEY on Vercel)', notConfigured: true });
    expect(off).toBe(ASK_OFF);
    expect(off).not.toMatch(/API|Vercel|Agent/);
    expect(askReply({ ok: false, text: 'The agent could not be reached. Try again in a moment.' })).toMatch(/could not be reached/);
    expect(askReply({ ok: true, text: 'Yes.' })).toBe('Yes.');
  });

  it('the context chip names the lot by its address, not its raw id', async () => {
    const { askWhere } = await import('./askTags');
    const tract = { NAMELSAD: 'Census Tract 2056' };
    expect(askWhere({ label: 'Linked lot', record: { lot: { id: '42091-120001072005', address: '119 N ESSEX AVE' } }, tract })).toBe('119 N Essex Ave');
    expect(askWhere({ label: 'Linked lot', record: { lot: { id: '42091-1', address: null } }, tract })).toBe('Lot 42091-1');
    expect(askWhere({ label: '12 Main St', record: { lot: { id: '42091-1', address: null } }, tract })).toBe('12 Main St');
    expect(askWhere({ tract })).toBe('Census Tract 2056');
    expect(askWhere(null)).toBe('No lot selected');
  });
});
