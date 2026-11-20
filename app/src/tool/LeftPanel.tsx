import { motion } from 'motion/react';
import { PanelLeftClose, X } from 'lucide-react';
import { SPRING_PANEL } from '../components/primitives';
import { PANEL, PANEL_BODY, PanelHeader, IconButton } from '../components/Panel';
import { cx } from '../lib/cx';
import Search from './Search';
import { useTool } from './store';
import TestControls from './test/TestControls';
import { VIEW_LABEL } from '../lib/router';
import ExploreControls from './ProjectControls';

/**
 * The left panel: search and the lot at a glance in the header, the controls below. Same shell as the right panel.
 * Wide screens: fixed. Tablet and phone: a drawer from the left (`drawer`), closed with the button or Esc.
 */
export default function LeftPanel({ style, drawer, onClose, column }: { style?: React.CSSProperties; drawer?: boolean; onClose?: () => void; column?: boolean }) {
  const status = useTool((s) => s.status);
  const test = useTool((s) => s.view === 'test');
  return (
    <motion.aside
      initial={drawer ? { x: '-105%' } : { opacity: 0, x: -16, filter: 'blur(6px)' }}
      animate={drawer ? { x: 0 } : { opacity: 1, x: 0, filter: 'blur(0px)' }}
      exit={drawer ? { x: '-105%', transition: { duration: 0.2 } } : undefined}
      transition={{ ...SPRING_PANEL, delay: drawer ? 0 : 0.1 }}
      // column: desktop and laptop, inside the left column (flush with the top, the Test Site legend card below). There it is as
      // tall as what is open, up to the column's height, and scrolls inside past that.
      className={cx(PANEL, column ? 'relative min-h-0 shrink' : 'absolute z-30')}
      style={style}
      aria-label="Search and map controls"
    >
      {/* Tablet and phone: search under the title, in the header, outside the scrolling body, so its focus ring and the
          results list are never clipped. Desktop and laptop: one box for an address or a question at the bottom left
          (AskDock). */}
      <PanelHeader title={test ? VIEW_LABEL.test : VIEW_LABEL.project} actions={onClose ? drawer ? <IconButton label="Close controls" onClick={onClose}><X className="h-4 w-4" /></IconButton> : <IconButton label="Hide the controls" onClick={onClose}><PanelLeftClose className="h-4 w-4" /></IconButton> : undefined}>
        {drawer || status === 'error' ? (
          <>
            {drawer && <Search />}
            {status === 'error' && <p className="mt-2 text-small text-rose-700">The map data did not load. Refresh the page to try again.</p>}
          </>
        ) : null}
      </PanelHeader>
      <div className={PANEL_BODY}>
        {test ? (
          <TestControls />
        ) : (
          <ExploreControls />
        )}
      </div>
    </motion.aside>
  );
}
