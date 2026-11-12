// One screen: the tool. Research opens as a panel over the map, kept in the hash query so links work:
// #/?research=6950 (older #/research/6950 links still open it). The ADU scenario shares the same query.
import { useSyncExternalStore } from 'react';

export type Course = '5500' | '6950';

const asCourse = (v: string | null | undefined): Course | null => (v === '5500' || v === '6950' ? v : null);

/** Which Research page is open, if any. */
export function researchOf(hash: string): Course | null {
  const [path, query] = hash.replace(/^#\/?/, '').split('?');
  const q = new URLSearchParams(query ?? '');
  if (q.has('research')) return asCourse(q.get('research'));
  const [page, course] = path.split('/').filter(Boolean);
  return page === 'research' ? (asCourse(course) ?? '6950') : null;
}

const subscribe = (cb: () => void) => {
  window.addEventListener('hashchange', cb);
  return () => window.removeEventListener('hashchange', cb);
};

export function useResearch(): Course | null {
  return researchOf(useSyncExternalStore(subscribe, () => window.location.hash, () => ''));
}

/** Open (or close, with null) a Research page, keeping the rest of the query. */
export function openResearch(course: Course | null) {
  const q = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  if (course) q.set('research', course);
  else q.delete('research');
  const s = q.toString();
  window.location.hash = s ? `#/?${s}` : '#/';
}

/** Which tool the top bar has picked: lot-level testing (default) or tract and town projections. */
export type ToolView = 'test' | 'project';
export const VIEW_LABEL: Record<ToolView, string> = {
  test: 'Test Project',
  project: 'Explore',
};

export const viewOf = (hash: string): ToolView => (new URLSearchParams(hash.split('?')[1] ?? '').get('view') === 'project' ? 'project' : 'test');

export function useView(): ToolView {
  return viewOf(useSyncExternalStore(subscribe, () => window.location.hash, () => ''));
}

/** Switch the tool. The tool page follows the hash (hashchange), the rest of the query is kept. */
export function openView(v: ToolView) {
  const q = new URLSearchParams(window.location.hash.split('?')[1] ?? '');
  q.set('view', v);
  q.delete('research'); // picking a mode also closes a Research page
  window.location.hash = `#/?${q.toString()}`;
}

/** The Quarto class version, copied into dist/quarto/ at build time. */
export const QUARTO_URL = '/quarto/';
