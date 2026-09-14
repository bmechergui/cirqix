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

/** Le défaut de KiCanvas, écrit par lui-même : ce n'est pas un choix de l'utilisateur. */
const KICANVAS_BUILTIN_DEFAULT_THEME = 'witchhazel';

export function ensureKiCanvasTheme(storage: Pick<Storage, 'getItem' | 'setItem'> | null | undefined = globalThis.localStorage): void {
  try {
    if (!storage) return;
    // ⚠️ « witchhazel » enregistré n'est PAS un choix : KiCanvas écrit son
    // défaut dès la première ouverture. Un navigateur qui avait ouvert le viewer
    // avant le 2026-09-13 gardait donc la carte ROSE malgré la préférence
    // posée « seulement si absente » (capture de l'utilisateur, 2026-09-14).
    // On remplace le défaut ; un autre thème choisi dans le panneau reste.
    const actuel = storage.getItem(KICANVAS_THEME_PREF_KEY);
    if (actuel !== null) {
      try {
        const val = (JSON.parse(actuel) as { val?: unknown }).val;
        if (typeof val === 'string' && val !== KICANVAS_BUILTIN_DEFAULT_THEME) return;
      } catch {
        // valeur illisible : on la remplace
      }
    }
    storage.setItem(KICANVAS_THEME_PREF_KEY, JSON.stringify({ val: KICANVAS_DEFAULT_THEME }));
  } catch {
    // stockage indisponible (navigation privée, politique) : KiCanvas gardera son défaut
  }
}

/**
 * Un board écrit par pcbnew 10 n'a AUCUNE table de nets : chaque objet porte
 * `(net "GND")` — le nom — là où KiCad ≤ 9 déclarait `(net 3 "GND")` en tête et
 * posait `(net 3)` sur les objets. KiCanvas ne connaît que cette seconde forme :
 * un clic sur une piste plantait la page entière (`getNetNumber: Cannot read
 * properties of undefined (reading 'number')`, rapporté le 2026-09-14) et le
 * panneau des nets restait vide.
 *
 * On reconstruit la table (0 = net vide, puis les noms triés) et on renumérote
 * les objets. Un board qui a déjà sa table est rendu tel quel : la fonction est
 * idempotente. `net_name` des zones n'est pas touché, KiCanvas le lit tel quel.
 */
const NET_NOMME_RE = /\(net "((?:[^"\\]|\\.)*)"\)/g;
const NET_DECLARE_RE = /\n\t\(net \d+ "/;
const PREMIER_OBJET_RE = /\n\t\((?:footprint|segment|arc|via|zone|gr_|dimension|target|group)/;

export function normaliserBoardPourKiCanvas(texte: string): string {
  if (!texte || NET_DECLARE_RE.test(texte)) return texte;
  const noms = new Set<string>();
  for (const m of texte.matchAll(NET_NOMME_RE)) noms.add(m[1] ?? '');
  if (noms.size === 0) return texte;
  noms.delete('');
  const table = new Map<string, number>([['', 0]]);
  for (const nom of Array.from(noms).sort()) table.set(nom, table.size);
  const renumerote = texte.replace(NET_NOMME_RE, (_tout, nom: string) => `(net ${table.get(nom) ?? 0})`);
  const declarations = Array.from(table.entries()).map(([nom, n]) => `\n\t(net ${n} "${nom}")`).join('');
  const m = PREMIER_OBJET_RE.exec(renumerote);
  if (!m) return renumerote + declarations;
  return renumerote.slice(0, m.index) + declarations + renumerote.slice(m.index);
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
