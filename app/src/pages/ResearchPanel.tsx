// Research opens in a large panel over the map (a full-height sheet on phones). The map stays mounted behind it.
// Esc, the close button or a click on the dimmed map returns to the tool.
import { useEffect, useRef } from 'react';
import { motion } from 'motion/react';
import { X } from 'lucide-react';
import { openResearch, type Course } from '../lib/router';
import { SPRING_PANEL } from '../components/primitives';
import Research from './Research';

export default function ResearchPanel({ course }: { course: Course }) {
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const esc = (e: KeyboardEvent) => e.key === 'Escape' && openResearch(null);
    window.addEventListener('keydown', esc);
    return () => window.removeEventListener('keydown', esc);
  }, []);
  useEffect(() => scroller.current?.scrollTo({ top: 0 }), [course]);

  return (
    <>
      <motion.div key="research-backdrop" className="absolute inset-0 z-40 bg-slate-900/25 backdrop-blur-[2px]" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => openResearch(null)} aria-hidden />
      <motion.section
        key="research-panel"
        role="dialog"
        aria-modal="true"
        aria-label="Research"
        initial={{ opacity: 0, y: 24, scale: 0.98 }}
        animate={{ opacity: 1, y: 0, scale: 1 }}
        exit={{ opacity: 0, y: 16, scale: 0.98, transition: { duration: 0.18 } }}
        transition={SPRING_PANEL}
        className="absolute bottom-3 left-1/2 top-[4.25rem] z-40 flex w-[min(880px,calc(100%-1.5rem))] -translate-x-1/2 flex-col overflow-hidden rounded-2xl bg-[#fbfaf8] shadow-[0_30px_80px_-20px_rgba(15,23,42,0.45)] ring-1 ring-black/5 max-sm:inset-x-0 max-sm:bottom-0 max-sm:top-[3.75rem] max-sm:w-auto max-sm:translate-x-0 max-sm:rounded-b-none max-sm:rounded-t-3xl"
      >
        <button type="button" onClick={() => openResearch(null)} className="tap absolute right-3 top-3 z-10 grid h-9 w-9 place-items-center rounded-full bg-white text-slate-600 shadow-md ring-1 ring-black/10 transition hover:text-slate-900" aria-label="Close research and return to the map">
          <X className="h-4 w-4" />
        </button>
        <div ref={scroller} className="scroll-quiet min-h-0 flex-1 overflow-y-auto">
          <Research course={course} />
        </div>
      </motion.section>
    </>
  );
}
