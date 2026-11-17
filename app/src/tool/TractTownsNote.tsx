// Explore, the Allowed row of a tract: when the tract crosses a town line, say so and give each town's share of the
// homes (data/tract_towns.json, 2020 Census blocks). Zoning is set by each town, so the answer above is for the town
// where the map was clicked. Nothing shows for a tract inside one town.
import { useEffect, useState } from 'react';
import { tractTownsSource, type TractTowns } from '../agent/tractTowns';
import { loadPlaces, usePlaces } from './places';

const source = tractTownsSource();

/** "Lancaster township 80%, Lancaster city 20%". Shares under 1% are left out. */
export function townSplitText(list: [string, number, number][], name: (geoid: string) => string): string {
  return list
    .filter(([, h]) => h >= 0.01)
    .map(([g, h]) => `${name(g)} ${Math.round(h * 100)}%`)
    .join(', ');
}

export default function TractTownsNote({ tract, town }: { tract: string; town: string | null }) {
  const [tt, setTt] = useState<TractTowns | null>(null);
  const places = usePlaces((s) => s.places);
  useEffect(() => {
    let live = true;
    void loadPlaces();
    void source.get().then((v) => live && setTt(v));
    return () => {
      live = false;
    };
  }, []);
  const list = tt?.[tract]?.filter(([, h]) => h >= 0.01);
  if (!list || list.length < 2) return null;
  const name = (g: string) => places?.byGeoid.get(g)?.name ?? g;
  return (
    <p className="text-caption text-slate-500" data-tract-towns>
      This tract crosses a town line. Its homes: {townSplitText(list, name)}. Each town sets its own rule. This answer is for {town ?? 'the town'} where you clicked.
    </p>
  );
}
