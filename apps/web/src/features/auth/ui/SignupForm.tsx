'use client';

import { useState } from 'react';
import Link from 'next/link';
import { Button } from '@/shared/ui/button';
import { Input } from '@/shared/ui/input';
import { createSupabaseBrowserClient } from '@/shared/lib/supabase-browser';
import { Check } from 'lucide-react';

export function SignupForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState(false);

  const handleSignup = async (e: React.FormEvent) => {
    e.preventDefault();
    if (password.length < 8) {
      setError('Password must be at least 8 characters.');
      return;
    }
    setLoading(true);
    setError('');

    const supabase = createSupabaseBrowserClient();
    const { error: authError } = await supabase.auth.signUp({
      email,
      password,
      options: { emailRedirectTo: `${window.location.origin}/auth/callback` },
    });

    if (authError) {
      setError(authError.message);
      setLoading(false);
      return;
    }

    setSuccess(true);
    setLoading(false);
  };

  const handleGoogleSignup = async () => {
    const supabase = createSupabaseBrowserClient();
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });
  };

  if (success) {
    return (
      <div className="bg-[#0f0f0f] border border-border rounded-2xl p-8 text-center space-y-4">
        <div className="w-12 h-12 rounded-full bg-green-500/10 border border-green-500/30 flex items-center justify-center mx-auto">
          <Check size={20} className="text-green-400" />
        </div>
        <h2 className="text-lg font-bold text-foreground">Check your email</h2>
        <p className="text-sm text-muted-foreground">
          We sent a confirmation link to <span className="text-foreground font-medium">{email}</span>.
          Click it to activate your account.
        </p>
        <Link href="/login" className="text-sm text-primary hover:underline block">
          Back to sign in
        </Link>
      </div>
    );
  }

  return (
    <div className="bg-[#0f0f0f] border border-border rounded-2xl p-8 space-y-6">
      <div className="space-y-1 text-center">
        <h1 className="text-xl font-bold text-foreground">Create your account</h1>
        <p className="text-sm text-muted-foreground">Start designing PCBs with AI</p>
      </div>

      <Button
        type="button"
        variant="secondary"
        className="w-full gap-2 border border-border"
        onClick={handleGoogleSignup}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
          <path d="M22.56 12.25c0-.78-.07-1.53-.2-2.25H12v4.26h5.92c-.26 1.37-1.04 2.53-2.21 3.31v2.77h3.57c2.08-1.92 3.28-4.74 3.28-8.09z" fill="#4285F4"/>
          <path d="M12 23c2.97 0 5.46-.98 7.28-2.66l-3.57-2.77c-.98.66-2.23 1.06-3.71 1.06-2.86 0-5.29-1.93-6.16-4.53H2.18v2.84C3.99 20.53 7.7 23 12 23z" fill="#34A853"/>
          <path d="M5.84 14.09c-.22-.66-.35-1.36-.35-2.09s.13-1.43.35-2.09V7.07H2.18C1.43 8.55 1 10.22 1 12s.43 3.45 1.18 4.93l3.66-2.84z" fill="#FBBC05"/>
          <path d="M12 5.38c1.62 0 3.06.56 4.21 1.64l3.15-3.15C17.45 2.09 14.97 1 12 1 7.7 1 3.99 3.47 2.18 7.07l3.66 2.84c.87-2.6 3.3-4.53 6.16-4.53z" fill="#EA4335"/>
        </svg>
        Continue with Google
      </Button>

      <div className="flex items-center gap-3">
        <div className="flex-1 h-px bg-border" />
        <span className="text-xs text-muted-foreground">or</span>
        <div className="flex-1 h-px bg-border" />
      </div>

      <form onSubmit={handleSignup} className="space-y-4">
        <div className="space-y-2">
          <label htmlFor="email" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Email
          </label>
          <Input
            id="email"
            type="email"
            placeholder="you@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="email"
            aria-invalid={!!error}
            aria-describedby={error ? 'signup-error' : undefined}
          />
        </div>

        <div className="space-y-2">
          <label htmlFor="password" className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
            Password
          </label>
          <Input
            id="password"
            type="password"
            placeholder="Min. 8 characters"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoComplete="new-password"
            aria-invalid={!!error}
            aria-describedby={error ? 'signup-error' : undefined}
          />
        </div>

        {error && <p id="signup-error" className="text-sm text-red-400" role="alert">{error}</p>}

        <Button type="submit" className="w-full glow-cyan-sm" disabled={loading}>
          {loading ? 'Creating account…' : 'Create account'}
        </Button>
      </form>

      <p className="text-center text-sm text-muted-foreground">
        Already have an account?{' '}
        <Link href="/login" className="text-primary hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
