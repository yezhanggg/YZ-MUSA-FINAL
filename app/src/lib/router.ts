// Hash routes (#/tool, #/research/5500/results, #/about), so the static build works on any host, even
// `python -m http.server`, with no rewrite rules.
import { useSyncExternalStore } from 'react';

export type DocId = 'results' | 'methods' | 'data' | 'proposal';
export const DOC_IDS: DocId[] = ['results', 'methods', 'data', 'proposal'];
export type Course = '5500' | '6950';

export type Route =
  | { page: 'home' }
  | { page: 'tool' }
  | { page: 'research'; course: Course; doc: DocId; section?: string }
  | { page: 'about' };

export function parse(hash: string): Route {
  const [page, a, b, c] = hash.replace(/^#\/?/, '').split('/').filter(Boolean);
  if (page === 'tool') return { page: 'tool' };
  if (page === 'about') return { page: 'about' };
  if (page === 'research') {
    const course: Course = a === '6950' ? '6950' : '5500';
    const doc = (DOC_IDS as string[]).includes(b) ? (b as DocId) : 'results';
    return { page: 'research', course, doc, section: c };
  }
  return { page: 'home' };
}

export function href(r: Route): string {
  switch (r.page) {
    case 'home':
      return '#/';
    case 'tool':
      return '#/tool';
    case 'about':
      return '#/about';
    case 'research':
      return `#/research/${r.course}/${r.doc}${r.section ? `/${r.section}` : ''}`;
  }
}

const subscribe = (cb: () => void) => {
  window.addEventListener('hashchange', cb);
  return () => window.removeEventListener('hashchange', cb);
};

export function useRoute(): Route {
  return parse(useSyncExternalStore(subscribe, () => window.location.hash, () => ''));
}

/** The Quarto class version, copied into dist/quarto/ at build time. */
export const QUARTO_URL = '/quarto/';
export const GITHUB_URL = 'https://github.com/yezhanggg/YZ-MUSA-FINAL';
