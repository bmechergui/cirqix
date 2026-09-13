import pino from 'pino';
import { runRealRender } from '../engines/render-service';
import { PRERENDUS, OPTIONS_PRERENDUS, cleDeRendu } from './render-cache';
import type { PipelineStore } from './store';

const log = pino({ name: 'cirqix.agents.prerendus', level: process.env['LOG_LEVEL'] ?? 'info' });

/**
 * Pré-rend les vues de `PRERENDUS` sur le board LIVRÉ et les dépose sous leur
 * clé de cache. Best-effort de bout en bout : un rendu raté ne touche ni au
 * statut du run, ni à son débit — le viewer rendra à la demande.
 *
 * Rend le nombre de rendus déposés (pour les journaux et les gardes).
 */
export async function prerendre(store: PipelineStore, kicadPcbContent: string): Promise<number> {
  if (!store.uploadRender) return 0;
  const board = new Uint8Array(Buffer.from(kicadPcbContent, 'utf-8'));
  let deposes = 0;
  for (const params of PRERENDUS) {
    const options = OPTIONS_PRERENDUS[params.view];
    if (!options) continue;
    const cle = cleDeRendu(board, params);
    try {
      const png = await runRealRender({
        kicadPcbContent,
        side: options.side, rotate: options.rotate, perspective: options.perspective,
        zoom: params.zoom, quality: params.quality, width: params.width, height: params.height,
      });
      await store.uploadRender(cle, png);
      deposes += 1;
    } catch (err) {
      log.warn({ err, view: params.view }, 'pré-rendu échoué — le viewer rendra à la demande');
    }
  }
  return deposes;
}
