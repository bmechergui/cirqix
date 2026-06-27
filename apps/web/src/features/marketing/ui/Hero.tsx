import Link from 'next/link';
import { Button } from '@/shared/ui/button';
import { ArrowRight } from 'lucide-react';

function PCBPreview() {
  return (
    <svg
      viewBox="0 0 480 280"
      className="w-full opacity-90"
      xmlns="http://www.w3.org/2000/svg"
      aria-hidden="true"
    >
      <defs>
        <filter id="glow">
          <feGaussianBlur stdDeviation="2" result="blur" />
          <feMerge><feMergeNode in="blur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
        <linearGradient id="traceGrad" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#00C2FF" stopOpacity="0" />
          <stop offset="40%" stopColor="#00C2FF" stopOpacity="0.8" />
          <stop offset="100%" stopColor="#00C2FF" stopOpacity="0.3" />
        </linearGradient>
        <linearGradient id="traceGrad2" x1="0%" y1="0%" x2="100%" y2="0%">
          <stop offset="0%" stopColor="#D4820A" stopOpacity="0.3" />
          <stop offset="60%" stopColor="#D4820A" stopOpacity="0.7" />
          <stop offset="100%" stopColor="#D4820A" stopOpacity="0" />
        </linearGradient>
      </defs>

      {/* Board */}
      <rect x="10" y="10" width="460" height="260" rx="4" fill="#0d1a00" stroke="#22330a" strokeWidth="1.5" />

      {/* Grid dots */}
      {Array.from({ length: 8 }, (_, row) =>
        Array.from({ length: 14 }, (_, col) => (
          <circle key={`${row}-${col}`} cx={30 + col * 30} cy={30 + row * 30} r="0.8" fill="rgba(0,194,255,0.15)" />
        ))
      )}

      {/* F.Cu traces */}
      <path d="M60 80 L180 80 L180 140 L300 140" stroke="url(#traceGrad)" strokeWidth="2" fill="none" filter="url(#glow)" />
      <path d="M300 140 L380 140 L380 200" stroke="#00C2FF" strokeWidth="2" fill="none" opacity="0.6" />
      <path d="M60 200 L120 200 L120 140 L180 140" stroke="#00C2FF" strokeWidth="1.5" fill="none" opacity="0.5" />
      <path d="M240 60 L240 140" stroke="#00C2FF" strokeWidth="1.5" fill="none" opacity="0.4" />

      {/* B.Cu traces */}
      <path d="M100 100 L100 220 L320 220 L320 180" stroke="url(#traceGrad2)" strokeWidth="1.5" fill="none" />
      <path d="M320 180 L420 180" stroke="#D4820A" strokeWidth="1.5" fill="none" opacity="0.5" />

      {/* Vias */}
      {([[ 180, 140], [300, 140], [120, 200], [240, 140]] as [number,number][]).map(([cx, cy], i) => (
        <g key={i}>
          <circle cx={cx} cy={cy} r="5" fill="#0d1a00" stroke="#888" strokeWidth="1" />
          <circle cx={cx} cy={cy} r="2.5" fill="#555" />
        </g>
      ))}

      {/* IC — main chip */}
      <rect x="195" y="100" width="90" height="80" rx="3" fill="#0a0a0a" stroke="#3a3a3a" strokeWidth="1.5" />
      {/* IC pins */}
      {[0,1,2,3].map(i => (
        <rect key={`l${i}`} x="191" y={110 + i * 14} width="8" height="4" rx="1" fill="#555" />
      ))}
      {[0,1,2,3].map(i => (
        <rect key={`r${i}`} x="281" y={110 + i * 14} width="8" height="4" rx="1" fill="#555" />
      ))}
      <text x="240" y="143" textAnchor="middle" fill="#444" fontSize="9" fontFamily="monospace">MCU</text>
      <circle cx="240" cy="130" r="1.5" fill="#00C2FF" opacity="0.6" />

      {/* Capacitors */}
      {([[60, 68], [60, 88]] as [number,number][]).map(([x, y], i) => (
        <g key={i}>
          <rect x={x} y={y} width="16" height="10" rx="1" fill="#1a1a1a" stroke="#444" strokeWidth="1" />
          <line x1={x + 8} y1={y} x2={x + 8} y2={y - 6} stroke="#00C2FF" strokeWidth="1" opacity="0.5" />
        </g>
      ))}

      {/* Resistors */}
      {[[370, 128], [370, 148], [370, 168]].map(([x, y], i) => (
        <rect key={i} x={x} y={y} width="20" height="8" rx="2" fill="#1a1a1a" stroke="#444" strokeWidth="1" />
      ))}

      {/* Connector */}
      <rect x="40" y="120" width="12" height="48" rx="1" fill="#1a1a1a" stroke="#555" strokeWidth="1" />
      {[0,1,2,3,4].map(i => (
        <circle key={i} cx={46} cy={130 + i * 9} r="2.5" fill="#0d1a00" stroke="#777" strokeWidth="0.8" />
      ))}

      {/* DRC-clean badge */}
      <g>
        <rect x="350" y="15" width="100" height="22" rx="3" fill="rgba(34,197,94,0.1)" stroke="rgba(34,197,94,0.3)" strokeWidth="1" />
        <circle cx="362" cy="26" r="3" fill="#22C55E" opacity="0.8" />
        <text x="370" y="30" fill="#22C55E" fontSize="8" fontFamily="monospace" opacity="0.9">DRC CLEAN</text>
      </g>

      {/* Agent status */}
      <g>
        <rect x="10" y="15" width="90" height="22" rx="3" fill="rgba(0,194,255,0.06)" stroke="rgba(0,194,255,0.2)" strokeWidth="1" />
        <text x="18" y="30" fill="#00C2FF" fontSize="8" fontFamily="monospace" opacity="0.8">ROUTING…</text>
      </g>

      {/* Silkscreen labels */}
      <text x="197" y="96" fill="#555" fontSize="7" fontFamily="monospace">U1</text>
      <text x="62" y="64" fill="#555" fontSize="7" fontFamily="monospace">C1</text>
      <text x="372" y="124" fill="#555" fontSize="7" fontFamily="monospace">R1</text>
    </svg>
  );
}

export function Hero() {
  return (
    <section className="relative min-h-screen flex items-center justify-center pcb-grid scan-overlay">
      {/* Background glows — isolated overflow-hidden wrapper so text is never clipped */}
      <div className="absolute inset-0 overflow-hidden pointer-events-none">
        <div className="absolute inset-0 flex items-center justify-center">
          <div className="w-[700px] h-[700px] rounded-full bg-primary/4 blur-[120px]" />
        </div>
        <div className="absolute bottom-0 right-0 w-[400px] h-[400px] rounded-full bg-accent/3 blur-[100px]" />
      </div>

      <div className="relative z-10 w-full max-w-6xl mx-auto px-6 pt-28 pb-16">
        <div className="grid xl:grid-cols-[3fr_2fr] gap-12 items-center">

          {/* Left — copy */}
          <div className="min-w-0">
            {/* Status pill */}
            <div className="inline-flex items-center gap-2.5 border border-primary/30 bg-primary/5 text-primary text-xs uppercase tracking-[0.14em] px-3.5 py-1.5 rounded-full mb-8 font-mono">
              <span className="via animate-pulse-slow" />
              AI PCB Design Agent
            </div>

            {/* Headline — display font */}
            <h1 className="font-display text-[2rem] leading-[1.08] font-extrabold tracking-tight mb-6 sm:text-[2.6rem] md:text-[3rem] xl:text-[3rem]">
              From idea to<br />
              manufacturable<br />
              <span className="text-gradient">PCB, autonomously</span>
            </h1>

            <p className="text-base text-muted-foreground mb-10 leading-relaxed max-w-md">
              Describe your circuit in plain English. Cirqix generates a DRC-clean PCB,
              exports Gerbers, and orders from JLCPCB — fully&nbsp;autonomously.
            </p>

            {/* CTAs */}
            <div className="flex flex-col sm:flex-row items-start gap-3 mb-12">
              <Link href="#waitlist">
                <Button size="lg" className="gap-2 glow-cyan-sm hover:glow-cyan px-8 font-semibold">
                  Join the Waitlist
                  <ArrowRight size={16} />
                </Button>
              </Link>
              <Link href="/dashboard">
                <Button variant="secondary" size="lg" className="gap-2 px-8 border border-border hover:border-primary/40 transition-colors">
                  Open Dashboard
                </Button>
              </Link>
            </div>

            {/* Stats — inline trace style */}
            <div className="flex flex-wrap items-center gap-6 md:gap-8">
              {[
                { value: '< 5 min', label: 'per PCB' },
                { value: '0 DRC', label: 'violations' },
                { value: '100%', label: 'cloud' },
              ].map(({ value, label }, i) => (
                <div key={label} className="flex flex-col">
                  {i > 0 && null}
                  <span className="font-display text-xl font-bold text-foreground">{value}</span>
                  <span className="pcb-label">{label}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Right — PCB preview */}
          <div className="relative hidden xl:block pt-8">
            {/* Circuit corner decoration */}
            <div className="absolute inset-0 circuit-corners pointer-events-none" />
            {/* PCB coordinate readout */}
            <div className="absolute top-0 right-0 flex items-center gap-3 pcb-label opacity-60">
              <span>X: 240.00mm</span>
              <span>Y: 140.00mm</span>
              <span className="text-success">●</span>
            </div>

            <div className="rounded-lg border border-[#1a2d0a] bg-[#0a0f05] overflow-hidden">
              <div className="flex items-center gap-2 px-3 py-2 border-b border-[#1a2d0a] bg-[#080c04]">
                <div className="flex gap-1.5">
                  <span className="w-2.5 h-2.5 rounded-full bg-[#2a2a2a]" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#2a2a2a]" />
                  <span className="w-2.5 h-2.5 rounded-full bg-[#2a2a2a]" />
                </div>
                <span className="pcb-label ml-2">esp32-weather-station.kicad_pcb</span>
                <span className="ml-auto pcb-label text-success">● F.Cu</span>
              </div>
              <PCBPreview />
            </div>

            {/* Agent log below */}
            <div className="mt-3 border border-[#1a2d0a] bg-[#080808] rounded-md px-3 py-2 animate-flicker">
              <p className="font-mono text-[11px] text-primary/70 leading-relaxed">
                <span className="text-muted-foreground/40">{'>'} </span>
                Agent routing trace 47/47 · DRC violations: <span className="text-success font-bold">0</span>
                <span className="animate-blink ml-1">_</span>
              </p>
            </div>
          </div>
        </div>
      </div>
    </section>
  );
}
