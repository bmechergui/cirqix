import type { DetailedHTMLProps, HTMLAttributes } from 'react';

declare global {
  namespace JSX {
    interface IntrinsicElements {
      'kicanvas-embed': DetailedHTMLProps<
        HTMLAttributes<HTMLElement> & {
          src?: string;
          controls?: 'none' | 'basic' | 'full';
          controlslist?: string;
          theme?: 'kicad' | 'witchhazel';
          zoom?: string;
        },
        HTMLElement
      >;
      'kicanvas-source': DetailedHTMLProps<
        HTMLAttributes<HTMLElement> & { src?: string; name?: string; type?: string },
        HTMLElement
      >;
    }
  }
}

export {};
