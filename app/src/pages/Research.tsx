import { useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion } from 'motion/react';
import { ArrowUpRight, BookOpen, ChevronDown, Clock, Coins, TreePine, X } from 'lucide-react';
import { COURSES, DOC_LABEL, getDoc, type TocItem } from '../lib/docs';
import { DOC_IDS, QUARTO_URL, href, type Course, type DocId } from '../lib/router';
import { cx } from '../lib/cx';
import { EASE_OUT, Eyebrow, SPRING_TAB, Tag } from '../components/primitives';

export default function Research({ course, doc, section }: { course: Course; doc: DocId; section?: string }) {
  const d = useMemo(() => getDoc(course, doc), [course, doc]);
  const articleRef = useRef<HTMLDivElement>(null);
  const [active, setActive] = useState<string | null>(null);
  const [zoom, setZoom] = useState<{ src: string; alt: string } | null>(null);

  // Deep link to a section (#/research/5500/results/<id>)
  useEffect(() => {
    if (!section) return;
    const t = setTimeout(() => document.getElementById(section)?.scrollIntoView({ block: 'start' }), 60);
    return () => clearTimeout(t);
  }, [section, course, doc]);

  // Scroll spy for the table of contents
  useEffect(() => {
    const root = articleRef.current;
    if (!root) return;
    const heads = Array.from(root.querySelectorAll<HTMLElement>('h2[id], h3[id]'));
    setActive(heads[0]?.id ?? null);
    const io = new IntersectionObserver(
      (entries) => {
        const vis = entries.filter((e) => e.isIntersecting).sort((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
        if (vis[0]) setActive(vis[0].target.id);
      },
      { rootMargin: '-80px 0px -70% 0px' },
    );
    heads.forEach((h) => io.observe(h));
    return () => io.disconnect();
  }, [d]);

  // Figures open in a lightbox
  useEffect(() => {
    const root = articleRef.current;
    if (!root) return;
    const onClick = (e: MouseEvent) => {
      const img = (e.target as HTMLElement).closest('figure img') as HTMLImageElement | null;
      if (img) setZoom({ src: img.src, alt: img.alt });
    };
    root.addEventListener('click', onClick);
    return () => root.removeEventListener('click', onClick);
  }, [d]);

  const jump = (id: string) => {
    document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
    history.replaceState(null, '', href({ page: 'research', course, doc, section: id }));
    setActive(id);
  };

  return (
    <div>
      {/* header */}
      <section className="relative isolate border-b border-stone-200/70">
        <div aria-hidden className="paper-dots absolute inset-0 -z-10 [mask-image:linear-gradient(to_bottom,black,transparent)]" />
        <div className="mx-auto max-w-7xl px-4 pb-8 pt-12 sm:px-6 sm:pt-16">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div>
              <Eyebrow>Research</Eyebrow>
              <h1 className="mt-3 font-display text-[36px] font-bold leading-tight tracking-tight text-slate-900 sm:text-[48px]">Methods and results</h1>
              <p className="mt-3 max-w-2xl text-lead text-slate-600">Two class projects, one tool. Every number in the tool traces back to these write-ups and the notebooks behind them.</p>
            </div>
            <a href={QUARTO_URL} className="inline-flex items-center gap-1.5 rounded-xl bg-white px-3.5 py-2 text-small font-semibold text-slate-700 ring-1 ring-stone-300 transition hover:text-violet-700 hover:ring-violet-300">
              <BookOpen className="h-4 w-4" /> Class version (Quarto) <ArrowUpRight className="h-3.5 w-3.5" />
            </a>
          </div>

          {/* course switch */}
          <div className="mt-8 grid gap-3 sm:grid-cols-2">
            {(['5500', '6950'] as Course[]).map((c) => {
              const on = c === course;
              const Icon = c === '5500' ? Coins : TreePine;
              return (
                <a key={c} href={href({ page: 'research', course: c, doc })} aria-current={on ? 'page' : undefined} className={cx('relative flex items-start gap-4 rounded-2xl p-4 text-left transition sm:p-5', on ? 'text-slate-900' : 'bg-white/60 text-slate-600 ring-1 ring-stone-200 hover:bg-white hover:ring-stone-300')}>
                  {on && <motion.span layoutId="course-card" className="absolute inset-0 rounded-2xl bg-white shadow-[0_14px_40px_-20px_rgba(76,29,149,0.45)] ring-2 ring-violet-500/70" transition={SPRING_TAB} />}
                  <span className={cx('relative grid h-10 w-10 shrink-0 place-items-center rounded-xl ring-1', on ? 'bg-violet-600 text-white ring-violet-700' : 'bg-stone-100 text-slate-500 ring-stone-200')}>
                    <Icon className="h-5 w-5" />
                  </span>
                  <span className="relative min-w-0">
                    <span className="flex items-center gap-2">
                      <span className="font-display text-lead font-bold text-slate-900">{COURSES[c].short}</span>
                      <Tag tone={on ? 'violet' : 'stone'}>{COURSES[c].name}</Tag>
                    </span>
                    <span className="mt-1 block text-small leading-snug text-slate-600">{COURSES[c].line}</span>
                  </span>
                </a>
              );
            })}
          </div>

          {/* doc tabs */}
          <nav aria-label="Documents" className="mt-6 flex w-fit max-w-full gap-1 overflow-x-auto rounded-xl bg-stone-100 p-1 ring-1 ring-stone-200/70">
            {DOC_IDS.map((id) => {
              const on = id === doc;
              return (
                <a key={id} href={href({ page: 'research', course, doc: id })} aria-current={on ? 'page' : undefined} className={cx('relative whitespace-nowrap rounded-lg px-4 py-1.5 text-body font-semibold transition-colors', on ? 'text-slate-900' : 'text-slate-600 hover:text-slate-900')}>
                  {on && <motion.span layoutId="doc-tab" className="absolute inset-0 rounded-lg bg-white shadow-sm ring-1 ring-black/5" transition={SPRING_TAB} />}
                  <span className="relative">{DOC_LABEL[id]}</span>
                </a>
              );
            })}
          </nav>
        </div>
      </section>

      {/* body */}
      <div className="mx-auto grid max-w-7xl gap-10 px-4 py-10 sm:px-6 lg:grid-cols-[240px_minmax(0,1fr)] lg:gap-14 lg:py-14">
        <aside className="lg:sticky lg:top-24 lg:max-h-[calc(100dvh-7rem)] lg:self-start">
          {d && <Toc items={d.toc} active={active} onJump={jump} words={d.words} />}
        </aside>
          <motion.article key={`${course}-${doc}`} initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.45, ease: EASE_OUT }} className="min-w-0 max-w-[780px]">
            {d ? (
              <>
                <div className="mb-8 flex flex-wrap items-center gap-2">
                  <Tag>{COURSES[course].name}</Tag>
                  <Tag tone="stone">{DOC_LABEL[doc]}</Tag>
                </div>
                <h2 className="font-display text-[30px] font-bold leading-tight tracking-tight text-slate-900 sm:text-[38px]">{d.title}</h2>
                <div ref={articleRef} className="prose-doc mt-8" dangerouslySetInnerHTML={{ __html: d.html }} />
                <DocPager course={course} doc={doc} />
              </>
            ) : (
              <p className="text-slate-600">This document is missing.</p>
            )}
          </motion.article>
      </div>

      <AnimatePresence>
        {zoom && (
          <motion.div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/70 p-4 backdrop-blur-sm sm:p-10" initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} onClick={() => setZoom(null)} role="dialog" aria-label={zoom.alt}>
            <motion.figure initial={{ scale: 0.94, y: 10 }} animate={{ scale: 1, y: 0 }} exit={{ scale: 0.96, opacity: 0 }} transition={{ type: 'spring', stiffness: 320, damping: 28 }} className="relative max-h-full max-w-6xl" onClick={(e) => e.stopPropagation()}>
              <img src={zoom.src} alt={zoom.alt} className="max-h-[82dvh] w-auto rounded-2xl bg-white object-contain shadow-2xl" />
              <figcaption className="mt-3 text-center text-small text-white/80">{zoom.alt}</figcaption>
              <button onClick={() => setZoom(null)} className="absolute -right-2 -top-2 grid h-9 w-9 place-items-center rounded-full bg-white text-slate-700 shadow-lg hover:text-slate-900" aria-label="Close">
                <X className="h-4 w-4" />
              </button>
            </motion.figure>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}

function Toc({ items, active, onJump, words }: { items: TocItem[]; active: string | null; onJump: (id: string) => void; words: number }) {
  const [open, setOpen] = useState(false);
  const list = (
    <ul className="space-y-0.5 border-l border-stone-200">
      {items.map((it) => {
        const on = it.id === active;
        return (
          <li key={it.id} className="relative">
            {on && <motion.span layoutId="toc-bar" className="absolute -left-px top-1 bottom-1 w-0.5 rounded-full bg-violet-600" transition={SPRING_TAB} />}
            <button onClick={() => { onJump(it.id); setOpen(false); }} className={cx('block w-full py-1 text-left text-small leading-snug transition-colors', it.depth === 3 ? 'pl-6' : 'pl-3.5', on ? 'font-semibold text-violet-800' : 'text-slate-600 hover:text-slate-900')}>
              {it.text}
            </button>
          </li>
        );
      })}
    </ul>
  );
  if (!items.length) return null;
  return (
    <>
      {/* phones and tablets: a fold */}
      <div className="lg:hidden">
        <button onClick={() => setOpen(!open)} className="flex w-full items-center justify-between rounded-xl bg-white px-4 py-3 text-small font-semibold text-slate-800 ring-1 ring-stone-200" aria-expanded={open}>
          On this page
          <ChevronDown className={cx('h-4 w-4 transition-transform', open && 'rotate-180')} />
        </button>
        <AnimatePresence initial={false}>
          {open && (
            <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: 'auto', opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
              <div className="pt-3">{list}</div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
      {/* desktop: sticky */}
      <div className="scroll-quiet hidden max-h-[calc(100dvh-7rem)] overflow-y-auto pr-2 lg:block">
        <div className="mb-3 flex items-center justify-between text-caption font-semibold uppercase tracking-[0.14em] text-slate-500">
          On this page
          <span className="inline-flex items-center gap-1 font-normal normal-case tracking-normal text-slate-400">
            <Clock className="h-3 w-3" /> {Math.max(1, Math.round(words / 230))} min
          </span>
        </div>
        {list}
      </div>
    </>
  );
}

function DocPager({ course, doc }: { course: Course; doc: DocId }) {
  const i = DOC_IDS.indexOf(doc);
  const next = DOC_IDS[i + 1];
  const other: Course = course === '5500' ? '6950' : '5500';
  return (
    <div className="mt-16 grid gap-3 border-t border-stone-200 pt-8 sm:grid-cols-2">
      {next ? (
        <a href={href({ page: 'research', course, doc: next })} className="group rounded-2xl bg-white p-5 ring-1 ring-stone-200 transition hover:ring-violet-300">
          <div className="text-caption text-slate-500">Next in {COURSES[course].name}</div>
          <div className="mt-1 font-display text-lead font-bold text-slate-900 group-hover:text-violet-700">{DOC_LABEL[next]} →</div>
        </a>
      ) : (
        <span />
      )}
      <a href={href({ page: 'research', course: other, doc: 'results' })} className="group rounded-2xl bg-white p-5 ring-1 ring-stone-200 transition hover:ring-violet-300 sm:text-right">
        <div className="text-caption text-slate-500">The other half · {COURSES[other].name}</div>
        <div className="mt-1 font-display text-lead font-bold text-slate-900 group-hover:text-violet-700">{COURSES[other].short} →</div>
      </a>
    </div>
  );
}
