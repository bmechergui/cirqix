/**
 * Client HTTP de `POST /render/auto` du service KiCad (`kicad-cli pcb render`).
 *
 * Rend les octets PNG, ou lève `RenderServiceUnavailableError`. Jamais d'image
 * de remplacement : un rendu absent est un rendu absent.
 */

import { buildKicadServiceHeaders } from './kicad-service-auth';

const RENDER_TIMEOUT_MS = 120_000;

export class RenderServiceUnavailableError extends Error {
  constructor(message: string, public readonly cause?: unknown) {
    super(message);
    this.name = 'RenderServiceUnavailableError';
  }
}

export interface RealRenderInput {
  /** Le `.kicad_pcb`, texte. */
  kicadPcbContent: string;
  side: string;
  rotate: string | null;
  perspective: boolean;
  zoom: number;
  quality: 'basic' | 'high';
  width: number;
  height: number;
}

export async function runRealRender(input: RealRenderInput): Promise<Uint8Array> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) throw new RenderServiceUnavailableError('KICAD_SERVICE_URL not configured');
  const url = `${baseUrl.replace(/\/+$/, '')}/render/auto`;
  const { kicadPcbContent, ...options } = input;
  let reponse: Response;
  try {
    reponse = await fetch(url, {
      method: 'POST',
      headers: buildKicadServiceHeaders(),
      body: JSON.stringify({ kicad_pcb_b64: Buffer.from(kicadPcbContent, 'utf-8').toString('base64'), ...options }),
      signal: AbortSignal.timeout(RENDER_TIMEOUT_MS),
    });
  } catch (err) {
    throw new RenderServiceUnavailableError(`render request failed: ${err instanceof Error ? err.message : String(err)}`, err);
  }
  if (!reponse.ok) {
    let detail = `service responded ${reponse.status}`;
    try {
      const corps = (await reponse.json()) as { detail?: unknown };
      if (typeof corps.detail === 'string') detail = corps.detail;
    } catch {
      // corps non JSON
    }
    throw new RenderServiceUnavailableError(detail);
  }
  const corps = (await reponse.json()) as { png_b64?: unknown };
  if (typeof corps.png_b64 !== 'string' || corps.png_b64.length === 0) {
    throw new RenderServiceUnavailableError('service returned no image');
  }
  return new Uint8Array(Buffer.from(corps.png_b64, 'base64'));
}

/** `POST /export/glb` — le modèle 3D du board (glTF binaire), pour le viewer interactif. */
export async function runRealGlb(kicadPcbContent: string): Promise<Uint8Array> {
  const baseUrl = process.env['KICAD_SERVICE_URL'];
  if (!baseUrl) throw new RenderServiceUnavailableError('KICAD_SERVICE_URL not configured');
  const url = `${baseUrl.replace(/\/+$/, '')}/export/glb`;
  let reponse: Response;
  try {
    reponse = await fetch(url, {
      method: 'POST',
      headers: buildKicadServiceHeaders(),
      body: JSON.stringify({ kicad_pcb_b64: Buffer.from(kicadPcbContent, 'utf-8').toString('base64') }),
      signal: AbortSignal.timeout(RENDER_TIMEOUT_MS),
    });
  } catch (err) {
    throw new RenderServiceUnavailableError(`glb request failed: ${err instanceof Error ? err.message : String(err)}`, err);
  }
  if (!reponse.ok) {
    let detail = `service responded ${reponse.status}`;
    try {
      const corps = (await reponse.json()) as { detail?: unknown };
      if (typeof corps.detail === 'string') detail = corps.detail;
    } catch {
      // corps non JSON
    }
    throw new RenderServiceUnavailableError(detail);
  }
  const corps = (await reponse.json()) as { glb_b64?: unknown };
  if (typeof corps.glb_b64 !== 'string' || corps.glb_b64.length === 0) {
    throw new RenderServiceUnavailableError('service returned no model');
  }
  return new Uint8Array(Buffer.from(corps.glb_b64, 'base64'));
}
