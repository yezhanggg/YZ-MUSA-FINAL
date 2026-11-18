// The Ask function (api/agent.ts) runs on Vercel as Node ESM, which does not guess file extensions. Every relative
// import in its graph must name the file with .js (the compiled name of a .ts file) or .json, and a JSON import needs
// `with { type: 'json' }`. This walks the graph from api/agent.ts and fails on the first import that would not load.
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { describe, expect, it } from 'vitest';

const ENTRY = resolve(import.meta.dirname, '../api/agent.ts');

/** Static imports and re-exports (`import ... from '...'`, `export ... from '...'`, `import '...'`) and dynamic
 *  imports with a plain string. Type-only imports are left out: they are erased when the file is compiled. */
export function importsOf(src: string): { spec: string; json: boolean; stmt: string }[] {
  const out: { spec: string; json: boolean; stmt: string }[] = [];
  const stat = /^\s*(import|export)\s+(type\s+)?(?:[^'";]*?\sfrom\s+)?['"]([^'"]+)['"]([^;\n]*)/gm;
  for (const m of src.matchAll(stat)) if (!m[2]) out.push({ spec: m[3], json: /type:\s*['"]json['"]/.test(m[4]), stmt: m[0].trim() });
  const dyn = /\bimport\(\s*['"]([^'"]+)['"]\s*(,[^)]*)?\)/g;
  for (const m of src.matchAll(dyn)) out.push({ spec: m[1], json: /type:\s*['"]json['"]/.test(m[2] ?? ''), stmt: m[0] });
  return out;
}

function walk(entry: string) {
  const seen = new Set<string>();
  const bad: string[] = [];
  const todo = [entry];
  while (todo.length) {
    const file = todo.pop()!;
    if (seen.has(file)) continue;
    seen.add(file);
    for (const { spec, json, stmt } of importsOf(readFileSync(file, 'utf8'))) {
      if (!spec.startsWith('.')) continue;
      const where = `${file.replace(resolve(import.meta.dirname, '..') + '/', '')}: ${stmt}`;
      if (spec.endsWith('.json')) {
        if (!json) bad.push(`${where} (a JSON import needs with { type: 'json' })`);
        continue;
      }
      if (!spec.endsWith('.js')) {
        bad.push(`${where} (no .js extension)`);
        continue;
      }
      const base = resolve(dirname(file), spec.slice(0, -3));
      const next = [`${base}.ts`, `${base}.tsx`, `${base}.js`].find(existsSync);
      if (!next) bad.push(`${where} (file not found)`);
      else if (!next.endsWith('.js')) todo.push(next);
    }
  }
  return { seen, bad };
}

describe('the Ask function loads as Node ESM', () => {
  it('reads imports, type-only imports left out', () => {
    const src = "import a from './a.js';\nimport type { B } from './b';\nexport { c } from './c.js';\nimport d from '../d.json' with { type: 'json' };\nconst e = () => import('./e.js');";
    expect(importsOf(src).map((i) => [i.spec, i.json])).toEqual([['./a.js', false], ['./c.js', false], ['../d.json', true], ['./e.js', false]]);
  });

  it('every relative import in the api/agent.ts graph has an extension, and JSON has its attribute', () => {
    const { seen, bad } = walk(ENTRY);
    expect(seen.size).toBeGreaterThan(5);
    expect([...seen].some((f) => f.endsWith('methods.ts'))).toBe(true);
    expect(bad).toEqual([]);
  });
});
