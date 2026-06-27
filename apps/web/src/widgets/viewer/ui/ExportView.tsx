'use client';

import dynamic from 'next/dynamic';
import { useState } from 'react';
import {
  Download, FileArchive, FileSpreadsheet, Box, AlertCircle,
  ShieldCheck, Package, Clock, ChevronRight, CheckCircle2, Loader2,
} from 'lucide-react';
import { Button } from '@/shared/ui/button';
import { StageHeader } from './StageHeader';
import type { PCBState } from '@cirqix/types';

const View3D = dynamic(() => import('./View3D').then((m) => ({ default: m.View3D })), {
  ssr: false,
  loading: () => (
    <div className="flex items-center justify-center h-full text-[#2a2a2a] text-xs font-mono">
      Loading 3D…
    </div>
  ),
});

// ─── Helpers ──────────────────────────────────────────────────────────────────

function downloadB64(b64: string, filename: string, mime: string) {
  const bytes = atob(b64);
  const arr = new Uint8Array(bytes.length);
  for (let i = 0; i < bytes.length; i++) arr[i] = bytes.charCodeAt(i);
  const url = URL.createObjectURL(new Blob([arr], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

function downloadText(text: string, filename: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

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

// Fallback quote table when the export service hasn't returned a quote yet
const QUOTE_TABLE: Record<Qty, { pcb: number; pcba: number; days: string }> = {
  5:  { pcb:  8,  pcba:  48, days: '2–3' },
  10: { pcb: 12,  pcba:  82, days: '3–5' },
  20: { pcb: 18,  pcba: 140, days: '3–5' },
  50: { pcb: 30,  pcba: 310, days: '5–7' },
};

// ─── Sub-components ───────────────────────────────────────────────────────────

interface FileCardProps {
  file: OutputFile;
  ready: boolean;
  onDownload?: () => void;
}

function FileCard({ file, ready, onDownload }: FileCardProps) {
  const canDownload = ready && !!onDownload;
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
        disabled={!canDownload}
        onClick={onDownload}
        className="w-full gap-1.5 text-[11px] h-7"
      >
        <Download size={11} />
        {canDownload
          ? `Download${file.credit ? ` · ${file.credit} credit` : ' · free'}`
          : ready ? 'Run export to generate' : 'Not yet available'}
      </Button>
    </div>
  );
}

// ─── Main ─────────────────────────────────────────────────────────────────────

type ExportTab = 'files' | '3d';

export function ExportView({ state }: { state: PCBState }) {
  const ready     = state.status === 'DRC_CLEAN' || state.status === 'PCB_LIVRÉ';
  const [tab, setTab] = useState<ExportTab>('files');
  const [qty, setQty] = useState<Qty>(5);
  const [showOrder, setShowOrder] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [ordered, setOrdered] = useState(false);
  const [orderLoading, setOrderLoading] = useState(false);
  const [orderError, setOrderError] = useState<string | null>(null);
  const [orderRef, setOrderRef] = useState<string | null>(null);

  const fallbackQuote = QUOTE_TABLE[qty];
  const pcbPrice = state.quoteUsd ?? fallbackQuote.pcb;
  const pcbaPrice = state.quoteUsd != null ? Math.round(state.quoteUsd * 5) : fallbackQuote.pcba;
  const leadTime = state.leadTimeDays != null ? `${state.leadTimeDays}` : fallbackQuote.days;
  const quoteIsReal = state.quoteUsd != null;

  function getDownloadHandler(fileId: string): (() => void) | undefined {
    switch (fileId) {
      case 'gerbers':
        return state.gerberZipB64
          ? () => downloadB64(state.gerberZipB64!, 'gerbers.zip', 'application/zip')
          : undefined;
      case 'bom':
        return state.bomCsv
          ? () => downloadText(state.bomCsv!, 'bom-lcsc.csv')
          : undefined;
      case 'cpl':
        // CPL is embedded in the BOM for now; expose when a dedicated field is added
        return undefined;
      case 'step':
        // STEP export is a separate Phase 4.2 feature
        return undefined;
      default:
        return undefined;
    }
  }

  async function handleOrder() {
    if (!confirmed) return;
    setOrderLoading(true);
    setOrderError(null);
    try {
      const res = await fetch('/api/jlcpcb/order', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ projectId: state.projectId, qty, confirmed: true }),
      });
      const json = (await res.json()) as { success: boolean; data?: { orderRef: string }; error?: string };
      if (!res.ok || !json.success) throw new Error(json.error ?? 'Order failed');
      setOrderRef(json.data?.orderRef ?? null);
      setOrdered(true);
      setShowOrder(false);
      setConfirmed(false);
    } catch (err) {
      setOrderError(err instanceof Error ? err.message : 'Order failed');
    } finally {
      setOrderLoading(false);
    }
  }

  const metaBadge = ready
    ? <span className="text-[#22C55E]">DRC clean · ready to export</span>
    : <span className="text-warning">Pending DRC</span>;

  return (
    <div className="flex flex-col h-full bg-[#080808] overflow-hidden">
      <StageHeader
        icon={<Download size={12} />}
        title="Export & Manufacture"
        meta={metaBadge}
        actions={
          <div className="flex items-center gap-0.5 bg-[#111] rounded-lg p-0.5 border border-[#1e1e1e]">
            {([['files', <Download key="d" size={10} />, 'Files'] , ['3d', <Box key="b" size={10} />, '3D']] as const).map(([id, icon, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setTab(id)}
                className={`flex items-center gap-1 px-2.5 py-1 rounded-md text-[10px] font-medium transition-all duration-150 ${
                  tab === id
                    ? 'bg-[#1a1a1a] text-foreground border border-[#2e2e2e]'
                    : 'text-[#3d3d3d] hover:text-[#666]'
                }`}
              >
                {icon}{label}
              </button>
            ))}
          </div>
        }
      />

      {tab === '3d' && <View3D state={state} />}

      {tab === 'files' && <div className="flex-1 overflow-y-auto p-4 space-y-6">

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
              {orderRef && (
                <p className="text-[10px] font-mono text-[#22C55E]/70 mt-0.5">{orderRef}</p>
              )}
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
            {OUTPUT_FILES.map((f) => {
              const onDownload = getDownloadHandler(f.id);
              return (
                <FileCard
                  key={f.id}
                  file={f}
                  ready={ready}
                  {...(onDownload ? { onDownload } : {})}
                />
              );
            })}
          </div>
        </section>

        {/* ── JLCPCB Quote ── */}
        <section className="rounded-xl border border-[#1a1a1a] bg-[#0d0d0d] overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2.5 border-b border-[#141414] bg-[#0a0a0a]">
            <div className="flex items-center gap-2">
              <Package size={12} className="text-[#00C2FF]" />
              <span className="text-xs font-semibold text-foreground/90">JLCPCB estimate</span>
              {quoteIsReal && (
                <span className="text-[9px] font-mono px-1.5 py-px rounded bg-[#00C2FF]/10 text-[#00C2FF] border border-[#00C2FF]/20">
                  live quote
                </span>
              )}
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
                <p className="text-sm font-bold text-foreground">~${pcbPrice.toFixed(0)}.00</p>
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
                <p className="text-sm font-bold text-foreground">~${pcbaPrice.toFixed(0)}.00</p>
                <p className="text-[9px] font-mono text-[#3d3d3d]">USD · {qty} pcs assembled</p>
              </div>
            </div>

            {/* Lead time */}
            <div className="flex items-center gap-1.5 px-3 py-2 rounded-lg bg-[#0a0a0a] border border-[#141414]">
              <Clock size={11} className="text-[#3d3d3d]" />
              <span className="text-[10px] font-mono text-[#3d3d3d]">
                Estimated lead time: <span className="text-foreground/60">{leadTime} business days</span>
              </span>
            </div>

            <p className="text-[9px] text-[#2a2a2a] font-mono">
              {quoteIsReal
                ? '* Quote from kicad-cli export service. Final price confirmed at JLCPCB checkout.'
                : '* Estimates based on JLCPCB standard pricing. Final price confirmed at checkout.'}
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
                    <span>~${pcbaPrice.toFixed(0)}.00 USD</span>
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

                {orderError && (
                  <p className="text-[11px] text-destructive font-mono">{orderError}</p>
                )}

                <div className="flex items-center gap-2">
                  <Button
                    size="sm"
                    disabled={!confirmed || orderLoading}
                    onClick={handleOrder}
                    className="gap-1.5 text-xs h-8"
                  >
                    {orderLoading
                      ? <><Loader2 size={11} className="animate-spin" />Sending…</>
                      : <><ShieldCheck size={11} />Confirm & send to JLCPCB</>}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    disabled={orderLoading}
                    onClick={() => { setShowOrder(false); setConfirmed(false); setOrderError(null); }}
                    className="text-xs h-8 text-muted-foreground"
                  >
                    Cancel
                  </Button>
                </div>
              </div>
            )}
          </section>
        )}

      </div>}
    </div>
  );
}
