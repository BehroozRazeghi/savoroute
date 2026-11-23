import type { ReactNode, SVGProps } from 'react';

type Name = 'search' | 'arrow' | 'arrow-up-right' | 'menu' | 'close' | 'leaf' | 'info' | 'check' | 'utensils' | 'book' | 'chevron' | 'sliders';

type Props = SVGProps<SVGSVGElement> & { name: Name; size?: number };

const paths: Record<Name, ReactNode> = {
  search: <><circle cx="11" cy="11" r="7.5" /><path d="m16.5 16.5 5 5" /></>,
  arrow: <><path d="M4 12h16m-6-6 6 6-6 6" /></>,
  'arrow-up-right': <><path d="M5 19 19 5M8 5h11v11" /></>,
  menu: <><path d="M4 7h16M4 12h16M4 17h16" /></>,
  close: <><path d="m5 5 14 14M19 5 5 19" /></>,
  leaf: <><path d="M20 4C10 3 5 8 5 15c0 4 4 6 7 4 6-3 8-9 8-15Z" /><path d="M4 21c4-6 8-10 14-13" /></>,
  info: <><circle cx="12" cy="12" r="9" /><path d="M12 11v5m0-9v.5" /></>,
  check: <path d="m4 12 5 5L20 6" />,
  utensils: <><path d="M5 3v7a3 3 0 0 0 6 0V3M8 3v18M17 21V3c-4 3-4 10 0 10" /></>,
  book: <><path d="M12 6C9 4 5 4 2 5v15c4-1 7-1 10 1 3-2 6-2 10-1V5c-3-1-7-1-10 1Zm0 0v15" /></>,
  chevron: <path d="m6 9 6 6 6-6" />,
  sliders: <><path d="M4 7h16M4 17h16" /><circle cx="8" cy="7" r="2" fill="currentColor" stroke="none" /><circle cx="16" cy="17" r="2" fill="currentColor" stroke="none" /></>,
};

export function Icon({ name, size = 20, ...props }: Props) {
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true" {...props}>{paths[name]}</svg>;
}
