import { Suspense, lazy, useEffect } from 'react';
import { useRoute } from './lib/router';
import SiteNav from './components/SiteNav';

// The site opens on the tool. The map (MapLibre) and the Research pages each load in their own chunk.
const ToolPage = lazy(() => import('./tool/ToolPage'));
const Research = lazy(() => import('./pages/Research'));

const Loading = ({ text, className }: { text: string; className: string }) => (
  <div className={`grid place-items-center ${className}`}>
    <span className="shimmer-text text-body font-medium">{text}</span>
  </div>
);

export default function App() {
  const route = useRoute();
  const key = route.page === 'research' ? `research-${route.course}` : 'tool';

  useEffect(() => {
    document.title = route.page === 'research' ? `${route.course === '6950' ? 'Room on the lot' : 'Demand and payoff'} · Backyard Homes PA` : 'Backyard Homes PA';
    window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (route.page === 'tool') {
    return (
      <Suspense fallback={<Loading text="Loading the map…" className="h-dvh bg-[#eef0f2]" />}>
        <ToolPage />
      </Suspense>
    );
  }

  return (
    <div className="min-h-dvh">
      <SiteNav />
      <main>
        <Suspense fallback={<Loading text="Loading…" className="min-h-[60vh]" />}>
          <Research course={route.course} />
        </Suspense>
      </main>
    </div>
  );
}
