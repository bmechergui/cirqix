'use client';

// Ce fichier est importé uniquement côté client via dynamic import
import { useEffect, useRef } from 'react';
import { createPCBRenderer } from '../lib/renderer';
import type { PCBRenderer } from '../lib/renderer';
import type { PCBState } from '@layrix/types';

interface PixiCanvasProps {
  pcbState: PCBState | null;
  layerVisibility: Record<string, boolean>;
}

export function PixiCanvas({ pcbState }: PixiCanvasProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const rendererRef = useRef<PCBRenderer | null>(null);
  const initializedRef = useRef(false);

  // Initialise PixiJS une seule fois
  useEffect(() => {
    if (initializedRef.current || !canvasRef.current) return;
    initializedRef.current = true;

    let renderer: PCBRenderer | null = null;

    void createPCBRenderer(canvasRef.current).then((r) => {
      renderer = r;
      rendererRef.current = r;
      r.render(pcbState);
    });

    return () => {
      renderer?.destroy();
      rendererRef.current = null;
      initializedRef.current = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-render quand l'état PCB change
  useEffect(() => {
    rendererRef.current?.render(pcbState);
  }, [pcbState]);

  return (
    <canvas
      ref={canvasRef}
      className="w-full h-full block"
      style={{ background: '#0d0d0d' }}
    />
  );
}
