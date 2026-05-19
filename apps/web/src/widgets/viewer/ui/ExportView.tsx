'use client';

import { useState } from 'react';
import {
  Download, FileArchive, FileSpreadsheet, Box, AlertCircle,
  ShieldCheck, Package, Clock, ChevronRight, CheckCircle2,
} from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { StageHeader } from './StageHeader';
import type { PCBState } from '@layrix/types';

// ─── Data ─────────────────────────────────────────────────────────────────────

interface OutputFile {
  id: string;
  ext: string;
  label: string;
  desc: string;
  credit: number;
  color: string;
}

const OUTPUT_FILES: OutputFile[] = [
  {
    id: 'gerbers',
    ext: '.zip',
    label: 'Gerber files',
    desc: 'F.Cu / B.Cu / F.Mask / B.Mask / F.SilkS / Edge.Cuts + drill (.drl)',
    credit: 1,
    color: '#00C2FF',
  },
  {
    id: 'bom',
    ext: '.csv',
    label: 'BOM LCSC',
    desc: 'Bill of materials with LCSC part numbers for JLCPCB PCBA.',
    credit: 0,
    color: '#D4820A',
  },
  {
    id: 'cpl',
    ext: '.csv',
    label: 'Pick & Place',
    desc: 'Component placement file (CPL) for SMT assembly.',
    credit: 0,
    color: '#D4820A',
  },
  {
    id: 'step',
    ext: '.step',
    label: '3D STEP model',
    desc: 'Mechanical 3D model for enclosure design and fit checks.',
    credit: 1,
    color: '#22C55E',
  },
];

type Qty = 5 | 10 | 20 | 50;
const QUANTITIES: Qty[] = [5, 10, 20, 50];

const QUOTE: Record<Qty, { pcb: number; pcba: number; days: string }> = {
  5:  { pcb:  8,  pcba:  48, days: '2–3' },
  10: { pcb: 12,  pcba:  82, days: '3–5' },
  20: { pcb: 18,  pcba: 140, days: '3–5' },
  50: { pcb: 30,  pcba: 310, days: '5–7' },
};

// ─── Sub-components ───────────────────────────────────────────────────────────

function FileCard({ file, ready }: { file: OutputFile; ready: boolean }) {
  return (
    <div className="rounded-xl border border-[#1a1a1a] bg-[#0d0d0d] p-4 flex flex-col gap-3 hover:border-[#2a2a2a] transition-colors">
      <div className="flex items-start gap-3">
        <div className="w-8 h-8 rounded-lg bg-[#111] border border-[#222] flex items-center justify-center shrink-0">
          {file.id === 'step'
            ? <Box size={14} style={{ color: file.color }} />
            : file.id === 'gerbers'
            ? <FileArchive size={14} style={{ color: file.color }} />
            : <FileSpreadsheet size={14} style={{ color: file.color }} />}
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5">
            <span className="text-xs font-semibold text-foreground/90">{file.label}</span>
            <span
              className="text-[9px] font-mono px-1 py-px rounded leading-none"
              style={{ background: `${file.color}15`, color: file.color, border: `1px solid ${file.color}25` }}
            >
              {file.ext}
            </span>
          </div>
          <p className="text-[10px] text-[#3d3d3d] leading-snug">{file.desc}</p>
        </div>
      </div>
      <Button
        size="sm"
        variant="secondary"
        disabled={!ready}
        className="w-full gap-1.5 text-[11px] h-7"
      >
        <Download size={11} />
        {ready ? `Download${file.credit ? ` · ${file.credit} credit` : ' · free'}` : 'Not yet available'}
      </Button>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

export function ExportView({ state }: { state: PCBState }) {
  const ready     = state.status === 'DRC_CLEAN' || state.status === 'PCB_LIVRÉ';
  const [qty, setQty] = useState<Qty>(5);
  const [showOrder, setShowOrder] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [ordered, setOrdered] = useState(false);

  const quote = QUOTE[qty];

  function handleOrder() {
    if (!confirmed) return;
    setOrdered(true);
    setShowOrder(false);
    setConfirmed(false);
  }

  const metaBadge = ready
    ? <span className="text-[#22C55E]">DRC clean · ready to export</span>
    : <span className="text-warning">Pending DRC</span>;

  return (
    <div className="flex flex-col h-full bg-[#080808]">
      <StageHeader
        icon={<Download size={12} />}
        title="Export & Manufacture"
        meta={metaBadge}
      />

      <div className="flex-1 overflow-y-auto p-4 space-y-6">

        {/* Not ready warning */}
        {!ready && (
          <div className="flex items-start gap-2.5 rounded-xl border border-warning/20 bg-warning/5 px-4 py-3">
            <AlertCircle size={14} className="text-warning shrink-0 mt-0.5" />
            <p className="text-xs text-warning/90 leading-relaxed">
              Complete the DRC step before exporting fabrication files.
            </p>
          </div>
        )}

        {/* Order success banner */}
        {ordered && (
          <div className="flex items-start gap-2.5 rounded-xl border border-[#22C55E]/25 bg-[#22C55E]/05 px-4 py-3">
            <CheckCircle2 size={14} className="text-[#22C55E] shrink-0 mt-0.5" />
            <div>
              <p className="text-xs font-semibold text-[#22C55E]">Order sent to JLCPCB</p>
              <p className="text-[11px] text-muted-foreground mt-0.5">
                You will receive a confirmation email from JLCPCB within a few minutes.
              </p>
            </div>
          </div>
        )}

        {/* ── Fabrication files ── */}
        <section>
          <h2 className="text-xs font-semibold text-foreground/80 uppercase tracking-widest mb-3">
            Fabrication files
          </h2>
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            {OUTPUT_FILES.map((f) => <FileCard key={f.id} file={f} ready={ready} />)}
          </div>
        </section>

        {/* ── JLCPCB Quote ── */}
        <section className="rounded-xl border border-[#1a1a1a] bg-[#0d0d0d] overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#141414] bg-[#0a0a0a]">
            <div className="flex items-center gap-2">
              <Package size={12} className="text-[#00C2FF]" />
              <span className="text-xs font-semibold text-foreground/90">JLCPCB estimate</span>
            </div>
            {/* Quantity selector */}
            <div className="flex items-center gap-0.5 bg-[#111] rounded-lg p-0.5 border border-[#1e1e1e]">
              {QUANTITIES.map((q) => (
                <button
                  key={q}
                  type="button"
                  onClick={() => setQty(q)}
                  className={`px-2.5 py-1 rounded-md text-[10px] font-mono font-medium transition-all duration-150 ${
                    qty === q
                      ? 'bg-[#1a1a1a] text-foreground border border-[#2e2e2e]'
                      : 'text-[#3d3d3d] hover:text-[#666]'
                  }`}
                >
                  {q}
                </button>
              ))}
              <span className="text-[9px] text-[#2e2e2e] font-mono pl-1.5 pr-1">pcs</span>
            </div>
          </div>

          <div className="p-4 space-y-3">
            {/* PCB only */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-foreground/80">PCB only</p>
                <p className="text-[10px] text-[#3d3d3d]">Standard 1.6 mm FR4 · 2 layers · green soldermask</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold text-foreground">~${quote.pcb}.00</p>
                <p className="text-[9px] font-mono text-[#3d3d3d]">USD · {qty} pcs</p>
              </div>
            </div>

            <div className="border-t border-[#111]" />

            {/* PCBA */}
            <div className="flex items-center justify-between">
              <div>
                <p className="text-xs font-medium text-foreground/80">PCB + PCBA assembly</p>
                <p className="text-[10px] text-[#3d3d3d]">SMT assembly · LCSC components · economic service</p>
              </div>
              <div className="text-right">
                <p className="text-sm font-bold text-foreground">~${quote.pcba}.00</p>
                <p className="text-[9px] font-mono text-[#3d3d3d]">USD · {qty} pcs assembled</p>
              </div>
            </div>

            {/* Lead time */}
            <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[#0a0a0a] border border-[#141414]">
              <Clock size={11} className="text-[#3d3d3d]" />
              <span className="text-[10px] font-mono text-[#3d3d3d]">
                Estimated lead time: <span className="text-foreground/60">{quote.days} business days</span>
              </span>
            </div>

            <p className="text-[9px] text-[#2a2a2a] font-mono">
              * Estimates based on JLCPCB standard pricing. Final price confirmed at checkout.
            </p>
          </div>
        </section>

        {/* ── Order section ── */}
        {!ordered && (
          <section className="rounded-xl border border-primary/20 bg-primary/[0.03] overflow-hidden">
            <div className="flex items-center justify-between px-4 py-3">
              <div>
                <p className="text-xs font-semibold text-foreground/90">Order on JLCPCB</p>
                <p className="text-[10px] text-[#3d3d3d] mt-0.5">
                  Gerbers + BOM + CPL will be sent directly to JLCPCB.
                </p>
              </div>
              {!showOrder && (
                <Button
                  size="sm"
                  disabled={!ready}
                  onClick={() => setShowOrder(true)}
                  className="gap-1.5 text-xs h-8 shrink-0"
                >
                  Configure order
                  <ChevronRight size={11} />
                </Button>
              )}
            </div>

            {/* Confirmation panel */}
            {showOrder && (
              <div className="border-t border-primary/10 mx-0 px-4 py-4 bg-[#040408] space-y-4">
                <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2.5">
                  <p className="text-[11px] text-destructive/90 font-medium leading-snug">
                    This action will initiate a real order on JLCPCB.
                    Once confirmed, cancellation depends on JLCPCB policies.
                  </p>
                </div>

                {/* Order summary */}
                <div className="space-y-1.5 text-[11px] font-mono">
                  <div className="flex justify-between text-foreground/60">
                    <span>Quantity</span>
                    <span>{qty} pcs</span>
                  </div>
                  <div className="flex justify-between text-foreground/60">
                    <span>Service</span>
                    <span>PCB + PCBA assembly</span>
                  </div>
                  <div className="flex justify-between text-foreground/80 font-bold border-t border-[#1a1a1a] pt-1.5 mt-1.5">
                    <span>Estimated total</span>
                    <span>~${quote.pcba}.00 USD</span>
                  </div>
                </div>

                {/* Mandatory confirmation checkbox */}
                <label className="flex items-start gap-3 cursor-pointer group">
                  <input
                    type="checkbox"
                    checked={confirmed}
                    onChange={(e) => setConfirmed(e.target.checked)}
                    className="mt-0.5 w-4 h-4 rounded border border-[#3d3d3d] bg-[#111] accent-primary shrink-0 cursor-pointer"
                  />
                  <span className="text-[11px] text-foreground/70 leading-relaxed group-hover:text-foreground/90 transition-colors">
                    <strong className="text-foreground font-mono">OUI JE CONFIRME</strong> — Je comprends
                    que cette action envoie une commande réelle à JLCPCB et engage des frais.
                    J&apos;ai vérifié le design, le DRC est propre, et je veux passer commande.
                  </span>
                </label>

                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    disabled={!confirmed}
                    onClick={handleOrder}
                    className="gap-1.5 text-xs h-8"
                  >
                    <ShieldCheck size={11} />
                    Confirm & send to JLCPCB
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => { setShowOrder(false); setConfirmed(false); }}
                    className="text-xs h-8 text-muted-foreground"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </section>
        )}

      </div>
    </div>
  );
}
