---
name: cirqix-frontend-verify
description: >
  Vérifie visuellement le frontend Cirqix (apps/web) pour détecter les chevauchements d'éléments,
  overlaps, problèmes de layout, textes superposés, et bugs visuels dans les composants marketing
  et dashboard. Utilise Chrome DevTools MCP pour capturer des screenshots et inspecter chaque section.
  Invoquer OBLIGATOIREMENT quand : l'utilisateur signale un chevauchement, un overlap, un problème
  visuel, des éléments qui se superposent, du texte coupé, un layout cassé, ou quand il dit
  "quelque chose ne s'affiche pas bien", "il y a un bug visuel", "les éléments se chevauchent",
  "ça se superpose". Aussi invoquer après chaque modification de composant marketing ou dashboard
  pour valider qu'il n'y a pas de régression visuelle.
---

# Cirqix — Frontend Verify

## Objectif

Ce skill est un outil de **diagnostic visuel read-only** : il détecte les problèmes de chevauchement
et de layout, produit un rapport structuré, et propose des corrections ciblées — mais ne modifie
rien sans confirmation explicite.

---

## Étape 1 — Vérifier et démarrer le dev server

```bash
# Vérifier si le port 3333 est actif
curl -s -o /dev/null -w "%{http_code}" http://localhost:3333
```

Si le code retourné n'est pas `200` :
```bash
# Démarrer depuis la racine du monorepo
cd C:/Users/Mechegui/Desktop/dev/cirqix
pnpm dev
# Attendre ~10s que le serveur démarre
```

---

## Étape 2 — Capture des screenshots par breakpoint

Pour chaque page et chaque breakpoint, capturer un screenshot complet.

### Pages à vérifier
| Page | URL | Sections |
|------|-----|---------|
| Marketing | `http://localhost:3333` | Hero, Features, HowItWorks, Comparison, Pricing, Footer |
| Dashboard | `http://localhost:3333/dashboard` | Sidebar, Header, ChatPanel, ViewerPanel, CreditsBadge |

### Breakpoints
| Nom | Largeur | Hauteur |
|-----|---------|---------|
| Mobile | 375px | 812px |
| Tablet | 768px | 1024px |
| Desktop | 1440px | 900px |

### Séquence de capture

Pour chaque combinaison page × breakpoint :

1. **Naviguer** vers la page
2. **Redimensionner** la fenêtre au breakpoint
3. **Prendre le screenshot** (pleine page)
4. **Analyser visuellement** l'image immédiatement

Utiliser les outils Chrome DevTools MCP :
- `mcp__plugin_chrome-devtools-mcp_chrome-devtools__navigate_page` → naviguer
- `mcp__plugin_chrome-devtools-mcp_chrome-devtools__resize_page` → redimensionner
- `mcp__plugin_chrome-devtools-mcp_chrome-devtools__take_screenshot` → capturer

---

## Étape 3 — Analyse visuelle des screenshots

Pour chaque screenshot, inspecter les catégories suivantes.

### Catégories de problèmes à détecter

#### A. Chevauchements texte/éléments
- Texte qui déborde de son conteneur
- Deux éléments occupant la même zone (z-index conflict)
- Badge ou label superposé sur du contenu
- Image recouvrant du texte de façon non intentionnelle

#### B. Overflow et débordements
- Scroll horizontal non attendu (largeur > viewport)
- Élément sortant du bounding box de son parent
- Contenu coupé par `overflow: hidden` involontaire

#### C. Problèmes responsive
- Layout cassé sur mobile (colonnes trop larges, texte trop grand)
- Éléments qui disparaissent ou se superposent quand l'écran est petit
- Navigation ou header qui déborde sur le contenu

#### D. Espacement et alignement
- Marges/paddings incorrects créant un décalage
- Éléments mal centrés ou non alignés avec la grille
- Sections sans séparation visuelle claire

#### E. Typographie
- Texte tronqué avec `text-overflow: ellipsis` non voulu
- Line-height insuffisant causant des lignes qui se collent
- Font-size trop grand pour le conteneur mobile

---

## Étape 4 — Inspection CSS (pour les problèmes détectés)

Pour chaque problème détecté à l'étape 3, inspecter le code source pour confirmer la cause.

### Fichiers à lire selon la section

| Section | Fichier |
|---------|---------|
| Hero | `apps/web/src/components/marketing/Hero.tsx` |
| Features | `apps/web/src/components/marketing/Features.tsx` |
| HowItWorks | `apps/web/src/components/marketing/HowItWorks.tsx` |
| Comparison | `apps/web/src/components/marketing/Comparison.tsx` |
| Pricing | `apps/web/src/components/marketing/Pricing.tsx` |
| Footer | `apps/web/src/components/marketing/Footer.tsx` |
| Sidebar | `apps/web/src/components/dashboard/Sidebar.tsx` |
| Header | `apps/web/src/components/dashboard/Header.tsx` |
| ChatPanel | `apps/web/src/components/dashboard/ChatPanel.tsx` |
| ViewerPanel | `apps/web/src/components/dashboard/ViewerPanel.tsx` |
| CreditsBadge | `apps/web/src/components/dashboard/CreditsBadge.tsx` |
| StatusBadge | `apps/web/src/components/dashboard/StatusBadge.tsx` |

### Causes fréquentes à chercher dans le code

```
position: absolute / fixed sans z-index explicite
→ Chercher : className="...absolute..." ou className="...fixed..."

overflow: hidden coupant du contenu mobile
→ Chercher : className="...overflow-hidden..." sur des conteneurs parent

Largeur fixe sur mobile
→ Chercher : className="...w-[Xpx]..." ou style={{ width: 'Xpx' }}

z-index implicite (stacking context non géré)
→ Chercher : className="...z-..." ou transform/opacity sur des parents

Flexbox sans flex-wrap sur mobile
→ Chercher : className="...flex..." sans "flex-wrap" ou "flex-col"
```

---

## Étape 5 — Rapport de diagnostic

Produire un rapport structuré avec ce format exact :

```
## Rapport Cirqix Frontend Verify
Date : [date]
Pages analysées : Marketing (/), Dashboard (/dashboard)
Breakpoints testés : Mobile 375px | Tablet 768px | Desktop 1440px

---

### Problèmes détectés

#### CRITIQUE (bloquant — visible immédiatement)

| # | Composant | Fichier | Breakpoint | Description | Cause probable |
|---|-----------|---------|------------|-------------|----------------|
| 1 | Hero | Hero.tsx | Mobile 375px | Titre H1 déborde hors du viewport | `text-7xl` sans responsive → ajouter `text-4xl md:text-7xl` |

#### MOYEN (dégradation visible)

| # | Composant | Fichier | Breakpoint | Description | Cause probable |
|---|-----------|---------|------------|-------------|----------------|

#### MINEUR (esthétique)

| # | Composant | Fichier | Breakpoint | Description | Cause probable |
|---|-----------|---------|------------|-------------|----------------|

---

### Corrections proposées

Pour chaque problème CRITIQUE ou MOYEN, proposer le diff exact :

**Problème #1 — Hero.tsx titre trop grand mobile**
```diff
- className="text-7xl font-extrabold"
+ className="text-4xl md:text-6xl xl:text-7xl font-extrabold"
```

---

### Résumé
- Total problèmes : X (Y critiques, Z moyens, W mineurs)
- Composants affectés : [liste]
- Action recommandée : [corriger / surveiller / OK]
```

---

## Étape 6 — Application des corrections (avec confirmation)

Ce skill ne modifie **rien** automatiquement.

Après le rapport, demander :

```
Voulez-vous que j'applique les corrections ?
- [A] Toutes les corrections CRITIQUES uniquement
- [B] Toutes les corrections (CRITIQUES + MOYENS)
- [C] Me montrer chaque correction une par une
- [D] Non, je les fais moi-même
```

Si l'utilisateur choisit A, B ou C → appliquer les corrections en respectant :
- Design system `docs/design/design-system.md` (couleurs, spacing, typo)
- Tailwind classes uniquement — pas de CSS inline
- Ne pas toucher à la logique, seulement aux classes CSS/layout
- Vérifier `pnpm type-check` après chaque correction

---

## Contexte design system Cirqix

Références obligatoires avant de proposer des corrections :

**Couleurs principales**
```
Background : #080808 (page) / #111111 (cards)
Borders : #2E2E2E (normal) / #3D3D3D (hover)
Text : #FFFFFF (primary) / #A1A1AA (secondary) / #71717A (muted)
Accent : #00C2FF (cyan) / #E07B39 (copper)
```

**Breakpoints Tailwind**
```
sm : 640px
md : 768px
lg : 1024px
xl : 1280px
2xl : 1536px
```

**Patterns responsive corrects pour Cirqix**
```tsx
// Texte responsive
className="text-3xl md:text-5xl xl:text-7xl"

// Grid responsive
className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3"

// Flex responsive
className="flex flex-col md:flex-row"

// Padding responsive
className="px-4 md:px-8 xl:px-16"
```

---

## Règles du skill

- **NEVER** modifier des fichiers sans confirmation explicite de l'utilisateur
- **NEVER** changer la logique ou les props — seulement les classes CSS/layout
- **ALWAYS** tester les 3 breakpoints même si l'utilisateur mentionne seulement un problème
- **ALWAYS** vérifier le dashboard ET le marketing, les problèmes se propagent souvent
- **ALWAYS** proposer des corrections Tailwind natives — pas de styles inline
