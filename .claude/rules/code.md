# Règles — Code

## TypeScript / JavaScript
- TypeScript strict sur tous les packages — jamais de `any`
- Zod pour validation des inputs API
- Immutabilité : créer de nouveaux objets, ne jamais muter
- Fichiers < 400 lignes — extraire si plus grand
- Pas de `console.log` en production — utiliser le logger Pino

## Sécurité
**NEVER** hardcoder des secrets (API keys, tokens, passwords).
**ALWAYS** utiliser des variables d'environnement.
**ALWAYS** invoquer `security-reviewer` agent avant un commit touchant auth ou paiement.

## Agents Claude
- Orchestrateur = Sonnet 4.6 — max 15 itérations par PCB
- Agents spécialisés = Haiku 4.5
- Coût cible : ~0.12€ par PCB complet
- **JAMAIS** de commande JLCPCB automatique — confirmation "OUI JE CONFIRME" obligatoire

## shadcn/ui
- `@radix-ui/react-badge` n'existe PAS — Badge est CSS pur
- Badge variants : `default | secondary | success | warning | destructive | copper | outline`

## Types source de vérité
Fichier : `apps/web/src/shared/lib/mock-data.ts` (migré FSD — ancien chemin : `apps/web/src/lib/mock-data.ts`)
- `PCBStatus` = `'INITIAL' | 'SCHEMA_DONE' | 'PLACEMENT_DONE' | 'ROUTING_DONE' | 'DRC_CLEAN' | 'PCB_LIVRÉ'`
- `Message.role` = `'user' | 'assistant'` (jamais `'agent'`)
- `Credits` = `{ balance, plan, daily_limit }` (pas `remaining`/`total`)
- `Project` = snake_case : `updated_at`, `iteration_count`
