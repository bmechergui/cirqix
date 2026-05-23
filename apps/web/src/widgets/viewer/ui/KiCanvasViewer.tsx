'use client';

import { useEffect, useRef, useState, useCallback } from 'react';
import { Layers, RefreshCw, ZoomIn, ZoomOut, Move, Hand, MousePointer, Maximize } from 'lucide-react';
import { loadKiCanvas } from '../lib/kicanvas-loader';

interface KiCanvasViewerProps {
  src: string;
  zoom?: string;
}

type KiViewer = { zoom_to_board?: () => void; zoom_to_page?: () => void };

function findKiCanvasViewer(el: Element): KiViewer | null {
  const shadow = (el as HTMLElement).shadowRoot;
  if (!shadow) return null;
  for (const tag of ['kc-board-viewer', 'kc-schematic-viewer']) {
    const ve = shadow.querySelector(tag) as (HTMLElement & { viewer?: KiViewer }) | null;
    if (ve?.viewer) return ve.viewer;
  }
  for (const d of Array.from(shadow.querySelectorAll('*'))) {
    const found = findKiCanvasViewer(d);
    if (found) return found;
  }
  return null;
}

function findCanvasInShadow(el: Element): HTMLCanvasElement | null {
  const shadow = (el as HTMLElement).shadowRoot;
  if (!shadow) return null;
  const direct = shadow.querySelector('canvas');
  if (direct) return direct as HTMLCanvasElement;
  // Recurse into shadow roots of ALL descendants (not just direct children)
  for (const descendant of Array.from(shadow.querySelectorAll('*'))) {
    const found = findCanvasInShadow(descendant);
    if (found) return found;
  }
  return null;
}

function getScrollParent(node: HTMLElement | null): HTMLElement | null {
  if (node == null) return null;
  if (node.scrollHeight > node.clientHeight) {
    const overflowY = window.getComputedStyle(node).overflowY;
    if (overflowY === 'auto' || overflowY === 'scroll') {
      return node;
    }
  }
  return getScrollParent(node.parentElement);
}

function dispatchSimulatedPointerEvent(
  target: EventTarget,
  type: string,
  original: PointerEvent,
  override: { button?: number; buttons?: number }
) {
  const init: PointerEventInit = {
    bubbles: true,
    cancelable: true,
    composed: true,
    pointerId: original.pointerId,
    width: original.width,
    height: original.height,
    pressure: original.pressure,
    tangentialPressure: original.tangentialPressure,
    tiltX: original.tiltX,
    tiltY: original.tiltY,
    twist: original.twist,
    pointerType: original.pointerType,
    isPrimary: original.isPrimary,
    screenX: original.screenX,
    screenY: original.screenY,
    clientX: original.clientX,
    clientY: original.clientY,
    ctrlKey: original.ctrlKey,
    shiftKey: original.shiftKey,
    altKey: original.altKey,
    metaKey: original.metaKey,
    button: override.button !== undefined ? override.button : original.button,
    buttons: override.buttons !== undefined ? override.buttons : original.buttons,
  };

  const simPointerEvent = new PointerEvent(type, init);
  target.dispatchEvent(simPointerEvent);

  let mouseType = '';
  if (type === 'pointerdown') mouseType = 'mousedown';
  else if (type === 'pointermove') mouseType = 'mousemove';
  else if (type === 'pointerup') mouseType = 'mouseup';

  if (mouseType) {
    const simMouseEvent = new MouseEvent(mouseType, init);
    target.dispatchEvent(simMouseEvent);
  }
}

export function KiCanvasViewer({ src, zoom = 'objects' }: KiCanvasViewerProps) {
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [showHints, setShowHints] = useState(false);
  const [isPanMode, setIsPanMode] = useState(false);
  const hintTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const retryCountRef = useRef(0);
  const embedRef = useRef<HTMLElement | null>(null);

  const dispatchZoomWheel = useCallback((deltaY: number) => {
    const el = embedRef.current;
    if (!el) return;
    const canvas = findCanvasInShadow(el) ?? el;
    const rect = canvas.getBoundingClientRect();
    canvas.dispatchEvent(new WheelEvent('wheel', {
      clientX: rect.left + rect.width / 2,
      clientY: rect.top + rect.height / 2,
      deltaY,
      ctrlKey: true,
      bubbles: true,
      cancelable: true,
      composed: true,
    }));
  }, []);

  const handleZoomIn = useCallback(() => dispatchZoomWheel(-120), [dispatchZoomWheel]);
  const handleZoomOut = useCallback(() => dispatchZoomWheel(120), [dispatchZoomWheel]);

  const handleZoomToFit = useCallback(() => {
    const el = embedRef.current;
    if (!el) return;
    const viewer = findKiCanvasViewer(el);
    if (viewer) {
      viewer.zoom_to_board?.() ?? viewer.zoom_to_page?.();
    }
  }, []);

  const startHints = useCallback((cancelled: () => boolean) => {
    hintTimerRef.current = setTimeout(() => {
      if (!cancelled()) {
        setShowHints(true);
        setTimeout(() => { if (!cancelled()) setShowHints(false); }, 3500);
      }
    }, 1500);
  }, []);

  useEffect(() => {
    let cancelled = false;
    retryCountRef.current = 0;
    setStatus('loading');
    setErrorMsg(null);
    setShowHints(false);

    loadKiCanvas()
      .then(() => {
        if (!cancelled) {
          setStatus('ready');
          startHints(() => cancelled);
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
  }, [src, startHints]);

  // Listen for errors emitted by the <kicanvas-embed> web component.
  // Supabase Storage has brief eventual-consistency delay after upload:
  // auto-retry once after 2s before showing the error state.
  useEffect(() => {
    const el = embedRef.current;
    if (!el || status !== 'ready') return;

    const handleError = (e: Event) => {
      const msg = (e as CustomEvent<string>).detail ?? 'KiCanvas file load error';
      if (retryCountRef.current < 1) {
        retryCountRef.current += 1;
        // Brief delay to let Supabase Storage propagate the uploaded file
        setTimeout(() => {
          if (embedRef.current) {
            embedRef.current.removeAttribute('src');
            embedRef.current.setAttribute('src', src);
          }
        }, 2000);
      } else {
        setStatus('error');
        setErrorMsg(String(msg));
      }
    };

    el.addEventListener('error', handleError);
    return () => el.removeEventListener('error', handleError);
  }, [status, src]);

  // Synchronize custom elements attributes manually because React 18
  // does not always map JSX properties to DOM attributes for custom elements.
  useEffect(() => {
    const el = embedRef.current;
    if (!el || status !== 'ready') return;

    el.setAttribute('zoom', zoom);
  }, [zoom, status]);

  // Zoom & Pan, custom cursors, and zoom=objects re-application
  useEffect(() => {
    const el = embedRef.current;
    if (!el || status !== 'ready') return;

    // Set cursor on host element
    el.style.cursor = isPanMode ? 'grab' : 'default';

    // 1. Inject cursor styles into shadowRoot to inherit host cursor
    const injectCursorStyles = () => {
      const shadow = el.shadowRoot;
      if (shadow) {
        if (!shadow.querySelector('#kicanvas-custom-cursor-style')) {
          const style = document.createElement('style');
          style.id = 'kicanvas-custom-cursor-style';
          style.textContent = `
            canvas, div, .canvas-container, :host {
              cursor: inherit !important;
            }
          `;
          shadow.appendChild(style);
        }
      }
    };

    injectCursorStyles();
    const observer = new MutationObserver(() => injectCursorStyles());
    observer.observe(el, { childList: true, subtree: true });

    // 2. Wheel Zoom Event Handler (Ctrl+Wheel to zoom, regular scroll to scroll page)
    const handleWheel = (e: WheelEvent) => {
      if (e.ctrlKey) {
        e.preventDefault(); // Stop browser page zoom
      } else {
        e.stopPropagation(); // Stop KiCanvas zoom
        const parent = getScrollParent(el);
        if (parent) {
          parent.scrollBy({ left: e.deltaX, top: e.deltaY, behavior: 'auto' });
        } else {
          window.scrollBy({ left: e.deltaX, top: e.deltaY, behavior: 'auto' });
        }
      }
    };

    el.addEventListener('wheel', handleWheel, { capture: true, passive: false });

    // 3. Pointer event mapping (Left drag -> Middle click pan)
    const target = el.shadowRoot ?? el;
    const getInnerTarget = () => findCanvasInShadow(el) ?? target;
    let isPending = false;
    let isDragging = false;
    let startX = 0;
    let startY = 0;
    let pendingEvent: PointerEvent | null = null;
    let isSimulating = false;

    const handlePointerDown = (e: PointerEvent) => {
      if (!isPanMode || isSimulating || e.button !== 0) return;
      isPending = true;
      isDragging = false;
      startX = e.clientX;
      startY = e.clientY;
      pendingEvent = e;
      // Do not stopPropagation here. We must let the first click reach the overlay so it activates!
    };

    const handlePointerMove = (e: PointerEvent) => {
      if (isSimulating) return;
      if (!isPanMode && !isDragging && !isPending) return;
      if (isPending && pendingEvent) {
        const dist = Math.hypot(e.clientX - startX, e.clientY - startY);
        if (dist > 3) {
          isDragging = true;
          isPending = false;
          el.style.cursor = 'grabbing';

          isSimulating = true;
          try {
            const innerTarget = getInnerTarget();
            dispatchSimulatedPointerEvent(innerTarget, 'pointerdown', pendingEvent, {
              button: 1,
              buttons: 4,
            });
            dispatchSimulatedPointerEvent(innerTarget, 'pointermove', e, {
              button: -1,
              buttons: 4,
            });
          } finally {
            isSimulating = false;
          }

          e.stopPropagation();
        } else {
          e.stopPropagation();
        }
      } else if (isDragging) {
        isSimulating = true;
        try {
          dispatchSimulatedPointerEvent(getInnerTarget(), 'pointermove', e, {
            button: -1,
            buttons: 4,
          });
        } finally {
          isSimulating = false;
        }
        e.stopPropagation();
      }
    };

    const handlePointerUp = (e: PointerEvent) => {
      if (isSimulating) return;
      if (!isPanMode && !isDragging && !isPending) return;
      if (isPending && pendingEvent) {
        isPending = false;
        isSimulating = true;
        try {
          const innerTarget = getInnerTarget();
          dispatchSimulatedPointerEvent(innerTarget, 'pointerdown', pendingEvent, {
            button: 0,
            buttons: 1,
          });
          dispatchSimulatedPointerEvent(innerTarget, 'pointerup', e, {
            button: 0,
            buttons: 0,
          });
        } finally {
          isSimulating = false;
        }
        e.stopPropagation();
      } else if (isDragging) {
        isDragging = false;
        el.style.cursor = 'grab';
        isSimulating = true;
        try {
          dispatchSimulatedPointerEvent(getInnerTarget(), 'pointerup', e, {
            button: 1,
            buttons: 0,
          });
        } finally {
          isSimulating = false;
        }
        e.stopPropagation();
      }
    };

    const handlePointerCancel = (e: PointerEvent) => {
      if (isSimulating) return;
      if (!isPanMode && !isDragging && !isPending) return;
      if (isDragging) {
        isDragging = false;
        el.style.cursor = 'grab';
        isSimulating = true;
        try {
          dispatchSimulatedPointerEvent(getInnerTarget(), 'pointerup', e, {
            button: 1,
            buttons: 0,
          });
        } finally {
          isSimulating = false;
        }
      }
      isPending = false;
    };

    target.addEventListener('pointerdown', handlePointerDown as EventListener, { capture: true });
    target.addEventListener('pointermove', handlePointerMove as EventListener, { capture: true });
    target.addEventListener('pointerup', handlePointerUp as EventListener, { capture: true });
    target.addEventListener('pointercancel', handlePointerCancel as EventListener, { capture: true });

    // 4. Zoom="objects" re-application on loaded events
    const handleLoad = () => {
      el.setAttribute('zoom', zoom);
    };
    el.addEventListener('load', handleLoad);
    el.addEventListener('kicanvas:load', handleLoad);

    return () => {
      observer.disconnect();
      el.removeEventListener('wheel', handleWheel, { capture: true });
      target.removeEventListener('pointerdown', handlePointerDown as EventListener, { capture: true });
      target.removeEventListener('pointermove', handlePointerMove as EventListener, { capture: true });
      target.removeEventListener('pointerup', handlePointerUp as EventListener, { capture: true });
      target.removeEventListener('pointercancel', handlePointerCancel as EventListener, { capture: true });
      el.removeEventListener('load', handleLoad);
      el.removeEventListener('kicanvas:load', handleLoad);
    };
  }, [status, zoom, isPanMode]);

  // 400 means the file was not found/expired; other errors are generic failures
  const isExpiredUrl = errorMsg?.includes('400');

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
            ref={(el: HTMLElement | null) => { embedRef.current = el; }}
            src={src}
            controls="none"
            theme="witchhazel"
            {...(zoom ? { zoom } : {})}
            style={{ width: '100%', height: '100%', display: 'block' }}
          />

          {/* HUD Toolbar */}
          <div className="absolute bottom-4 left-1/2 -translate-x-1/2 flex items-center gap-1.5 p-1 rounded-xl bg-[#0a0a0a]/80 border border-[#1e1e1e] backdrop-blur-md shadow-2xl z-20 select-none">
            <div className="flex items-center gap-0.5 bg-[#111]/60 p-0.5 rounded-lg border border-[#1a1a1a]">
              <button
                type="button"
                onClick={() => setIsPanMode(false)}
                className={`p-1.5 rounded-md transition-all ${
                  !isPanMode
                    ? 'bg-primary/20 text-primary border border-primary/30'
                    : 'text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] border border-transparent'
                }`}
                title="Select Mode (Click components to view details)"
              >
                <MousePointer size={14} />
              </button>
              <button
                type="button"
                onClick={() => setIsPanMode(true)}
                className={`p-1.5 rounded-md transition-all ${
                  isPanMode
                    ? 'bg-primary/20 text-primary border border-primary/30'
                    : 'text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] border border-transparent'
                }`}
                title="Pan Mode (Click and drag to move canvas)"
              >
                <Hand size={14} />
              </button>
            </div>
            <div className="w-px h-5 bg-[#1e1e1e]" />
            <div className="flex items-center gap-0.5">
              <button
                type="button"
                onClick={handleZoomIn}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] transition-all"
                title="Zoom In (Ctrl + Scroll Up)"
              >
                <ZoomIn size={14} />
              </button>
              <button
                type="button"
                onClick={handleZoomOut}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] transition-all"
                title="Zoom Out (Ctrl + Scroll Down)"
              >
                <ZoomOut size={14} />
              </button>
              <button
                type="button"
                onClick={handleZoomToFit}
                className="p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-[#1a1a1a] transition-all"
                title="Zoom to Fit (Center schematic)"
              >
                <Maximize size={14} />
              </button>
            </div>
          </div>

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
                { icon: <ZoomIn size={10} />, label: 'Ctrl + Scroll to zoom' },
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
