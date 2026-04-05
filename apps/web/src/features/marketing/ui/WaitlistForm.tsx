'use client';

import { useState } from 'react';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { Check } from 'lucide-react';

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function WaitlistForm() {
  const [email, setEmail] = useState('');
  const [state, setState] = useState<'idle' | 'loading' | 'success' | 'error'>('idle');
  const [errorMsg, setErrorMsg] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!EMAIL_RE.test(email)) {
      setErrorMsg('Please enter a valid email address.');
      setState('error');
      return;
    }
    setState('loading');
    setErrorMsg('');
    try {
      const res = await fetch('/api/waitlist', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email }),
      });
      const data = await res.json() as { success: boolean; error?: string };
      if (!res.ok) {
        setErrorMsg(data.error === 'already_registered' ? "You're already on the list!" : 'Something went wrong. Please try again.');
        setState('error');
        return;
      }
      setState('success');
    } catch {
      setErrorMsg('Something went wrong. Please try again.');
      setState('error');
    }
  };

  return (
    <section id="waitlist" className="py-24 px-6 border-t border-border scroll-mt-14">
      <div className="max-w-xl mx-auto text-center">
        <div className="inline-flex items-center gap-2 border border-primary/30 text-primary text-xs px-3 py-1.5 rounded-full mb-6">
          <span className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse-slow" />
          Early Access
        </div>
        <h2 className="text-2xl sm:text-3xl md:text-4xl font-bold tracking-tight mb-4">Be first to design PCBs with AI</h2>
        <p className="text-muted-foreground mb-8">Join 500+ engineers already on the waitlist.</p>

        {state === 'success' ? (
          <div className="flex items-center justify-center gap-3 bg-[#22C55E]/10 border border-[#22C55E]/30 text-[#22C55E] rounded-xl p-4">
            <Check size={20} />
            <span className="font-medium">You&apos;re on the list! We&apos;ll notify you when Layrix launches.</span>
          </div>
        ) : (
          <div className="flex flex-col gap-2">
            <form onSubmit={handleSubmit} className="flex flex-col sm:flex-row gap-2">
              <Input
                type="email"
                placeholder="your@email.com"
                value={email}
                onChange={(e) => { setEmail(e.target.value); if (state === 'error') setState('idle'); }}
                required
                className="flex-1 h-12 text-base"
                aria-describedby={state === 'error' ? 'waitlist-error' : undefined}
              />
              <Button type="submit" size="lg" disabled={state === 'loading'} className="px-6 glow-cyan-sm">
                {state === 'loading' ? 'Joining...' : 'Join Waitlist'}
              </Button>
            </form>
            {state === 'error' && (
              <p id="waitlist-error" className="text-sm text-red-400">{errorMsg}</p>
            )}
          </div>
        )}
      </div>
    </section>
  );
}
