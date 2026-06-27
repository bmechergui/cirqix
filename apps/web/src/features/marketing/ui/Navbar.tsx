'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/shared/ui/button';
import { CirqixLogo } from '@/shared/ui/cirqix-logo';
import { Menu, X } from 'lucide-react';

const NAV_LINKS = [
  { label: 'Features', href: '#features' },
  { label: 'Pricing', href: '#pricing' },
  { label: 'Docs', href: '#' },
];

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', handler);
    return () => window.removeEventListener('scroll', handler);
  }, []);

  return (
    <nav className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${
      scrolled || menuOpen
        ? 'bg-[#080808]/90 backdrop-blur-md border-b border-border'
        : 'bg-transparent'
    }`}>
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">

        {/* Logo */}
        <Link href="/" className="flex items-center">
          <CirqixLogo height={32} />
        </Link>

        {/* Desktop nav links */}
        <div className="hidden md:flex items-center gap-8">
          {NAV_LINKS.map(({ label, href }) => (
            <Link
              key={label}
              href={href}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors font-medium"
            >
              {label}
            </Link>
          ))}
        </div>

        {/* Right side */}
        <div className="flex items-center gap-3">
          <span className="hidden lg:block pcb-label text-muted-foreground/30 mr-2 animate-flicker">
            v0.1.0-beta
          </span>
          <Link href="/login" className="hidden sm:block">
            <Button variant="ghost" size="sm" className="text-sm">Sign in</Button>
          </Link>
          <Link href="/signup" className="hidden sm:block">
            <Button size="sm" className="glow-cyan-sm hover:glow-cyan font-semibold">
              Get started
            </Button>
          </Link>
          <Link href="#waitlist" className="sm:hidden">
            <Button size="sm" className="glow-cyan-sm font-semibold">
              Join Waitlist
            </Button>
          </Link>
          {/* Mobile hamburger */}
          <button
            type="button"
            className="md:hidden flex items-center justify-center w-8 h-8 text-muted-foreground hover:text-foreground transition-colors"
            onClick={() => setMenuOpen((v) => !v)}
            aria-label={menuOpen ? 'Close menu' : 'Open menu'}
          >
            {menuOpen ? <X size={18} /> : <Menu size={18} />}
          </button>
        </div>
      </div>

      {/* Mobile dropdown menu */}
      {menuOpen && (
        <div className="md:hidden border-t border-border bg-[#080808]/95 backdrop-blur-md px-6 py-4 flex flex-col gap-1">
          {NAV_LINKS.map(({ label, href }) => (
            <Link
              key={label}
              href={href}
              onClick={() => setMenuOpen(false)}
              className="text-sm text-muted-foreground hover:text-foreground transition-colors py-2"
            >
              {label}
            </Link>
          ))}
          <div className="pt-2 border-t border-border mt-2 flex flex-col gap-2">
            <Link href="/login" onClick={() => setMenuOpen(false)}>
              <Button variant="ghost" size="sm" className="w-full justify-start text-sm">Sign in</Button>
            </Link>
            <Link href="/signup" onClick={() => setMenuOpen(false)}>
              <Button size="sm" className="w-full font-semibold">Get started</Button>
            </Link>
          </div>
        </div>
      )}
    </nav>
  );
}
