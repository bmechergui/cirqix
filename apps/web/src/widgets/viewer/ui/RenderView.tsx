'use client';

import { useEffect, useMemo, useState } from 'react';
import { RotateCcw, RotateCw, Sparkles, RefreshCw, ExternalLink, Undo2, Loader2, ImageOff } from 'lucide-react';
import {
  RENDER_PRESETS,
  viewsOfFamily,
  renderQueryString,
  type RenderFamily,
  type RenderView as RenderViewName,
  type RenderQuality,
} from '@/shared/lib/render-presets';
import { cn } from '@/shared/lib/utils';

/**
 * Le rendu de KiCad, affiché directement : PNG (top / bottom) ou 3D (iso,
 * front, back, left, right, avec rotation). L'image vient de
 * `GET /api/projects/[id]/render` — rien n'est dessiné ici.
 *
 * Mesuré le 2026-09-13 sur 8 composants (1200×800) : basic top ≈ 6 s,
 * high iso ≈ 14 s. La qualité de base est donc le défaut ; « HD » est un
 * choix explicite.
 */

export interface RenderViewProps {
  projectId: string;
  family: RenderFamily;
  /** Change quand le board change (itération du pipeline) : invalide le cache navigateur. */
  version?: number | string | undefined;
}

const YAW_STEP = 30;

export function renderUrl(
  projectId: string,
  params: { view: RenderViewName; quality: RenderQuality; yaw: number },
  extra: { version?: number | string | undefined; attempt?: number } = {},
): string {
  const q = new URLSearchParams(renderQueryString(params));
  if (extra.version !== undefined) q.set('v', String(extra.version));
  if (extra.attempt) q.set('r', String(extra.attempt));
  return `/api/projects/${encodeURIComponent(projectId)}/render?${q.toString()}`;
}

type Status = { kind: 'loading' } | { kind: 'ready'; objectUrl: string; durationMs: number | null } | { kind: 'error'; message: string };

async function messageDErreur(r: Response): Promise<string> {
  try {
    const corps = (await r.json()) as { error?: unknown };
    if (typeof corps.error === 'string' && corps.error) return corps.error;
  } catch {
    // pas de JSON
  }
  return `Render failed (${r.status})`;
}

export function RenderView({ projectId, family, version }: RenderViewProps) {
  const views = useMemo(() => viewsOfFamily(family), [family]);
  const [view, setView] = useState<RenderViewName>(views[0] ?? 'top');
  const [quality, setQuality] = useState<RenderQuality>('basic');
  const [yaw, setYaw] = useState(0);
  const [attempt, setAttempt] = useState(0);
  const [status, setStatus] = useState<Status>({ kind: 'loading' });

  // Un changement de famille (PNG ↔ 3D) repart sur sa première vue.
  useEffect(() => {
    setView(views[0] ?? 'top');
    setYaw(0);
  }, [views]);

  const url = renderUrl(projectId, { view, quality, yaw }, { version, attempt });

  useEffect(() => {
    const controller = new AbortController();
    let objectUrl: string | null = null;
    // ⚠️ Une bascule rapide (vue, rotation, HD) démonte cet effet pendant que le
    // fetch précédent aboutit encore : sans ce drapeau, l'URL blob créée APRÈS
    // le nettoyage n'était jamais révoquée (revue du 2026-09-13).
    let cancelled = false;
    setStatus({ kind: 'loading' });
    (async () => {
      try {
        const r = await fetch(url, { signal: controller.signal, headers: { Accept: 'image/png' } });
        if (cancelled) return;
        if (!r.ok) {
          const message = await messageDErreur(r);
          if (!cancelled) setStatus({ kind: 'error', message });
          return;
        }
        const blob = await r.blob();
        if (cancelled) return;
        objectUrl = URL.createObjectURL(blob);
        const duree = Number(r.headers.get('x-render-duration-ms'));
        setStatus({ kind: 'ready', objectUrl, durationMs: Number.isFinite(duree) && duree >= 0 ? duree : null });
      } catch (err) {
        if (cancelled || controller.signal.aborted) return;
        setStatus({ kind: 'error', message: err instanceof Error ? err.message : 'Render request failed' });
      }
    })();
    return () => {
      cancelled = true;
      controller.abort();
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [url]);

  const is3d = family === '3d';

  return (
    <div className="relative flex-1 min-h-0 flex flex-col bg-[#060606] overflow-hidden" data-testid="render-view">
      {/* Barre de vues */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-[#1a1a1a] bg-[#0a0a0a]">
        <div className="flex items-center gap-0.5 bg-[#111] rounded-lg p-0.5 border border-[#1e1e1e]">
          {views.map((v) => (
            <button
              key={v}
              type="button"
              onClick={() => setView(v)}
              aria-pressed={view === v}
              className={cn(
                'px-2.5 py-1 rounded-md text-[10px] font-medium transition-all',
                view === v ? 'bg-[#1a2a14] text-[#8be05a] border border-[#3f7a2a]/40' : 'text-[#555] hover:text-[#888] hover:bg-[#161616] border border-transparent',
              )}
            >
              {RENDER_PRESETS[v].label}
            </button>
          ))}
        </div>

        {is3d && (
          <div className="flex items-center gap-0.5 bg-[#111] rounded-lg p-0.5 border border-[#1e1e1e]">
            <button type="button" onClick={() => setYaw((y) => y - YAW_STEP)} title={`Rotate −${YAW_STEP}°`} aria-label="Rotate left"
              className="p-1.5 rounded-md text-[#555] hover:text-[#888] hover:bg-[#161616]"><RotateCcw size={12} /></button>
            <span className="px-1.5 text-[10px] font-mono text-[#666] tabular-nums min-w-[3.5rem] text-center">{yaw}°</span>
            <button type="button" onClick={() => setYaw((y) => y + YAW_STEP)} title={`Rotate +${YAW_STEP}°`} aria-label="Rotate right"
              className="p-1.5 rounded-md text-[#555] hover:text-[#888] hover:bg-[#161616]"><RotateCw size={12} /></button>
            {yaw !== 0 && (
              <button type="button" onClick={() => setYaw(0)} title="Reset rotation" aria-label="Reset rotation"
                className="p-1.5 rounded-md text-[#555] hover:text-[#888] hover:bg-[#161616]"><Undo2 size={12} /></button>
            )}
          </div>
        )}

        <button
          type="button"
          onClick={() => setQuality((q) => (q === 'high' ? 'basic' : 'high'))}
          aria-pressed={quality === 'high'}
          title={quality === 'high' ? 'High quality (raytraced, slower)' : 'Switch to high quality (slower)'}
          className={cn(
            'flex items-center gap-1 px-2 py-1 rounded-md text-[10px] font-medium border transition-all',
            quality === 'high' ? 'bg-primary/10 text-primary border-primary/30' : 'text-[#555] border-[#1e1e1e] hover:text-[#888]',
          )}
        >
          <Sparkles size={10} /> HD
        </button>

        <div className="ml-auto flex items-center gap-2">
          {status.kind === 'ready' && status.durationMs !== null && (
            <span className="text-[10px] font-mono text-[#3d3d3d]">{(status.durationMs / 1000).toFixed(1)} s</span>
          )}
          <a
            href={url}
            target="_blank"
            rel="noreferrer"
            title="Open the PNG in a new tab"
            className="flex items-center gap-1 px-2 py-1 rounded-md text-[10px] text-[#555] border border-[#1e1e1e] hover:text-[#888]"
          >
            <ExternalLink size={10} /> Open
          </a>
        </div>
      </div>

      {/* L'image */}
      <div className="relative flex-1 min-h-0 flex items-center justify-center p-3">
        {status.kind === 'ready' && (
          // eslint-disable-next-line @next/next/no-img-element -- blob: URL d'un rendu authentifié, hors optimiseur Next
          <img
            src={status.objectUrl}
            alt={`KiCad render — ${RENDER_PRESETS[view].label}`}
            className="max-w-full max-h-full object-contain rounded-md shadow-2xl"
            data-testid="render-image"
          />
        )}
        {status.kind === 'loading' && (
          <div className="flex flex-col items-center gap-3" role="status">
            <Loader2 size={18} className="animate-spin text-primary/60" />
            <span className="text-[11px] font-mono text-[#3d3d3d] tracking-wider">
              {quality === 'high' ? 'Raytracing with KiCad…' : 'Rendering with KiCad…'}
            </span>
          </div>
        )}
        {status.kind === 'error' && (
          <div className="flex flex-col items-center gap-3 px-8 text-center" role="alert">
            <div className="w-10 h-10 rounded-xl bg-[#1a0e0e] border border-destructive/20 flex items-center justify-center">
              <ImageOff size={16} className="text-destructive/70" />
            </div>
            <p className="text-xs font-semibold text-foreground/80">Render unavailable</p>
            <p className="text-[11px] text-muted-foreground leading-relaxed max-w-sm">{status.message}</p>
            <button
              type="button"
              onClick={() => setAttempt((a) => a + 1)}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#111] border border-border text-xs text-muted-foreground hover:text-foreground"
            >
              <RefreshCw size={11} /> Retry
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
