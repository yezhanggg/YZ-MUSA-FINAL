// Hash routes, so the static build works on any host with no rewrite rules.
// #/ and #/tool open the tool. #/research/6950 and #/research/5500 open the two Research pages.
import { useSyncExternalStore } from 'react';

export type Course = '5500' | '6950';
export type Route = { page: 'tool' } | { page: 'research'; course: Course };

export function parse(hash: string): Route {
  const [page, course] = hash.replace(/^#\/?/, '').split('?')[0].split('/').filter(Boolean);
  if (page === 'research') return { page: 'research', course: course === '5500' ? '5500' : '6950' };
  return { page: 'tool' };
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
