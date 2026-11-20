// Desktop and laptop, bottom left: one box for an address or a question (Search, dock mode), and ParcelIQ joined on
// top of it once the box is clicked. ParcelIQ reaches up to just under the Controls panel and follows it as cards open
// and close; with the panel hidden it reaches up to under the panel's show button. Its right edge drags the width
// (remembered, useChatSize); the box takes the same width. While an address is typed, ParcelIQ steps aside for the
// address list.
import { useEffect, useState } from 'react';
import { AnimatePresence } from 'motion/react';
import ParcelIQ from './ParcelIQ';
import Search from './Search';
import { CHAT_H_MIN, CHAT_W_MIN, GUTTER, PANEL_TOP, useChatOpen, useChatSize, useSides } from './layout';

/** The box's height (h-12). */
export const DOCK_BAR_H = 48;
/** The panel's "Controls" show button when the panel is hidden (h-11). */
const SHOW_BTN_H = 44;

/** The bottom edge of the Controls panel on screen, kept current as it grows, shrinks or hides. */
function useControlsBottom(): number {
  const leftOpen = useSides((s) => s.left);
  const [bottom, setBottom] = useState(PANEL_TOP + SHOW_BTN_H);
  useEffect(() => {
    if (!leftOpen) return void setBottom(GUTTER + SHOW_BTN_H);
    let el: Element | null = null;
    const read = () => el && setBottom(Math.round(el.getBoundingClientRect().bottom));
    const ro = new ResizeObserver(read);
    // The panel mounts with its slide-in: find it once it is there.
    let t = 0;
    const find = () => {
      el = document.querySelector('aside[aria-label="Search and map controls"]');
      if (el) {
        ro.observe(el);
        read();
      } else t = window.setTimeout(find, 100);
    };
    t = window.setTimeout(find, 0);
    window.addEventListener('resize', read);
    // The slide-in moves the panel without resizing it: read again when it has settled.
    const settle = window.setTimeout(read, 700);
    return () => {
      window.clearTimeout(t);
      window.clearTimeout(settle);
      ro.disconnect();
      window.removeEventListener('resize', read);
    };
  }, [leftOpen]);
  return bottom;
}

export default function AskDock({ maxW, vh }: { maxW: number; vh: number }) {
  const open = useChatOpen((s) => s.open && !s.hidden);
  const w = useChatSize((s) => s.w);
  const setSize = useChatSize((s) => s.setSize);
  const top = useControlsBottom() + GUTTER;
  const width = Math.round(Math.min(Math.max(CHAT_W_MIN, maxW), Math.max(CHAT_W_MIN, w)));
  // From under the Controls panel down to the box. When the panel leaves too little room, ParcelIQ keeps a usable
  // height and lies over the panel's lower part.
  const height = Math.max(CHAT_H_MIN, vh - GUTTER - DOCK_BAR_H - top);
  return (
    <div className="pointer-events-none absolute z-40 flex flex-col justify-end [&>*]:pointer-events-auto" style={{ left: GUTTER, bottom: GUTTER, width }} data-ask-dock>
      <AnimatePresence>
        {open && (
          <ParcelIQ
            key="parceliq"
            style={{ height }}
            onClose={() => useChatOpen.getState().setOpen(false)}
            resize={{ width, height, minW: CHAT_W_MIN, maxW: Math.max(CHAT_W_MIN, maxW), minH: height, maxH: height, onSize: setSize }}
          />
        )}
      </AnimatePresence>
      <Search dock joined={open} />
    </div>
  );
}
