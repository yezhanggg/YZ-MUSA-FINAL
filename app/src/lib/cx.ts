import { clsx, type ClassValue } from 'clsx';
import { extendTailwindMerge } from 'tailwind-merge';

// The theme's own type sizes (index.css), so tailwind-merge does not mistake `text-caption` for a colour.
const twMerge = extendTailwindMerge({
  extend: { theme: { text: ['caption', 'small', 'body', 'lead', 'title', 'display'] } },
});

/** Join class names, letting later Tailwind classes win. */
export const cx = (...c: ClassValue[]) => twMerge(clsx(c));
