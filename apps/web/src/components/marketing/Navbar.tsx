'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { Button } from '@/components/ui/button';

export function Navbar() {
  const [scrolled, setScrolled] = useState(false);

  useEffect(() => {
    const handler = () => setScrolled(window.scrollY > 20);
    window.addEventListener('scroll', handler);
    return () => window.removeEventListener('scroll', handler);
  }, []);

  return (
    <nav className={`fixed top-0 inset-x-0 z-50 transition-all duration-300 ${
      scrolled
        ? 'bg-[#080808]/90 backdrop-blur-md border-b border-border'
        : 'bg-transparent'
    }`}>
      <div className="max-w-6xl mx-auto px-6 h-14 flex items-center justify-between">

        {/* Logo */}
        <Link href="/" className="flex items-center">
          <Image
            src="/logo.jpg"
            alt="Layrix"
            width={110}
            height={32}
            className="h-8 w-auto object-contain mix-blend-screen"
            priority
          />
        </Link>

        {/* Nav links */}
        <div className="hidden md:flex items-center gap-8">
          {[
            { label: 'Features', href: '#features' },
            { label: 'Pricing', href: '#pricing' },
            { label: 'Docs', href: '#' },
          ].map(({ label, href }) => (
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
          {/* Technical readout — decorative */}
          <span className="hidden lg:block pcb-label text-muted-foreground/30 mr-2 animate-flicker">
            v0.1.0-beta
          </span>
          <Link href="/dashboard">
            <Button variant="ghost" size="sm" className="text-sm">Sign in</Button>
          </Link>
          <Link href="#waitlist">
            <Button size="sm" className="glow-cyan-sm hover:glow-cyan font-semibold">
              Join Waitlist
            </Button>
          </Link>
        </div>
      </div>
    </nav>
  );
}
