import { Suspense, lazy, useEffect } from 'react';
import { AnimatePresence } from 'motion/react';
import { useResearch } from './lib/router';
import TopBar from './components/SiteNav';

// One shell: the tool fills the screen, the top bar stays on it, and Research opens as a panel over the map.
// The map (MapLibre) and the Research pages each load in their own chunk.
const ToolPage = lazy(() => import('./tool/ToolPage'));
const ResearchPanel = lazy(() => import('./pages/ResearchPanel'));

export default function App() {
  const research = useResearch();

  useEffect(() => {
    document.title = research ? `${research === '6950' ? 'Room on the lot' : 'Demand and payoff'} · Backyard Homes PA` : 'Backyard Homes PA';
  }, [research]);

  return (
    <div className="relative h-dvh w-full overflow-hidden bg-[#eef0f2]">
      <Suspense
        fallback={
          <div className="grid h-full place-items-center">
            <span className="shimmer-text text-body font-medium">Loading the map…</span>
          </div>
        }
      >
        <ToolPage />
      </Suspense>
      <Suspense fallback={null}>
        <AnimatePresence>{research && <ResearchPanel key="research" course={research} />}</AnimatePresence>
      </Suspense>
      <TopBar />
    </div>
  );
}
