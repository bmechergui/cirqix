import { Separator } from '@/shared/ui/separator';
import { FOOTER_LINKS } from '@/shared/lib/marketing-content';
import { CirqixLogo } from '@/shared/ui/cirqix-logo';

export function Footer() {
  return (
    <footer className="py-16 px-6 border-t border-border">
      <div className="max-w-6xl mx-auto">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-8 mb-12">
          {/* Brand */}
          <div>
            <div className="mb-4">
              <CirqixLogo height={28} />
            </div>
            <p className="text-xs text-muted-foreground leading-relaxed">
              AI PCB Design Agent — From idea to manufacturable PCB, autonomously.
            </p>
          </div>

          {Object.entries(FOOTER_LINKS).map(([group, items]) => (
            <div key={group}>
              <h4 className="text-xs font-semibold text-foreground uppercase tracking-widest mb-4">
                {group}
              </h4>
              <ul className="space-y-2">
                {items.map((item) => (
                  <li key={item}>
                    <span className="text-sm text-muted-foreground hover:text-foreground transition-colors cursor-pointer">
                      {item}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <Separator className="mb-6" />

        <div className="flex flex-col md:flex-row items-center justify-between gap-4 text-xs text-muted-foreground">
          <span>© 2025 Cirqix Technologies. All rights reserved.</span>
          <span>Made with ♥ for hardware engineers</span>
        </div>
      </div>
    </footer>
  );
}
