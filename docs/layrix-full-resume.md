# ⬡ Layrix.ai — Résumé complet startup

---

## IDENTITÉ

- Nom : Layrix.ai
- Prononciation : "Lay-rix"
- Signification : Layer (couche PCB) + -ix (tech)
- Domaine : layrix.ai — Cloudflare ~33$/an
- Tagline : "Every layer, perfectly designed by AI"
- Positionnement : La puissance d'Altium sans payer 3000€/an

---

## LAYRIX EST UN AGENT — PAS UN CHATBOT

Un chatbot répond à des questions. Un agent agit dans le monde réel.

Layrix est un agent IA autonome qui reçoit un objectif ("crée ce PCB") et exécute toutes les étapes nécessaires jusqu'au résultat final sans intervention humaine — il planifie, appelle des outils, observe les résultats, corrige les erreurs, et boucle jusqu'à obtenir un PCB DRC-clean prêt à fabriquer. Il peut même commander la fabrication directement chez JLCPCB sans quitter le chat.

Boucle agentique complète :
Percevoir → Planifier → Agir → Observer → Corriger → Recommencer
jusqu'à DRC propre + Gerbers exportés + commande JLCPCB ✅

---

## LE PRODUIT

- Concept : SaaS web 100% cloud de conception PCB via langage naturel
- Moteur PCB : Circuit-Synth (Python, génère .kicad_sch + .kicad_pcb natifs) + KiCad (pro multi-couches)
- Routage auto : Freerouting (Java, dockerisé)
- Couches : 2 à 8 couches selon le plan
- Exports : .kicad_pcb + .kicad_sch + Gerber + BOM + PDF + STEP 3D
- Viewer Schéma + PCB : KiCanvas (rendu natif KiCad dans le navigateur)
- Viewer 3D : Three.js (fichier STEP, rotation libre)
- Zéro installation requise

---

## STRATÉGIE CIRCUIT-SYNTH + KICAD — 100% INVISIBLE

L'utilisateur ne sait jamais quel moteur tourne derrière.
Le pipeline génère des fichiers KiCad natifs :

- **Circuit-Synth** → Claude génère du code Python → KiCad Docker exécute → `.kicad_sch` + `.kicad_pcb` réels
- Routage différentiel, 4+ couches, plan Pro → **KiCad + Freerouting + pcbnew** natif
- **Viewer** : KiCanvas charge les fichiers `.kicad_sch` / `.kicad_pcb` depuis Supabase Storage

Résultat : fichiers KiCad natifs + Gerbers standard ✅

---

## FOOTPRINT INTROUVABLE — LAYRIX GÉNÈRE AUTOMATIQUEMENT

Cascade de recherche de l'agent Footprint (8 étapes) :

1. Cherche dans librairies KiCad officielles
2. Cherche sur SnapMagic API (millions de composants)
3. Cherche sur Octopart (Digi-Key, Mouser, LCSC)
4. Télécharge la datasheet PDF depuis le web
5. Claude Vision lit les dimensions du package
6. Génère le fichier .kicad_mod complet
7. Valide les dimensions vs datasheet
8. Sauvegarde dans la librairie privée de l'utilisateur ✅

Génération footprint = 3 crédits (plan Maker+)

### Dashboard Footprint Library (app.layrix.ai/footprints)

Chaque utilisateur a sa propre librairie privée de footprints :

- Badge source : KiCad officiel / SnapMagic / Octopart / Généré IA Claude
- Viewer inline PixiJS : aperçu 2D pads + courtyard + silkscreen
- Validation manuelle : l'utilisateur confirme les dimensions
- Librairie communautaire : footprints validés partagés avec tous les users → effet de réseau
- Recherche sémantique pgvector : "régulateur 3.3V QFN" → trouve les footprints correspondants
- Export .kicad_mod : plan Pro uniquement

Plus il y a d'utilisateurs → plus la librairie est complète → avantage compétitif défendable.

---

## CLAUDE API — UTILISATION DÉTAILLÉE

### 3 modes d'utilisation :

1. Messages API — boucle agentique principale
   - Appels successifs avec tool calling
   - stop_reason "tool_use" → exécute le tool → réinjecte résultat → reboucle
   - stop_reason "end_turn" → PCB livré ✅
   - Max 15 itérations par projet

2. Streaming API — chat temps réel
   - Tokens envoyés mot par mot via WebSocket
   - Même expérience que Claude.ai

3. Vision API — lecture datasheets PDF
   - Document base64 injecté dans le message
   - Agent extrait dimensions et génère le footprint KiCad automatiquement

### Tokens consommés par PCB complet :

- Orchestrateur Sonnet : ~5 000 input + ~1 000 output
- Agent Schéma Haiku : ~2 000 input + ~500 output
- Agent Placement Haiku : ~3 000 input + ~500 output
- Agent Routage Haiku : ~2 000 input + ~300 output
- Agent DRC ×3 Haiku : ~1 500 input + ~300 output
- Agent Export Haiku : ~1 000 input + ~200 output
- TOTAL : ~30 000 tokens → ~0.12€ ✅

### Gestion du contexte agent :

Contexte session stocké dans Redis :
- État courant du PCB (composants, traces, violations DRC)
- Historique complet messages Claude (jusqu'à 30 tours)
- Décisions prises
- Fichiers générés sur Supabase Storage

Compression intelligente : après 10 appels, Claude Haiku résume les anciens tours → garde résumé + 5 derniers tours → -60% coûts sur projets longs.

Gestion des erreurs : l'agent ne s'arrête jamais sur une erreur DRC — il corrige et reboucle jusqu'à maxIterations (15).

---

## 6 AGENTS IA CLAUDE

- Orchestrateur : Claude Sonnet — planifie et délègue
- Agent Schéma : Claude Haiku — génère le netlist JSON
- Agent Placement : Claude Haiku — place les composants (condensateurs < 2mm des VCC, cristal < 10mm MCU)
- Agent Routage : Claude Haiku — pilote Freerouting (angles 45°, plans de masse, paires diff)
- Agent DRC : Claude Haiku — vérifie les règles + correction auto
- Agent Footprint : Claude Haiku — cascade 8 étapes + génération IA depuis datasheet

Coût total : ~0.12€ par PCB complet.
Pas de fine-tuning nécessaire — system prompt + RAG suffisent.

### Exemple prompt structuré — Agent Sélection Composants :

L'agent répond en JSON strict avec : part_number, manufacturer, description, price_lcsc, stock_lcsc, footprint, key_specs, why_good, datasheet_url, tscircuit_import.

---

## FREEROUTING — ROUTAGE AUTOMATIQUE

- Routeur automatique open source en Java
- Reçoit fichier .dsn → route toutes les pistes → retourne .ses réimporté dans KiCad
- Supporte : multi-couches, impédance, paires différentielles, ground pour
- Temps : 30–90 sec (PCB simple) | 3–10 min (8 couches complexe)
- Docker isolé par job utilisateur
- Agent DRC revalide systématiquement après chaque routage

---

## PCBNEW — API PYTHON KICAD

- Module Python embarqué dans KiCad
- Opérations : charger/sauvegarder .kicad_pcb, placer composants au micron, créer traces/vias, définir zones cuivre, lancer DRC, exporter Gerbers
- Chaque worker Python = instance pcbnew isolée par utilisateur
- Microservice : Python + FastAPI sur kicad.layrix.ai

---

## OCTOPART — BASE DE DONNÉES COMPOSANTS

- Agrège : Digi-Key, Mouser, LCSC, Arrow, 300+ distributeurs
- Données temps réel : prix, stock, datasheet, modèles 3D STEP, footprints KiCad
- pgvector : embeddings composants pour recherche sémantique
- LCSC en priorité (moins cher, livraison rapide)

---

## NGSPICE — SIMULATION ÉLECTRONIQUE

- Simulateur SPICE open source intégré à KiCad
- Simulations disponibles : DC, transitoire, AC (Bode), bruit, Monte Carlo
- Détecte automatiquement : oscillations, surtensions, instabilités
- Plan Pro et Enterprise uniquement — 3 crédits par simulation

---

## VIEWER PCB — PIXIJS + THREE.JS

### Vue 2D — PixiJS (WebGL) :
- 60 FPS, 100 000+ éléments graphiques
- Zoom/pan fluide, layers toggles (F.Cu, B.Cu, SilkS...)
- Sélection composants au clic, mesure distances
- DRC violations cliquables avec localisation exacte
- Viewer footprint inline dans le dashboard librairie

### Vue 3D — Three.js :
- Fichier STEP 3D exporté par KiCad CLI
- Rotation libre, zoom, composants 3D (QFN, condensateurs, connecteurs)
- Éclairage réaliste (vert FR4, cuivre doré, silkscreen blanc)
- Plan Maker+ — 1 crédit

---

## EXPORT GERBER + COMMANDE JLCPCB

### Export via KiCad CLI :
Fichiers générés : F.Cu.gbr, B.Cu.gbr, F.SilkS.gbr, B.SilkS.gbr, F.Mask.gbr, B.Mask.gbr, Edge.Cuts.gbr, board.drl
Tout zippé automatiquement en gerbers.zip prêt pour upload JLCPCB.

### Commande JLCPCB via API partenaire :
L'agent appelle l'API JLCPCB directement avec les Gerbers et paramètres choisis :
1. Upload des fichiers Gerber
2. Obtention du devis (prix + délai)
3. Affichage à l'utilisateur pour confirmation OBLIGATOIRE
4. Commande passée uniquement après accord explicite
5. Retour : order_id, prix total, délai livraison, tracking URL

Sécurité : jamais de commande automatique sans confirmation. Carte de paiement via Stripe, jamais exposée à l'agent.

Roadmap fabricants : JLCPCB (Phase 1) → PCBWay (Phase 2) → Eurocircuits (Phase 3) → OSHPark (Phase 4)

Commission Layrix : 5–10% par commande → +1 000–2 000€/mois dès mois 12.

---

## CONCURRENTS AVEC IA

### Flux.ai (Defy Gravity Inc.) — Le plus financé
- 37M$ levés en Series B (8VC) en février 2026
- Langage naturel, recommandation composants, firmware generation
- Orienté entreprises, prix premium
- Pas de commande fabrication, pas de génération footprint automatique
- Pas accessible aux makers

### Quilter.ai
- Routage autonome cloud, pay-per-use
- Pas de schéma, pas de langage naturel, pas de footprint, pas de commande fabrication
- Résout uniquement le routage

### DeepPCB
- Reinforcement Learning, routage DRC-clean, jusqu'à 8 couches
- Compatible KiCad et Zuken
- Pas d'agent conversationnel, pas de footprint, pas de commande fabrication

### Siemens EDA AI
- IA générative agentique dans Xpedition (DAC 2025)
- 100% enterprise, 50 000€+/an
- Inaccessible makers

### Cadence Allegro AI
- Géant EDA, IA intégrée
- 50 000€+/an, Fortune 500 uniquement

### KiCad MCP Server (open source)
- Claude + KiCad via MCP, 64 tools
- Nécessite installation locale KiCad + Python
- Réservé développeurs, pas de SaaS

### TSCircuit (open source)
- "React for Electronics", Skill Claude Code officiel
- Framework open source — Layrix l'utilise comme moteur interne

### Tableau comparatif :

|                    | Flux  | Quilter | DeepPCB | KiCad MCP | Layrix |
|--------------------|-------|---------|---------|-----------|--------|
| Langage naturel    |  ✅   |   ❌    |   ❌    |    ✅     |   ✅   |
| 100% cloud         |  ✅   |   ✅    |   ✅    |    ❌     |   ✅   |
| Prix accessible    |  ❌   |   ⚠️    |   ⚠️    |    ✅     |   ✅   |
| Schéma → Gerber    |  ✅   |   ❌    |   ❌    |    ✅     |   ✅   |
| Footprint auto     |  ❌   |   ❌    |   ❌    |    ❌     |   ✅   |
| Viewer 2D/3D       |  ✅   |   ❌    |   ❌    |    ❌     |   ✅   |
| Commande JLCPCB    |  ❌   |   ❌    |   ❌    |    ❌     |   ✅   |
| Simulation SPICE   |  ❌   |   ❌    |   ❌    |    ❌     |   ✅   |
| Financement        | 37M$  |    ?    |    ?    |    0$     |   0$   |

Layrix est le seul outil qui couvre le cycle complet de l'idée au PCB dans ta boîte aux lettres, avec génération automatique des footprints manquants.

---

## POURQUOI LAYRIX EST UNE IDÉE PORTEUSE

### 6 signaux convergents :

1. Validation marché : Flux.ai a levé 37M$ en 2026 sur exactement ce segment. Les VCs valident que le marché est réel. Flux cible les entreprises. Layrix cible les makers — segment 10× plus large en volume.

2. Marché en forte croissance : marché PCB mondial à 85.4B$ en 2025 → 117.5B$ en 2035. Le segment cloud/SaaS EDA croît 3× plus vite que le marché global.

3. IA devient standard industrie : les outils IA PCB détectent les erreurs avec une vitesse et précision qui dépasse les capacités humaines. Adoption massive en cours.

4. Aucun dominant sur le segment accessible : Flux est trop cher, KiCad MCP trop technique, DeepPCB et Quilter font du routage seulement. Le segment "SaaS PCB IA accessible, cycle complet, langage naturel" est libre.

5. Effet de levier Claude API : niveau d'intelligence comparable à ce que Flux a construit avec 37M$, pour 0.12€ par PCB.

6. Double business model : SaaS abonnement + commission fabrication JLCPCB. La librairie communautaire de footprints devient un asset propriétaire défendable après 10 000 users.

---

## STACK TECHNIQUE

-      → next.js (landing, SEO, marketing) — pas de JS inutile, Lighthouse 100/100  + Zustand+ailwind + shadcn/ui
-   → next.js (dashboard, pas de SEO — SSR inutile ici)
-   → next.js ou node.js +express ou Node.js + Fastify (backend, jobs KiCad longs, WebSocket, BullMQ)
mais pour MVP next.js
-  → Python + FastAPI + pcbnew (microservice KiCad)
-turbo :monorepo
Pourquoi  Next.js pour le dashboard :
- Le dashboard n'a pas besoin de SEO → SSR inutile
- Supabase Auth gère l'authentification → Auth.js inutile
- Next.js vaut le coup SEULEMENT si on utilise SSR + API Routes + Auth.js

- Viewer 2D : PixiJS (WebGL)
- Viewer 3D : Three.js (STEP)
- Base de données : PostgreSQL + Supabase + pgvector (RAG)
- Cache / Queue : Redis + BullMQ (10 PCBs simultanés)
- Stockage fichiers : Supabase Storage (S3-like)
- Deploy : Vercel (frontend) +
- Paiement : Stripe Billing ou Lemon Squeezy ou Paddle , MVP : Lemon Squeezy
- Outil de code : Claude Code + Cursor

---

## INFRASTRUCTURE MULTI-USERS

- BullMQ + Redis : 10 PCBs simultanés sans blocage
- WebSocket : progression temps réel par utilisateur (jamais mélangée)
- Row Level Security Supabase : isolation totale des données
- Stockage isolé : /storage/userId/projectId/
- Auto-scaling Railway selon la charge
- Coût MVP : ~11$/mois | Lancement : ~80$/mois | Scale : ~250$/mois

### Futur — API publique KiCad multi-users :
- Phase 1 : Docker container KiCad par job (MVP)
- Phase 2 : Pool de 10 workers pcbnew actifs (Scale)
- Phase 3 : API REST publique JWT + webhooks + SDK Node.js/Python (Enterprise)

Endpoints futurs :
- POST api.layrix.ai/v1/pcb/generate
- POST api.layrix.ai/v1/drc/check
- POST api.layrix.ai/v1/simulate
- POST api.layrix.ai/v1/footprint
- GET  api.layrix.ai/v1/components/search

---

## BUSINESS MODEL — INSPIRÉ DE LOVABLE

Système de crédits : 1 crédit = 1 action IA sur le PCB

- Free : 0€ → 5 crédits/jour (30/mois)
- Maker : 25€/mois → 100 crédits
- Pro : 50€/mois → 300 crédits
- Enterprise : sur devis → crédits illimités

Top-ups ponctuels : 20 crédits = 5€ | 100 crédits = 20€ | 300 crédits = 50€

Coût par action :
- Chat simple : 0.5 crédit
- Génération schéma : 2 crédits
- Placement composants : 2 crédits
- Routage Freerouting : 3 crédits
- DRC + correction : 1 crédit
- Export Gerber : 1 crédit
- Footprint depuis datasheet : 3 crédits
- Vue 3D : 1 crédit
- Simulation ngspice : 3 crédits
- PCB complet bout-en-bout : ~10–15 crédits

Réduction annuelle : −20%
Rollover des crédits non utilisés (plans payants)
Marge brute : ~85–94%
Commission JLCPCB : 5–10% par commande

---

## REVENUS ESTIMÉS — ANALYSE LOGIQUE

Hypothèses : conversion Free → Payant = 8%, churn = 5%/mois,
croissance organique Product Hunt + LinkedIn + communautés EDA = 15–25 signups/semaine

Mois 1  → 50 Free, 0 payants        → MRR : 0€
Mois 2  → 150 Free, 8 Maker, 1 Pro  → MRR : 250€
Mois 3  → 300 Free, 18M, 3P         → MRR : 600€
Mois 4  → 500 Free, 30M, 6P         → MRR : 1 050€
Mois 6  → 1 000 Free, 60M, 15P      → MRR : 2 250€
Mois 9  → 2 000 Free, 120M, 35P     → MRR : 4 750€
Mois 12 → 4 000 Free, 220M, 70P     → MRR : 9 000€
Mois 18 → 10 000 Free, 500M, 180P, 5E  → MRR : 24 500€
Mois 24 → 25 000 Free, 1000M, 400P, 15E → MRR : 52 500€

Revenus annuels :
- ARR An 1 : ~45 000€
- ARR An 2 : ~350 000€
- ARR An 3 : ~800 000€ (avec commissions fabrication + API publique)

Revenus additionnels :
- Top-ups crédits : +15% du MRR
- Commissions JLCPCB : +1 000–2 000€/mois dès mois 12
- API publique : +20% du MRR dès mois 12

Seuil de rentabilité : mois 2 — dès 10 clients payants ✅
Coût Claude API à 10 000 PCBs/mois : ~1 200€ (très en dessous des revenus)

---

## PLANNING — MI-TEMPS 3–4H/JOUR AVEC CLAUDE CODE

- Semaine 1 : Setup infra + deploy Vercel/Railway(si besion de bacckend) /DigitalOcean(Kicad)
- Semaine 2 : Landing Astro + waitlist
- Semaines 3–4 : Dashboard + chat agent + TSCircuit + PixiJS 2D + dashboard Footprints
- Semaines 5–7 : Microservice Python KiCad + Freerouting + pcbnew + génération footprint IA
- Semaines 8–9 : Three.js 3D + ngspice + Octopart + JLCPCB API
- Semaine 10 : 🚀 Polish + Launch

MVP minimal (sans viewer 3D) : 4 semaines
Version complète : 10 semaines

---

## VISION

Layrix n'est pas un chatbot PCB — c'est un agent IA autonome qui conçoit, route, valide, génère les footprints manquants, exporte et commande la fabrication de PCBs complets sans quitter le chat.

Aucun composant ne bloque l'agent — si le footprint n'existe pas, Layrix le crée.

Flux a levé 37M$ pour les entreprises.
Layrix prend le marché des makers et startups — 2 millions de personnes qui ne peuvent pas payer Altium à 3000€/an.

35 millions d'ingénieurs dans le monde.
25€/mois. Zéro installation. Langage naturel. Commande JLCPCB intégrée.

"Describe your circuit. We build and ship your board." 🚀


La meilleure approche en 2026 (recommandation réaliste)
Hybride (ce que font beaucoup d’équipes sérieuses) :

Claude Agent SDK → utilisé à l’intérieur des nœuds LangGraph pour les parties lourdes (tool-use fiable, file ops, bash sandbox, MCP tools).
LangGraph → comme orchestrateur principal (StateGraph) : gère le flux global, la persistance, le routing, le human-in-the-loop, et le dashboard SaaS.

Avantage : Tu profites du meilleur tool-use de Claude + la flexibilité et la production-readiness de LangGraph.
Quand choisir Claude SDK seul ?

Si ton MVP est ultra-simple (un seul type d’agent tool-heavy, pas de complexité de flux).
Si tu veux sortir un prototype en 1-2 semaines.
Si tu es 100 % sûr de rester sur Claude pour toujours.

Pour un vrai SaaS Layrix avec plusieurs templates, utilisateurs payants, et agents "deep" → LangGraph (hybride avec Claude SDK) est le choix le plus durable.


pour protypage on utulise claude SDK
