---
name: cirqix-drc
description: This skill should be used when the user asks to "lancer le DRC", "vérifier les règles PCB", "corriger les violations DRC", "implémenter la boucle DRC", "afficher les erreurs DRC dans le viewer" or mentions DRC, violations, clearance, track width, règles PCB.
version: 0.1.0
---

# Cirqix — Agent DRC (Design Rule Check)

## Chaîne DRC réelle

`handleDrc` (`packages/agents/src/tools/handlers/drc.ts`) → `POST /drc/auto` (`services/kicad/routers/drc.py`) : pré-filtre kicad-tools, puis `kicad-cli pcb drc` qui fait foi, auto-correction au plus 3 fois dans le service. Verdict : `est_bloquante` (`services/kicad/tools/drc.py`). Fail-closed : service injoignable, `skipped` ou board absent → `status: 'error'`, jamais `DRC_CLEAN`. Aucun modèle dans cette étape.

## Corrections automatiques

`_apply_fixes` (`services/kicad/routers/drc.py`) : via micro dans une pastille de net de plan restée orpheline (`add_zone_via_for_unconnected_pads`, en texte pur), puis remplissage des zones par `pcbnew` dans un processus enfant (`tools/drc_pcbnew_runner.py`), jamais dans le handler, car `pcbnew` n'est pas thread-safe et la route tourne dans le pool de threads d'uvicorn. Une correction qui échoue n'est pas comptée. `apply_drc_fixes` de `tools/drc.py` est un reliquat sans appelant.

## Types DRC

`DRCViolation` (`packages/types/src/index.ts`) : `id`, `severity`, `message`, `x_mm`, `y_mm`, `layer?`. Réponse du service côté client : `RealDrcResult` (`packages/agents/src/engines/drc-service.ts`) : `drcClean`, `violations`, `fixedCount`, `kicadPcbContent?`, `skipped`, `warning?`. Côté Python, une violation porte aussi `type`, que lit `est_bloquante`.

## Violations et règles

Violations affichées par `apps/web/src/widgets/viewer/ui/DrcView.tsx`. Règles : profil fabricant kicad-tools (`services/kicad/tools/drc.py`) et `_REGLES_FINE_PITCH` (`services/kicad/routers/routing.py`) ; ne pas les recopier.
