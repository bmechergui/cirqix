import { Card, CardContent } from '@/components/ui/card';
import { FEATURES } from '@/lib/marketing-content';

export function Features() {
  return (
    <section id="features" className="py-24 px-6 border-t border-border scroll-mt-14">
      <div className="max-w-6xl mx-auto">
        <div className="text-center mb-16">
          <p className="pcb-label text-muted-foreground/60 mb-3">CAPABILITIES</p>
          <h2 className="font-display text-4xl font-extrabold tracking-tight mb-4">
            Everything you need to<br />
            <span className="text-gradient">design PCBs with AI</span>
          </h2>
          <p className="text-muted-foreground text-lg max-w-2xl mx-auto">
            From schematic to Gerbers, the entire workflow is automated.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          {FEATURES.map(({ icon: Icon, label, title, desc, accent }) => (
            <Card
              key={title}
              className="group hover:border-primary/30 transition-all duration-300 hover:bg-[#0f0f0f] circuit-corners"
            >
              <CardContent className="p-6">
                {/* PCB label */}
                <p className="pcb-label text-muted-foreground/30 mb-4">{label}</p>

                {/* Icon */}
                <div className={`w-10 h-10 rounded-lg flex items-center justify-center mb-4 transition-colors ${
                  accent === 'copper'
                    ? 'bg-accent/10 group-hover:bg-accent/20'
                    : 'bg-primary/10 group-hover:bg-primary/20'
                }`}>
                  <Icon
                    size={18}
                    className={accent === 'copper' ? 'text-accent' : 'text-primary'}
                  />
                </div>

                <h3 className="font-display font-bold text-foreground mb-2">{title}</h3>
                <p className="text-muted-foreground text-sm leading-relaxed">{desc}</p>
              </CardContent>
            </Card>
          ))}
        </div>
      </div>
    </section>
  );
}
