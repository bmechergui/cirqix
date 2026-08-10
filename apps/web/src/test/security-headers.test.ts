import { describe, it, expect } from 'vitest';
import nextConfig from '../../next.config';

// PLAN.md §5.1 : headers CSP, HSTS, X-Frame-Options sur toutes les routes.

describe('next.config security headers', () => {
  it('expose une règle de headers globale', async () => {
    expect(nextConfig.headers).toBeTypeOf('function');
    const rules = await nextConfig.headers!();
    const global = rules.find((r) => r.source === '/:path*');
    expect(global).toBeDefined();
  });

  it('pose les headers de sécurité obligatoires', async () => {
    const rules = await nextConfig.headers!();
    const global = rules.find((r) => r.source === '/:path*')!;
    const keys = global.headers.map((h) => h.key);

    expect(keys).toContain('X-Frame-Options');
    expect(keys).toContain('X-Content-Type-Options');
    expect(keys).toContain('Referrer-Policy');
    expect(keys).toContain('Permissions-Policy');
    expect(keys).toContain('Content-Security-Policy');
  });

  it('X-Frame-Options vaut DENY et X-Content-Type-Options nosniff', async () => {
    const rules = await nextConfig.headers!();
    const global = rules.find((r) => r.source === '/:path*')!;
    const get = (k: string) => global.headers.find((h) => h.key === k)?.value;

    expect(get('X-Frame-Options')).toBe('DENY');
    expect(get('X-Content-Type-Options')).toBe('nosniff');
  });

  it('la CSP restreint frame-ancestors et autorise Supabase + WASM (viewer 3D)', async () => {
    const rules = await nextConfig.headers!();
    const global = rules.find((r) => r.source === '/:path*')!;
    const csp = global.headers.find((h) => h.key === 'Content-Security-Policy')!.value;

    expect(csp).toContain("default-src 'self'");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain('https://*.supabase.co');
    expect(csp).toContain('wss://*.supabase.co');
    expect(csp).toContain('wasm-unsafe-eval');
  });

  it('autorise le CDN KiCanvas (script + assets WASM du viewer)', async () => {
    const rules = await nextConfig.headers!();
    const global = rules.find((r) => r.source === '/:path*')!;
    const csp = global.headers.find((h) => h.key === 'Content-Security-Policy')!.value;
    const scriptSrc = csp.split(';').find((d) => d.trim().startsWith('script-src'))!;
    const connectSrc = csp.split(';').find((d) => d.trim().startsWith('connect-src'))!;

    expect(scriptSrc).toContain('https://kicanvas.org');
    expect(connectSrc).toContain('https://kicanvas.org');
  });
});
