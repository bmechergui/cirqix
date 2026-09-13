const KICANVAS_CDN_URL = 'https://kicanvas.org/kicanvas/kicanvas.js';

let loadPromise: Promise<void> | null = null;

/**
 * Le thème que KiCanvas applique RÉELLEMENT en `controls="full"`.
 *
 * ⚠️ L'attribut `theme` de `<kicanvas-embed>` n'atteint pas le viewer dans ce
 * mode : `kc-board-app` ne le transmet pas à `kc-board-viewer`, qui retombe
 * sur `Preferences.INSTANCE.theme` — lu dans `localStorage` sous
 * `kc:prefs:theme`, au format `{"val": <nom>}`, défaut « witchhazel » (carte
 * rose). Vérifié dans le dashboard le 2026-09-13 : attribut `kicad` posé,
 * viewer toujours rose. On pose donc la préférence AVANT de charger le script,
 * sans écraser un choix fait dans le panneau de réglages de KiCanvas.
 */
export const KICANVAS_THEME_PREF_KEY = 'kc:prefs:theme';
export const KICANVAS_DEFAULT_THEME = 'kicad';

export function ensureKiCanvasTheme(storage: Pick<Storage, 'getItem' | 'setItem'> | null | undefined = globalThis.localStorage): void {
  try {
    if (!storage) return;
    if (storage.getItem(KICANVAS_THEME_PREF_KEY) !== null) return;
    storage.setItem(KICANVAS_THEME_PREF_KEY, JSON.stringify({ val: KICANVAS_DEFAULT_THEME }));
  } catch {
    // stockage indisponible (navigation privée, politique) : KiCanvas gardera son défaut
  }
}

export function loadKiCanvas(): Promise<void> {
  if (typeof window === 'undefined') {
    return Promise.reject(new Error('KiCanvas requires a browser environment'));
  }
  ensureKiCanvasTheme();
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
