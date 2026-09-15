import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class'],
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Noir et blanc (2026-09-15) — fond noir pur, marque monochrome, dans
        // l'esprit de x.ai / Grok. Les noms `cyan` / `copper` restent pour ne pas
        // toucher 47 fichiers : ce sont des RÔLES (marque, accent), plus des teintes.
        background: '#000000',
        foreground: '#ffffff',
        card: { DEFAULT: '#0a0a0a', foreground: '#ffffff' },
        popover: { DEFAULT: '#0a0a0a', foreground: '#ffffff' },
        primary: { DEFAULT: '#ffffff', foreground: '#000000' },
        secondary: { DEFAULT: '#141414', foreground: '#ffffff' },
        muted: { DEFAULT: '#141414', foreground: '#8a8a8a' },
        accent: { DEFAULT: '#a3a3a3', foreground: '#000000' },
        destructive: { DEFAULT: '#ef4444', foreground: '#ffffff' },
        border: '#262626',
        input: '#262626',
        ring: '#ffffff',
        // Cirqix custom
        'bg-base': '#000000',
        'bg-1': '#0a0a0a',
        'bg-2': '#141414',
        'bg-3': '#1f1f1f',
        'border-hi': '#3a3a3a',
        cyan: {
          400: '#ffffff',
          500: '#d4d4d4',
          600: '#a3a3a3',
        },
        copper: {
          400: '#a3a3a3',
          500: '#737373',
        },
        success: '#22C55E',
        warning: '#F59E0B',
      },
      borderRadius: {
        lg: '12px',
        md: '8px',
        sm: '6px',
      },
      fontFamily: {
        sans: ['var(--font-geist-sans)', 'system-ui', 'sans-serif'],
        mono: ['var(--font-geist-mono)', 'monospace'],
        display: ['var(--font-syne)', 'system-ui', 'sans-serif'],
      },
      boxShadow: {
        'glow-cyan': '0 0 20px rgba(255,255,255,0.18)',
        'glow-cyan-sm': '0 0 10px rgba(255,255,255,0.1)',
      },
      keyframes: {
        blink: { '0%,100%': { opacity: '1' }, '50%': { opacity: '0' } },
        'pulse-slow': { '0%,100%': { opacity: '1' }, '50%': { opacity: '0.4' } },
        scan: { '0%': { transform: 'translateY(-100%)' }, '100%': { transform: 'translateY(100vh)' } },
        'trace-in': { '0%': { strokeDashoffset: '1000' }, '100%': { strokeDashoffset: '0' } },
        flicker: { '0%,100%': { opacity: '1' }, '92%': { opacity: '1' }, '93%': { opacity: '0.4' }, '94%': { opacity: '1' } },
        float: { '0%,100%': { transform: 'translateY(0)' }, '50%': { transform: 'translateY(-6px)' } },
      },
      animation: {
        blink: 'blink 1s step-end infinite',
        'pulse-slow': 'pulse-slow 2s ease-in-out infinite',
        scan: 'scan 8s linear infinite',
        flicker: 'flicker 6s ease-in-out infinite',
        float: 'float 4s ease-in-out infinite',
      },
    },
  },
  plugins: [],
};

export default config;
