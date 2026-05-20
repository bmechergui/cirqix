const KICANVAS_CDN_URL = 'https://kicanvas.org/kicanvas/kicanvas.js';

let loadPromise: Promise<void> | null = null;

export function loadKiCanvas(): Promise<void> {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('KiCanvas requires a browser environment'));
  }
  if (window.customElements?.get('kicanvas-embed')) {
    return Promise.resolve();
  }
  if (loadPromise) return loadPromise;

  loadPromise = new Promise<void>((resolve, reject) => {
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${KICANVAS_CDN_URL}"]`);
    if (existing) {
      existing.addEventListener(
        'load',
        () => { customElements.whenDefined('kicanvas-embed').then(() => resolve(), () => resolve()); },
        { once: true },
      );
      existing.addEventListener(
        'error',
        () => reject(new Error('Failed to load KiCanvas script')),
        { once: true },
      );
      return;
    }
    const script = document.createElement('script');
    script.src = KICANVAS_CDN_URL;
    script.type = 'module';
    script.async = true;
    script.addEventListener(
      'load',
      () => {
        // KiCanvas registers its custom element asynchronously (WASM init).
        // Wait until the element is actually defined before resolving.
        customElements.whenDefined('kicanvas-embed').then(() => resolve(), () => resolve());
      },
      { once: true },
    );
    script.addEventListener(
      'error',
      () => {
        loadPromise = null;
        reject(new Error('Failed to load KiCanvas script'));
      },
      { once: true }
    );
    document.head.appendChild(script);
  });

  return loadPromise;
}
