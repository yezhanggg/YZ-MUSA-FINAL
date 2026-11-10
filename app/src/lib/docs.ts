// The research write-ups (musa5500/docs/*.md, musa6950/docs/*.md) are bundled at build time, so the markdown stays
// the single source of truth. Figures are bundled too, and their relative paths are mapped to the built files.
import { Marked, type Tokens } from 'marked';
import type { Course, DocId } from './router';

const RAW = import.meta.glob('../../../musa*/docs/*.md', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const FIGS = import.meta.glob('../../../musa*/docs/figures/*.{png,jpg,jpeg,svg}', { query: '?url', import: 'default', eager: true }) as Record<string, string>;

export interface TocItem {
  id: string;
  text: string;
  depth: 2 | 3;
}
export interface Doc {
  title: string;
  html: string;
  toc: TocItem[];
  words: number;
}

export const COURSES: Record<Course, { name: string; short: string; line: string }> = {
  '5500': { name: 'MUSA 5500', short: 'Demand and payoff', line: 'Where people and jobs are growing, where an ADU pays for itself, and how many could come by 2031.' },
  '6950': { name: 'MUSA 6950', short: 'Room on the lot', line: 'A U-Net on 2022 aerial images finds open ground and trees, then a 600 sq ft fit test runs on every lot.' },
};
export const DOC_LABEL: Record<DocId, string> = { results: 'Results', methods: 'Methods', data: 'Data', proposal: 'Proposal' };

/** Split off the Quarto front matter and read its title. */
function frontMatter(src: string): { title: string | null; body: string } {
  const m = /^---\s*\n([\s\S]*?)\n---\s*\n?/.exec(src);
  if (!m) return { title: null, body: src };
  const t = /^title:\s*["']?(.*?)["']?\s*$/m.exec(m[1]);
  return { title: t ? t[1] : null, body: src.slice(m[0].length) };
}

const slug = (s: string) =>
  s
    .toLowerCase()
    .replace(/<[^>]+>/g, '')
    .replace(/&[a-z]+;/g, '')
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');

const cache = new Map<string, Doc>();

export function getDoc(course: Course, doc: DocId): Doc | null {
  const key = `${course}/${doc}`;
  const hit = cache.get(key);
  if (hit) return hit;
  const path = Object.keys(RAW).find((p) => p.endsWith(`musa${course}/docs/${doc}.md`));
  if (!path) return null;
  const { title, body } = frontMatter(RAW[path]);

  const toc: TocItem[] = [];
  const seen = new Map<string, number>();
  const idFor = (text: string) => {
    const base = slug(text) || 'section';
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n ? `${base}-${n}` : base;
  };

  const figure = (href: string) => {
    const file = href.replace(/^\.?\/?/, '');
    const hitFig = Object.keys(FIGS).find((p) => p.endsWith(`musa${course}/docs/${file}`));
    return hitFig ? FIGS[hitFig] : href;
  };

  const md = new Marked({ gfm: true });
  md.use({
    renderer: {
      heading(this: { parser: { parseInline: (t: Tokens.Generic[]) => string } }, { tokens, depth }: Tokens.Heading) {
        const inner = this.parser.parseInline(tokens);
        const id = idFor(inner);
        if (depth === 2 || depth === 3) toc.push({ id, text: inner.replace(/<[^>]+>/g, ''), depth });
        return `<h${depth} id="${id}">${inner}</h${depth}>\n`;
      },
      image({ href, text }: Tokens.Image) {
        return `<figure><img src="${figure(href)}" alt="${text.replace(/"/g, '&quot;')}" loading="lazy" decoding="async"><figcaption>${text}</figcaption></figure>`;
      },
      link(this: { parser: { parseInline: (t: Tokens.Generic[]) => string } }, { href, tokens }: Tokens.Link) {
        const inner = this.parser.parseInline(tokens);
        const m = /^(?:\.\/)?([a-z]+)\.md(?:#(.*))?$/.exec(href);
        if (m) return `<a href="#/research/${course}/${m[1]}${m[2] ? `/${m[2]}` : ''}">${inner}</a>`;
        const ext = /^https?:/.test(href);
        return `<a href="${href}"${ext ? ' target="_blank" rel="noreferrer"' : ''}>${inner}</a>`;
      },
    },
  });

  let html = md.parse(body, { async: false }) as string;
  html = html
    .replace(/<p>\s*(<figure>[\s\S]*?<\/figure>)\s*<\/p>/g, '$1')
    .replace(/<table>/g, '<div class="table-wrap"><table>')
    .replace(/<\/table>/g, '</table></div>');

  const out: Doc = { title: title ?? `${COURSES[course].name} ${DOC_LABEL[doc]}`, html, toc, words: body.split(/\s+/).length };
  cache.set(key, out);
  return out;
}
