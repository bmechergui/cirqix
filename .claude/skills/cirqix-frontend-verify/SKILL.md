---
name: cirqix-frontend-verify
description: >
  Diagnostic visuel du frontend Cirqix (apps/web) par captures Chrome DevTools : chevauchements,
  débordements, texte coupé, mise en page cassée ou régressions responsive sur les pages marketing et
  dashboard. À invoquer quand l'utilisateur signale un défaut d'affichage, et après une modification de
  mise en page d'un composant marketing ou dashboard.
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

Si le code retourné n'est pas `200`, lancer `pnpm dev` depuis la racine du dépôt ou du worktree courant (port 3333), puis attendre que le serveur réponde.

---

## Étape 2 — Capture des screenshots par breakpoint

Pour chaque page et chaque breakpoint, capturer un screenshot complet.

### Pages à vérifier
| Page | URL | Sections |
|------|-----|---------|
| Marketing | `http://localhost:3333` | Hero, Features, HowItWorks, Comparison, Pricing, Footer |
| Dashboard | `http://localhost:3333/dashboard` | Sidebar, Header, ChatRail, viewer, CreditsBadge |

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

### Où chercher le code d'une section

- Marketing : `apps/web/src/features/marketing/ui/` (Hero, Features, HowItWorks, Comparison, Pricing, Footer, Navbar)
- Dashboard : `apps/web/src/features/dashboard/ui/` (Sidebar, Header, CreditsBadge, StatusBadge…)
- Espace de travail : `apps/web/src/features/workspace/ui/` (ChatRail…)
- Viewer : `apps/web/src/widgets/viewer/ui/`

En cas de doute, chercher le composant par son nom plutôt que de supposer un chemin.

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

## Contexte design system

Avant de proposer une correction, lire `docs/design/design-system.md` (couleurs, espacements) et la section « Responsive — Règles obligatoires » de `CLAUDE.md` (tailles de titres, grilles). Ne pas recopier de valeurs ici. Dans le rapport, les exemples de diff sont illustratifs : la correction réelle suit ces deux sources.

---

## En résumé

Lecture seule jusqu'à confirmation ; les corrections ne touchent qu'aux classes Tailwind de mise en page, jamais à la logique ni aux props ; un défaut signalé sur un breakpoint ou une page se vérifie sur les trois breakpoints et les deux pages, car ils partagent des composants.
