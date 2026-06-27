import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: ['class'],
  content: ['./src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        background: '#080808',
        foreground: '#ffffff',
        card: { DEFAULT: '#111111', foreground: '#ffffff' },
        popover: { DEFAULT: '#111111', foreground: '#ffffff' },
        primary: { DEFAULT: '#00C2FF', foreground: '#080808' },
        secondary: { DEFAULT: '#1a1a1a', foreground: '#ffffff' },
        muted: { DEFAULT: '#1a1a1a', foreground: '#71717a' },
        accent: { DEFAULT: '#D4820A', foreground: '#080808' },
        destructive: { DEFAULT: '#ef4444', foreground: '#ffffff' },
        border: '#2e2e2e',
        input: '#2e2e2e',
        ring: '#00C2FF',
        // Cirqix custom
        'bg-base': '#080808',
        'bg-1': '#111111',
        'bg-2': '#1a1a1a',
        'bg-3': '#242424',
        'border-hi': '#3d3d3d',
        cyan: {
          400: '#00C2FF',
          500: '#00A3D9',
          600: '#0082AD',
        },
        copper: {
          400: '#D4820A',
          500: '#B06A08',
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
        'glow-cyan': '0 0 20px rgba(0,194,255,0.35)',
        'glow-cyan-sm': '0 0 10px rgba(0,194,255,0.2)',
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
