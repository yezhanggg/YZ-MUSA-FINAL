import { AnimatePresence, motion } from 'motion/react';
import { Loader2, MousePointerClick } from 'lucide-react';
import { MapNav } from '../components/SiteNav';
import MapCanvas from './MapCanvas';
import LeftPanel from './LeftPanel';
import Report from './Report';
import MapControls from './MapControls';
import { useEffect } from 'react';
import { aduFromHash, useTool } from './store';

/** Full-screen map with floating panels: search and controls on the left, the report on the right. */
export default function ToolPage() {
  const status = useTool((s) => s.status);
  const hasSpot = useTool((s) => !!s.spot || s.busy);
  // A scenario link opened while the tool is already up (#/tool?bed=2&size=800&st=1)
  useEffect(() => {
    const on = () => window.location.hash.includes('?') && useTool.getState().set({ adu: aduFromHash(window.location.hash) });
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return (
    <div className="relative h-dvh w-full overflow-hidden bg-[#eef0f2]">
      <MapCanvas />
      <MapNav />
      <LeftPanel />
      <MapControls />
      <Report />
      <AnimatePresence>
        {(status === 'loading' || (status === 'ready' && !hasSpot)) && (
          <motion.div key={status} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }} transition={{ type: 'spring', stiffness: 400, damping: 30, delay: status === 'ready' ? 0.6 : 0 }} className="pointer-events-none absolute bottom-6 left-1/2 z-10 -translate-x-1/2 max-sm:bottom-4">
            <div className="flex items-center gap-2 whitespace-nowrap rounded-full bg-slate-900/90 px-4 py-2 text-small font-medium text-white shadow-lg backdrop-blur">
              {status === 'loading' ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" /> Loading 3,445 tracts and 2,572 towns…
                </>
              ) : (
                <>
                  <MousePointerClick className="h-4 w-4 text-violet-300" /> Click anywhere in Pennsylvania to test a spot
                </>
              )}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
