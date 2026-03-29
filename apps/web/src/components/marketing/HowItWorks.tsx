import { HOW_IT_WORKS_STEPS } from '@/lib/marketing-content';

export function HowItWorks() {
  return (
    <section className="py-24 px-6 border-t border-border">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <p className="pcb-label text-muted-foreground/60 mb-3">HOW IT WORKS</p>
          <h2 className="font-display text-4xl font-extrabold tracking-tight mb-4">
            From prompt to PCB<br />
            <span className="text-gradient">in minutes</span>
          </h2>
          <p className="text-muted-foreground text-lg">No EDA software. No manual routing. Just describe and receive.</p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-px bg-border rounded-xl overflow-hidden">
          {HOW_IT_WORKS_STEPS.map(({ num, title, desc, label }, i) => (
            <div
              key={num}
              className="relative bg-[#0a0a0a] p-8 group hover:bg-[#0f0f0f] transition-colors"
            >
              {/* PCB label top */}
              <p className="relative z-10 pcb-label text-muted-foreground/40 mb-6">{label}</p>

              {/* Step circle */}
              <div className="relative z-10 w-12 h-12 rounded-full border border-primary/30 flex items-center justify-center mb-6 group-hover:border-primary group-hover:bg-primary/5 transition-all">
                <span className="font-mono text-sm font-bold text-primary">{num}</span>
              </div>



              <h3 className="relative z-10 font-display text-xl font-bold text-foreground mb-3">{title}</h3>
              <p className="relative z-10 text-muted-foreground text-sm leading-relaxed">{desc}</p>

              {/* Watermark number */}
              <span className="absolute bottom-4 right-6 text-7xl font-extrabold text-white opacity-[0.04] select-none font-display leading-none pointer-events-none z-0">
                {num}
              </span>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}
