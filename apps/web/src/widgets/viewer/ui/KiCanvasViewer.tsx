'use client';

import { useEffect, useRef, useState } from 'react';
import { Layers, RefreshCw, ZoomIn, ZoomOut, Move } from 'lucide-react';
import { loadKiCanvas } from '../lib/kicanvas-loader';

interface KiCanvasViewerProps {
  src: string;
  controls?: 'none' | 'basic' | 'full';
}

export function KiCanvasViewer({ src, controls = 'basic' }: KiCanvasViewerProps) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showHints, setShowHints] = useState(false);
  const hintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    let cancelled = false;
    setStatus('loading');
    setErrorMsg(null);
    setShowHints(false);

    loadKiCanvas()
      .then(() => {
        if (!cancelled) {
          setStatus('ready');
          // Show control hints after 1.5s, hide after 4s
          hintTimerRef.current = setTimeout(() => {
            if (!cancelled) {
              setShowHints(true);
              setTimeout(() => { if (!cancelled) setShowHints(false); }, 3500);
            }
          }, 1500);
        }
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setStatus('error');
        setErrorMsg(err instanceof Error ? err.message : 'KiCanvas load failed');
      });

    return () => {
      cancelled = true;
      if (hintTimerRef.current) clearTimeout(hintTimerRef.current);
    };
  }, [src]);

  const isExpiredUrl = errorMsg?.includes('400') || src.includes('token=');

  return (
    <div className="relative flex-1 min-h-0 bg-[#060606] overflow-hidden">

      {/* Loading state */}
      {status === 'loading' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-3 z-10">
          <div className="flex items-center gap-1.5">
            {[0, 1, 2].map((i) => (
              <span
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-primary/60 animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
          <span className="text-[11px] font-mono text-[#3d3d3d] tracking-wider">
            Loading KiCad viewer…
          </span>
        </div>
      )}

      {/* Error state */}
      {status === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 px-8 z-10">
          <div className="w-10 h-10 rounded-xl bg-[#1a0e0e] border border-destructive/20 flex items-center justify-center">
            <Layers size={16} className="text-destructive/70" />
          </div>
          <div className="text-center max-w-xs">
            <p className="text-xs font-semibold text-foreground/80 mb-1">
              {isExpiredUrl ? 'Signed URL expired' : 'KiCanvas failed to load'}
            </p>
            <p className="text-[11px] text-muted-foreground leading-relaxed">
              {isExpiredUrl
                ? 'The file access token has expired. Reload the project to regenerate a fresh link.'
                : errorMsg ?? 'Could not load the native KiCad renderer.'}
            </p>
          </div>
          {isExpiredUrl && (
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-[#111] border border-border text-xs text-muted-foreground hover:text-foreground hover:border-border/80 transition-colors"
            >
              <RefreshCw size={11} />
              Reload page
            </button>
          )}
        </div>
      )}

      {/* Native KiCanvas viewer */}
      {status === 'ready' && (
        <>
          <kicanvas-embed
            src={src}
            controls={controls}
            theme="kicad"
            style={{ width: '100%', height: '100%', display: 'block' }}
          />

          {/* File type badge */}
          <div className="absolute top-3 left-3 flex items-center gap-1.5 px-2 py-1 rounded-md bg-[#0a0a0a]/80 border border-[#1e1e1e] backdrop-blur-sm pointer-events-none">
            <Layers size={10} className="text-primary/60" />
            <span className="text-[10px] font-mono text-[#3d3d3d] tracking-wider">
              {src.includes('.kicad_sch') ? 'SCHEMATIC' : 'PCB LAYOUT'}
            </span>
          </div>

          {/* Control hints overlay — fades in then out */}
          {showHints && (
            <div
              className="absolute bottom-4 right-4 flex flex-col gap-1.5 pointer-events-none"
              style={{
                animation: 'fadeInOut 3.5s ease forwards',
              }}
            >
              {[
                { icon: <Move size={10} />, label: 'Drag to pan' },
                { icon: <ZoomIn size={10} />, label: 'Scroll to zoom' },
              ].map(({ icon, label }) => (
                <div
                  key={label}
                  className="flex items-center gap-1.5 px-2 py-1 rounded-md bg-[#0a0a0a]/80 border border-[#1e1e1e] backdrop-blur-sm"
                >
                  <span className="text-[#3d3d3d]">{icon}</span>
                  <span className="text-[10px] font-mono text-[#3d3d3d]">{label}</span>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      <style>{`
        @keyframes fadeInOut {
          0% { opacity: 0; transform: translateY(4px); }
          15% { opacity: 1; transform: translateY(0); }
          70% { opacity: 1; }
          100% { opacity: 0; }
        }
      `}</style>
    </div>
  );
}
