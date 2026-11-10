import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** Join class names, letting later Tailwind classes win. */
export const cx = (...c: ClassValue[]) => twMerge(clsx(c));
