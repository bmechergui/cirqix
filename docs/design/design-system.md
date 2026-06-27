# Cirqix.ai — Design System

> Inspiré du logo : fond noir PCB, traces de circuit, typographie géométrique bold, étincelle IA.
> Dark mode first. Précision technique. Premium accessible.

---

## 1. Identité visuelle

### Concept
Le logo dit tout : **noir PCB + blanc pur + traces de circuit + étincelle IA**.
L'interface est une extension du logo — une carte mère élégante où chaque élément
a une raison d'être, comme chaque piste sur un PCB.

### Mots-clés design
`Précision` · `Profondeur` · `Électrique` · `Minimal` · `Hardware meets AI`

---

## 2. Couleurs

### Palette principale

```
Background  #080808   ← Noir PCB (fond de la carte)
Surface-1   #111111   ← Cartes, modales, panels
Surface-2   #1A1A1A   ← Hover states, inputs
Surface-3   #242424   ← Séparateurs, borders subtils
Border      #2E2E2E   ← Borders des composants
Border-hi   #3D3D3D   ← Borders en focus/hover
```

### Accent — Cyan électrique (IA + précision)
```
Cyan-50     #E0FAFE
Cyan-100    #B3F4FD
Cyan-200    #66E8FB
Cyan-300    #1AD9F8
Cyan-400    #00C2FF   ← Primary brand color (CTA, links, actif)
Cyan-500    #00A3D9   ← Hover
Cyan-600    #0082AD   ← Active / pressed
```

### Copper — Cuivre PCB (accent secondaire)
```
Copper-300  #F0A855
Copper-400  #D4820A   ← Badges, highlights, traces PCB
Copper-500  #B06A08
```

### Semantic
```
Success     #22C55E   ← DRC clean, PCB validé (vert PCB)
Warning     #F59E0B   ← Warnings DRC
Error       #EF4444   ← Violations DRC, erreurs
Info        #00C2FF   ← Info (= cyan brand)
```

### Texte
```
Text-primary    #FFFFFF   ← Titres, contenu principal
Text-secondary  #A1A1AA   ← Labels, descriptions
Text-muted      #71717A   ← Placeholders, disabled
Text-disabled   #3F3F46
```

### Variables CSS (Tailwind + CSS custom properties)

```css
:root {
  /* Backgrounds */
  --bg-base: #080808;
  --bg-surface-1: #111111;
  --bg-surface-2: #1A1A1A;
  --bg-surface-3: #242424;

  /* Borders */
  --border: #2E2E2E;
  --border-hi: #3D3D3D;

  /* Brand */
  --cyan: #00C2FF;
  --cyan-hover: #00A3D9;
  --copper: #D4820A;

  /* Text */
  --text-primary: #FFFFFF;
  --text-secondary: #A1A1AA;
  --text-muted: #71717A;

  /* Semantic */
  --success: #22C55E;
  --warning: #F59E0B;
  --error: #EF4444;
}
```

### Extension Tailwind

```js
// tailwind.config.ts
export default {
  theme: {
    extend: {
      colors: {
        bg: {
          base: '#080808',
          1: '#111111',
          2: '#1A1A1A',
          3: '#242424',
        },
        border: {
          DEFAULT: '#2E2E2E',
          hi: '#3D3D3D',
        },
        cyan: {
          400: '#00C2FF',
          500: '#00A3D9',
          600: '#0082AD',
        },
        copper: {
          400: '#D4820A',
          500: '#B06A08',
        },
        text: {
          primary: '#FFFFFF',
          secondary: '#A1A1AA',
          muted: '#71717A',
        },
      },
    },
  },
}
```

---

## 3. Typographie

### Fonts

| Usage | Font | Raison |
|-------|------|--------|
| UI principale | **Geist Sans** (Vercel) | Géométrique, lisible, moderne |
| Code / agents | **Geist Mono** | Cohérence Geist, lisibilité code |
| Fallback | `system-ui, sans-serif` | Performance |

```css
/* next/font/local ou Google Fonts */
font-family: 'Geist', 'Inter', system-ui, sans-serif;
font-family: 'Geist Mono', 'JetBrains Mono', monospace; /* code */
```

### Scale typographique

```
Display     72px / bold 800 / tracking -0.04em   ← Hero landing
H1          48px / bold 700 / tracking -0.03em
H2          36px / semibold 600 / tracking -0.02em
H3          24px / semibold 600 / tracking -0.01em
H4          20px / semibold 600
Body-lg     18px / regular 400 / leading 1.7
Body        16px / regular 400 / leading 1.6
Body-sm     14px / regular 400 / leading 1.5
Caption     12px / medium 500 / tracking +0.02em
Code        14px / mono / leading 1.8
```

### Tailwind classes

```
text-7xl font-extrabold tracking-tighter   → Display
text-5xl font-bold tracking-tight          → H1
text-4xl font-semibold tracking-tight      → H2
text-2xl font-semibold                     → H3
text-xl font-semibold                      → H4
text-lg leading-relaxed                    → Body-lg
text-base leading-relaxed                  → Body
text-sm leading-relaxed                    → Body-sm
text-xs font-medium tracking-wide          → Caption
text-sm font-mono                          → Code
```

---

## 4. Spacing & Layout

### Grid
- Landing : max-width `1280px`, padding `0 24px`
- Dashboard : sidebar `240px` fixe + contenu fluid
- Gutter : `24px` (desktop), `16px` (mobile)

### Spacing scale (Tailwind default — respecter strictement)
```
4px   → gap-1, p-1    (micro)
8px   → gap-2, p-2    (tiny)
12px  → gap-3, p-3
16px  → gap-4, p-4    (base)
24px  → gap-6, p-6    (section interne)
32px  → gap-8, p-8
48px  → gap-12, p-12  (section)
64px  → gap-16, p-16  (grande section)
96px  → gap-24, p-24  (hero spacing)
```

### Border radius
```
rounded-sm    → 4px   (badges, tags)
rounded       → 6px   (boutons, inputs)
rounded-md    → 8px   (cartes)
rounded-lg    → 12px  (panels, modales)
rounded-xl    → 16px  (grandes cartes)
rounded-full  →       (avatars, pills)
```

---

## 5. Composants

### Button

```tsx
// Variants
<Button variant="primary">   → bg-cyan-400 text-black hover:bg-cyan-500
<Button variant="secondary"> → bg-bg-2 border border-border text-white hover:border-border-hi
<Button variant="ghost">     → transparent hover:bg-bg-2
<Button variant="danger">    → bg-error/10 text-error hover:bg-error/20 border border-error/30

// Sizes
<Button size="sm">  → h-8  px-3 text-sm
<Button size="md">  → h-10 px-4 text-sm  (default)
<Button size="lg">  → h-12 px-6 text-base

// Exemples CSS
.btn-primary {
  @apply bg-cyan-400 text-black font-semibold rounded
         hover:bg-cyan-500 active:bg-cyan-600
         transition-colors duration-150;
}
.btn-secondary {
  @apply bg-bg-2 border border-border text-white font-medium rounded
         hover:border-border-hi hover:bg-bg-3
         transition-all duration-150;
}
```

### Input / Textarea

```tsx
// Style de base
className="
  w-full bg-bg-2 border border-border rounded
  text-white placeholder:text-text-muted
  px-3 py-2 text-sm
  focus:outline-none focus:border-cyan-400 focus:ring-1 focus:ring-cyan-400/30
  transition-colors duration-150
"
```

### Card

```tsx
// Base card
className="bg-bg-1 border border-border rounded-lg p-6"

// Card interactive (projet, footprint)
className="
  bg-bg-1 border border-border rounded-lg p-6
  hover:border-border-hi hover:bg-bg-2
  cursor-pointer transition-all duration-200
"

// Card highlight (feature landing)
className="
  bg-bg-1 border border-cyan-400/20 rounded-xl p-8
  hover:border-cyan-400/40
  transition-all duration-300
"
```

### Badge / Status

```tsx
// DRC Clean
<Badge variant="success">DRC Clean</Badge>
className="bg-success/10 text-success border border-success/20 text-xs font-medium px-2 py-0.5 rounded-full"

// En cours
<Badge variant="info">Routing...</Badge>
className="bg-cyan-400/10 text-cyan-400 border border-cyan-400/20 ..."

// Erreur
<Badge variant="error">2 violations</Badge>
className="bg-error/10 text-error border border-error/20 ..."

// Footprint source
<Badge variant="copper">IA Generated</Badge>
className="bg-copper-400/10 text-copper-400 border border-copper-400/20 ..."
```

### Agent Progress Bar

```tsx
// Barre de progression de l'agent (states PCB)
const states = ['SCHEMA', 'PLACEMENT', 'ROUTING', 'DRC', 'EXPORT']
// Chaque step = segment de circuit trace (SVG animé)
// Couleur active : cyan-400
// Couleur done : cyan-600
// Couleur pending : border/30
```

### Chat / Agent Stream

```tsx
// Message utilisateur
className="bg-bg-2 rounded-lg rounded-br-sm px-4 py-3 max-w-[80%] ml-auto text-sm"

// Message agent
className="bg-bg-1 border border-border rounded-lg rounded-bl-sm px-4 py-3 max-w-[90%] text-sm"

// Token streaming cursor
className="inline-block w-0.5 h-4 bg-cyan-400 animate-pulse ml-0.5"

// Code block dans agent message
className="bg-bg-base border border-border rounded-md p-4 font-mono text-xs text-cyan-300 overflow-x-auto my-2"
```

### Sidebar Dashboard

```tsx
// Layout
className="w-60 flex-shrink-0 bg-bg-1 border-r border-border h-screen flex flex-col"

// Nav item
className="flex items-center gap-3 px-3 py-2 rounded text-text-secondary hover:text-white hover:bg-bg-2 text-sm transition-colors"

// Nav item actif
className="flex items-center gap-3 px-3 py-2 rounded text-white bg-bg-2 border-l-2 border-cyan-400 text-sm"

// Compteur crédits (bas de sidebar)
className="p-4 border-t border-border"
// → affiche solde crédits + barre de progression + "Upgrade" CTA
```

---

## 6. Effets & Animations

### Glow cyan (CTA, éléments actifs)
```css
.glow-cyan {
  box-shadow: 0 0 20px rgba(0, 194, 255, 0.15),
              0 0 40px rgba(0, 194, 255, 0.05);
}
.glow-cyan-strong {
  box-shadow: 0 0 30px rgba(0, 194, 255, 0.3),
              0 0 60px rgba(0, 194, 255, 0.1);
}
```

### Glow copper (accents PCB)
```css
.glow-copper {
  box-shadow: 0 0 20px rgba(212, 130, 10, 0.2),
              0 0 40px rgba(212, 130, 10, 0.05);
}
```

### Gradient brand (hero, CTA section)
```css
.gradient-brand {
  background: linear-gradient(135deg, #080808 0%, #0a1520 50%, #080808 100%);
}
.gradient-text {
  background: linear-gradient(90deg, #00C2FF, #D4820A);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
}
```

### PCB Grid (fond hero landing)
```css
.pcb-grid {
  background-image:
    linear-gradient(rgba(0,194,255,0.04) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,194,255,0.04) 1px, transparent 1px);
  background-size: 40px 40px;
}
```

### Circuit trace animation (loading agent)
```css
@keyframes trace {
  0%   { stroke-dashoffset: 100; opacity: 0.3; }
  50%  { opacity: 1; }
  100% { stroke-dashoffset: 0; opacity: 0.3; }
}
.circuit-trace {
  stroke-dasharray: 100;
  animation: trace 2s ease-in-out infinite;
}
```

### Transitions standard
```css
transition-colors duration-150   → couleurs (hover)
transition-all duration-200      → layout (cartes)
transition-opacity duration-300  → apparition
```

---

## 7. Icônes

- Librairie : **Lucide React** (`lucide-react`)
- Taille standard : `16px` (sm), `20px` (base), `24px` (lg)
- Couleur : hérite du texte parent
- Stroke width : `1.5` (default Lucide, garder)
- Icônes PCB custom (traces, vias, layers) : SVG inline dans `packages/ui/src/icons/`

### Icônes métier clés
```
Layers        → couches PCB
Cpu           → agent / schéma
Zap           → routage / vitesse
CheckCircle   → DRC clean
AlertTriangle → warning DRC
XCircle       → erreur
Package       → export / BOM
Sparkles      → IA / génération
Box           → vue 3D
Download      → export Gerber
```

---

## 8. PCB Viewer — tokens visuels

### Couleurs des layers (standard KiCad)
```
F.Cu (cuivre avant)  → #D4820A   (copper)
B.Cu (cuivre arrière)→ #4488FF   (bleu)
F.SilkS              → #CCCCCC   (gris clair)
B.SilkS              → #999999
F.Mask               → rgba(212,130,10,0.3)
B.Mask               → rgba(68,136,255,0.3)
Edge.Cuts (contour)  → #FFFF00   (jaune)
DRC violation        → #EF4444   (rouge, clignotant)
Sélection            → #00C2FF   (cyan brand)
Courtyard            → rgba(255,255,0,0.15)
```

### Fond viewer
```
Viewer 2D : #0D0D0D  (légèrement plus clair que bg-base)
Viewer 3D : #0A0A0A  (noir profond, éclairage Three.js)
```

---

## 9. Landing page — structure visuelle

```
┌─────────────────────────────────────┐
│  Nav : Logo + liens + CTA "Waitlist"│  bg-base, border-b border/30, backdrop-blur
├─────────────────────────────────────┤
│  HERO                               │  bg-base + pcb-grid overlay
│  Eyebrow : "AI PCB Design Agent"    │  text-cyan-400 text-sm uppercase tracking-widest
│  H1 : "Every layer, perfectly..."   │  text-7xl font-extrabold + gradient-text
│  Subtitle                           │  text-text-secondary text-xl
│  CTA : "Join Waitlist" + "Watch demo│  btn-primary (glow-cyan) + btn-ghost
│  Hero visual : PCB animé PixiJS     │  viewer 2D avec traces qui s'animent
├─────────────────────────────────────┤
│  SOCIAL PROOF                       │  "Trusted by 2,000+ engineers on the waitlist"
├─────────────────────────────────────┤
│  FEATURES (3 colonnes)              │  Cards avec border-cyan/20 + icônes
│  Agent autonome / Viewer 2D-3D /    │
│  Footprint auto / JLCPCB / SPICE    │
├─────────────────────────────────────┤
│  HOW IT WORKS (steps)               │  Ligne de circuit trace reliant les steps
│  1. Décris → 2. Agent PCB → 3.Send  │
├─────────────────────────────────────┤
│  PRICING                            │  Free / Maker / Pro — card active = border-cyan
├─────────────────────────────────────┤
│  COMPARATIF TABLE                   │  bg-bg-1, checkmarks cyan, X rouge
├─────────────────────────────────────┤
│  CTA FINAL                          │  gradient-brand, glow-cyan-strong
├─────────────────────────────────────┤
│  FOOTER                             │  bg-bg-1 border-t border-border
└─────────────────────────────────────┘
```

---

## 10. Dashboard — structure visuelle

```
┌──────────┬──────────────────────────────────────┐
│ SIDEBAR  │ HEADER : breadcrumb + crédits + user  │
│ 240px    ├──────────────────────────────────────┤
│          │ CONTENU selon la route               │
│ Logo     │                                      │
│ ──────   │  /dashboard         → liste projets  │
│ Projets  │  /projects/[id]     → chat + viewer  │
│ Footprints│  /footprints        → librairie      │
│ Settings │  /billing           → plans/crédits  │
│          │                                      │
│ ──────   │                                      │
│ Crédits  │                                      │
│ [====  ] │                                      │
│ 47 / 100 │                                      │
│ Upgrade→ │                                      │
└──────────┴──────────────────────────────────────┘
```

### Page projet `/projects/[id]`
```
┌──────────────────────┬─────────────────────────┐
│ CHAT PANEL (40%)     │ VIEWER PANEL (60%)       │
│                      │                          │
│ Agent progress bar   │ [PCB Viewer PixiJS]      │
│ SCHEMA ● PLACE ● ... │                          │
│                      │ Layer toggles toolbar    │
│ Message history      │ F.Cu B.Cu SilkS ...      │
│                      │                          │
│ [Input + Send]       │ Infos composant sidebar  │
│ 47 crédits restants  │ + DRC violations list    │
└──────────────────────┴─────────────────────────┘
```

---

## 11. Tokens Tailwind — cheatsheet rapide

```
Fond page          : bg-[#080808]
Fond carte         : bg-[#111111]
Fond hover         : bg-[#1A1A1A]
Border             : border-[#2E2E2E]
Border hover       : border-[#3D3D3D]
Texte principal    : text-white
Texte secondaire   : text-[#A1A1AA]
Texte muet         : text-[#71717A]
Brand cyan         : text-[#00C2FF] bg-[#00C2FF]
Copper             : text-[#D4820A] bg-[#D4820A]
Succès             : text-green-500 bg-green-500
Erreur             : text-red-500 bg-red-500
Warning            : text-amber-500 bg-amber-500
```

---

*Design System — Cirqix.ai — v1.0 — 2026-03-27*
