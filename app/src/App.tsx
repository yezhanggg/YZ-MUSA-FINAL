import { Suspense, lazy, useEffect } from 'react';
import { useRoute } from './lib/router';
import Landing from './pages/Landing';
import SiteNav from './components/SiteNav';
import Footer from './components/Footer';

// The map (MapLibre) and the docs (markdown) load only when their page opens, so the landing page stays light.
const ToolPage = lazy(() => import('./tool/ToolPage'));
const Research = lazy(() => import('./pages/Research'));
const About = lazy(() => import('./pages/About'));

const TITLES = { home: 'Backyard Homes PA', tool: 'Tool · Backyard Homes PA', research: 'Research · Backyard Homes PA', about: 'About · Backyard Homes PA' } as const;

function PageFallback() {
  return (
    <div className="grid min-h-[60vh] place-items-center">
      <span className="shimmer-text text-body font-medium">Loading…</span>
    </div>
  );
}

export default function App() {
  const route = useRoute();
  const key = route.page === 'research' ? `research-${route.course}-${route.doc}` : route.page;

  useEffect(() => {
    document.title = TITLES[route.page];
    if (!(route.page === 'research' && route.section)) window.scrollTo({ top: 0, behavior: 'instant' as ScrollBehavior });
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps

  if (route.page === 'tool') {
    return (
      <Suspense fallback={<div className="grid h-dvh place-items-center bg-[#eef0f2]"><span className="shimmer-text text-body font-medium">Loading the map…</span></div>}>
        <ToolPage />
      </Suspense>
    );
  }

  return (
    <div className="flex min-h-dvh flex-col">
      <SiteNav />
      <main className="flex-1">
        <Suspense fallback={<PageFallback />}>
          {route.page === 'home' && <Landing />}
          {route.page === 'research' && <Research course={route.course} doc={route.doc} section={route.section} />}
          {route.page === 'about' && <About />}
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
