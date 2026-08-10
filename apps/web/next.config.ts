import type { NextConfig } from 'next';
import path from 'path';

// ---------------------------------------------------------------------------
// Headers de sécurité (PLAN.md §5.1)
//
// CSP : 'unsafe-inline'/'unsafe-eval' sont requis par Next.js (scripts inline
// d'hydratation) ; 'wasm-unsafe-eval' et https://kicanvas.org par le viewer
// KiCanvas (script chargé dynamiquement depuis le CDN kicanvas.org +
// assets WASM internes). Supabase est autorisé en connect (REST + Realtime
// wss) et en img (Storage, signed URLs). frame-ancestors 'none' =
// équivalent moderne de X-Frame-Options: DENY (gardé pour les vieux
// navigateurs). HSTS uniquement en production : le poser en dev casserait
// http://localhost.
// ---------------------------------------------------------------------------

const csp = [
  "default-src 'self'",
  "script-src 'self' 'unsafe-inline' 'unsafe-eval' 'wasm-unsafe-eval' https://kicanvas.org",
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data: blob: https://*.supabase.co",
  "font-src 'self' data:",
  "connect-src 'self' https://*.supabase.co wss://*.supabase.co https://kicanvas.org",
  "worker-src 'self' blob:",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "base-uri 'self'",
  "form-action 'self'",
].join('; ');

const securityHeaders = [
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
  { key: 'Content-Security-Policy', value: csp },
  ...(process.env.NODE_ENV === 'production'
    ? [{ key: 'Strict-Transport-Security', value: 'max-age=63072000; includeSubDomains; preload' }]
    : []),
];

const nextConfig: NextConfig = {
  transpilePackages: ['@cirqix/db', '@cirqix/agents'],
  outputFileTracingRoot: path.join(__dirname, '../../'),
  async headers() {
    return [{ source: '/:path*', headers: securityHeaders }];
  },
};

export default nextConfig;
