'use client';

import { Suspense } from 'react';
import { Canvas } from '@react-three/fiber';
import { OrbitControls, Environment } from '@react-three/drei';
import * as THREE from 'three';
import type { PCBState } from '@cirqix/types';
import { layoutBoard, type PlacedComponent } from '../lib/layout-engine';
import { StageHeader } from './StageHeader';
import { Box } from 'lucide-react';

// ─── Component height map (mm → Three.js units = mm) ─────────────────────────

const KIND_HEIGHT: Record<PlacedComponent['kind'], number> = {
  IC:    1.2,
  CAP:   1.8,
  RES:   0.4,
  DIODE: 0.8,
  LED:   1.2,
  CONN:  8.0,
  MISC:  0.8,
};

const KIND_COLOR: Record<PlacedComponent['kind'], string> = {
  IC:    '#1c3a5e',
  CAP:   '#c8c8c8',
  RES:   '#d4a027',
  DIODE: '#5c2d8e',
  LED:   '#cc2222',
  CONN:  '#444444',
  MISC:  '#555555',
};

// ─── PCB board mesh ───────────────────────────────────────────────────────────

function PcbBoard({ w, h }: { w: number; h: number }) {
  return (
    <group>
      {/* FR4 substrate */}
      <mesh receiveShadow position={[0, -0.1, 0]}>
        <boxGeometry args={[w, 0.2, h]} />
        <meshStandardMaterial color="#b8a080" />
      </mesh>
      {/* Top copper + soldermask */}
      <mesh receiveShadow position={[0, 0.0, 0]}>
        <boxGeometry args={[w, 0.08, h]} />
        <meshStandardMaterial color="#1a5220" roughness={0.3} metalness={0.1} />
      </mesh>
      {/* Silkscreen edge outline */}
      <lineSegments>
        <edgesGeometry args={[new THREE.BoxGeometry(w, 0.01, h)]} />
        <lineBasicMaterial color="#ffffff" opacity={0.3} transparent />
      </lineSegments>
    </group>
  );
}

// ─── Single component mesh ────────────────────────────────────────────────────

function ComponentMesh({ comp, boardW, boardH }: {
  comp: PlacedComponent;
  boardW: number;
  boardH: number;
}) {
  const ch = KIND_HEIGHT[comp.kind];
  const color = KIND_COLOR[comp.kind];

  // Convert from top-left (mm) to center-origin Three.js coords
  const tx = comp.x + comp.w / 2 - boardW / 2;
  const tz = comp.y + comp.h / 2 - boardH / 2;
  const ty = ch / 2 + 0.05;

  return (
    <mesh
      castShadow
      position={[tx, ty, tz]}
    >
      <boxGeometry args={[comp.w, ch, comp.h]} />
      <meshStandardMaterial color={color} roughness={0.6} metalness={0.2} />
    </mesh>
  );
}

// ─── Main 3D scene ────────────────────────────────────────────────────────────

function PcbScene({ state }: { state: PCBState }) {
  const boardW = state.board_width_mm ?? 50;
  const boardH = state.board_height_mm ?? 50;
  const placed = layoutBoard(state.components ?? [], boardW, boardH);

  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight
        castShadow
        position={[boardW * 0.8, boardW * 1.2, boardH * 0.6]}
        intensity={1.2}
        shadow-mapSize={[1024, 1024]}
      />
      <pointLight position={[-boardW, 20, -boardH]} intensity={0.3} color="#60b2ff" />

      <PcbBoard w={boardW} h={boardH} />
      {placed.map((comp) => (
        <ComponentMesh
          key={comp.ref}
          comp={comp}
          boardW={boardW}
          boardH={boardH}
        />
      ))}

      <OrbitControls
        autoRotate
        autoRotateSpeed={0.6}
        enableDamping
        dampingFactor={0.05}
        minDistance={10}
        maxDistance={Math.max(boardW, boardH) * 3}
      />
      <Environment preset="city" />
    </>
  );
}

// ─── Empty state ──────────────────────────────────────────────────────────────

function EmptyState() {
  return (
    <div className="flex flex-col items-center justify-center h-full gap-3 text-[#2a2a2a]">
      <Box size={32} strokeWidth={1} />
      <p className="text-xs font-mono">No PCB data — run placement first</p>
    </div>
  );
}

// ─── Public component ─────────────────────────────────────────────────────────

export function View3D({ state }: { state: PCBState }) {
  const hasData = (state.components?.length ?? 0) > 0 || state.board_width_mm;
  const boardW = state.board_width_mm ?? 50;
  const boardH = state.board_height_mm ?? 50;
  const camDist = Math.max(boardW, boardH) * 1.4;

  return (
    <div className="flex flex-col h-full bg-[#080808] overflow-hidden">
      <StageHeader
        icon={<Box size={12} />}
        title="3D Preview"
        meta={
          hasData
            ? <span className="text-[#22C55E]">{boardW}×{boardH} mm · Three.js</span>
            : <span className="text-[#3d3d3d]">No data</span>
        }
      />

      <div className="flex-1 relative overflow-hidden">
        {!hasData ? (
          <EmptyState />
        ) : (
          <Canvas
            shadows
            camera={{ position: [camDist * 0.7, camDist * 0.6, camDist * 0.7], fov: 45 }}
            gl={{ antialias: true, alpha: false }}
            style={{ background: '#0a0a0a' }}
          >
            <Suspense fallback={null}>
              <PcbScene state={state} />
            </Suspense>
          </Canvas>
        )}

        {/* Corner hint */}
        {hasData && (
          <div className="absolute bottom-3 right-3 pointer-events-none">
            <p className="text-[9px] font-mono text-[#2a2a2a]">Drag to rotate · scroll to zoom</p>
          </div>
        )}
      </div>
    </div>
  );
}
