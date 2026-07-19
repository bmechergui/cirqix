# Handoff — `2026-07-19-routage-100-industriel`

- **Status:** `REVIEW`
- **Owner:** `Claude Code`
- **Reviewer:** `Codex`
- **Receiver:** `none` (Kimi indisponible — validation croisée reprise par l'owner, décision utilisateur 2026-07-19)
- **Branch:** `feat/routage-100-industriel` (à créer depuis `origin/main` = `aa50a81`)
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Base commit:** `aa50a81` (origin/main)
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-07-19T12:10:00Z`

Le receiver relève le head Git courant local et distant au moment de la
réception ; ne pas le recopier ici, car le commit de ce fichier le périmerait.

## Objectif

Routage **100 % des nets** sur `services/kicad/examples/stm32-validation`
(juge : `kicad-cli pcb drc`), via une solution **générique** (aucune constante
board-specific) applicable à tout type de carte. Référence : mémoire projet
« routage-100-pourcent » — recette `--auto-mfr-tier` déjà en prod (PR #48),
plancher mesuré 91 % sur placement GA frais.

## Critère de terminaison

3 runs consécutifs de `run_agent_chain.py` (placement GA frais à chaque run)
atteignent 100 % de nets routés, OU l'écart résiduel est documenté avec cause
racine + mesures ; tests `services/kicad/tests/` verts ; PR ouverte.

## Périmètre autorisé

### Chemins possédés (Claude Code)

- `services/kicad/tools/reasoning.py` (piste 2 — dédup suggestions rescue)
- `services/kicad/tools/kct_route.py` (piste 4 — alignement DRC sur tier escaladé)
- `services/kicad/tests/test_reasoning_feedback.py` + nouveaux tests `services/kicad/tests/`
- `docs/agents/handoffs/2026-07-19-routage-100-industriel.md` (ce fichier)

### Lecture seule

- `services/kicad/kicad-tools/**` (sous-module fork — JAMAIS modifié depuis ce repo)
- `services/kicad/examples/stm32-validation/**` (harnais de validation ; outputs régénérables non committés)

### Hors périmètre

- Tout `apps/web`, `packages/**`, migrations DB
- Toute mise à jour de gitlink des sous-modules
- Régénération de la clé `ANTHROPIC_API_KEY` (action humaine — voir Risques)

## Modifications préexistantes non possédées

- `.cursor/`, `.gemini/`, `GEMINI.md` (untracked — adaptateurs autres assistants, ne pas toucher)

## Décisions prises

- Orchestration 3 agents : Claude Code = owner exécution ; Codex = reviewer ;
  Kimi = validation croisée généricité. Un seul owner actif (protocole COLLABORATION.md).
- Pistes retenues (mémoire routage-100-pourcent, leviers rejetés non re-testés) :
  - **Piste 2** : dédup des suggestions déjà appliquées entre itérations du
    rescue (anti-oscillation U2/J1 91→82→91).
  - **Piste 4** : aligner les règles DRC du board sur le tier fabricant
    réellement retenu après escalade (résiduels copper_edge/annular_width).
  - **Piste 3 (vérif)** : retry placement borné (commit 0230ebc) — vérifier
    qu'il se déclenche quand le rescue plafonne, l'étendre sinon.
- La voie LLM (Haiku) reste bloquée par la clé API invalide — la solution doit
  être **déterministe d'abord** ; le LLM redevient un bonus quand la clé sera régénérée.

## Tâches assignées

### Codex — Reviewer (lecture seule jusqu'à review)

1. À la demande de review (Status → REVIEW) : relire le diff de
   `services/kicad/tools/reasoning.py` + `kct_route.py` + tests.
2. Points d'attention : généricité (zéro référence STM32/refs en dur),
   préservation de la garde anti-régression (meilleur board conservé),
   non-régression du contrat des endpoints `/route/auto` et `/reason/auto`.
3. Rapporter les constats classés par sévérité à l'owner — pas de correction directe.

### Validation croisée généricité (reprise par l'owner — Kimi indisponible)

1. La dédup opère uniquement sur les tuples `(ref, direction)` du parseur
   générique (`[A-Z]{1,4}\d+`) — les tests utilisent des refs variées
   (R5/C2/C3/Z99) pour verrouiller l'absence de constante board-specific.
2. Validation d'exécution réelle : boucle rescue de prod sur le board baseline
   (voir Validations exactes).

## Travail réalisé

- Baseline `run_agent_chain.py` exécutée (output local `examples/stm32-validation/output/orch-run1`,
  non committé) : génération OK, ERC PASS, placement 17 composants, **routage initial 27 %**
  (tirage GA défavorable — non-déterminisme documenté 56–89 %).
- **Piste 2 implémentée (TDD)** : `_select_applicable_moves` (filtre pur avant la
  coupe `max_moves_per_iter`), historique `(ref, direction)` local à l'appel,
  cap `_MAX_SAME_MOVE=2`, rejet des positions déjà occupées en voie 2
  (`_position_already_tried`, ε=0.05mm). 8 nouveaux tests — 28/28 verts.
- **Piste 3 vérifiée** : retry placement présent et actif
  (`packages/agents/src/orchestrator.ts:52-77`, `MAX_PLACEMENT_ATTEMPTS=3`,
  `keepBestRouting`) — aucune extension nécessaire ; la dédup lui rend du budget
  en arrêtant le rescue dès qu'aucune suggestion inédite ne reste.
- **Piste 4 implémentée (TDD, commit d13bc19)** : `parse_retained_tier` (stdout
  escalade) + marqueur in-band `cirqix_mfr_tier` (property racine KiCad,
  idempotent, validé compatible parseur kicad-tools) + sidecar `.kicad_pro`
  natif (`get_profile().get_design_rules()` + `apply_manufacturer_rules`) écrit
  par le router DRC avant kicad-cli. No-op sans escalade. 13 tests, 107/107 verts.

## Fichiers modifiés

- `services/kicad/tools/reasoning.py` — dédup anti-oscillation (voies 1 et 2)
- `services/kicad/tests/test_reasoning_feedback.py` — 8 tests dédup + stub scripté
- `docs/agents/handoffs/2026-07-19-routage-100-industriel.md` — création + suivi

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `run_agent_chain.py output/orch-run1` (baseline) | `exit 0 — ERC PASS, placement 17 comp., routage 27 %` | `2026-07-19T12:40:00Z` |
| `run_feedback_loop.py … no_decisions.json` (rescue prod + dédup, sans LLM) | `exit 0 — 27 % → 45 % (meilleur conservé) ; 4 suggestions appliquées (D1/R2 nord puis ouest — orthogonales, correctement autorisées) ; itér. 3 rechute 27 % absorbée par la garde` | `2026-07-19T13:05:00Z` |
| `pytest services/kicad/tests` | `107 passed (8 tests dédup + 13 tests alignement tier)` | `2026-07-19T17:00:00Z` |
| `kct build-native --check` (local Windows) | `C++ backend: not installed — compilation impossible (pas de C++20)` | `2026-07-19T16:55:00Z` |
| `kct build-native --check` (Docker cirqix-kicad) | `C++ backend: available (version 1.0.0)` | `2026-07-19T17:00:00Z` |
| Docker run 3 : `run_agent_chain.py` (backend C++) | `exit 0 — placement 17 comp. (0 conflit), routage brut 36 % (tirage GA défavorable, NRST BLOCKED_PATH)` | `2026-07-19T17:15:00Z` |
| Docker run 3 : `run_feedback_loop.py` (rescue prod + dédup, sans LLM) | `exit 0 — 36 % → 82 % → 91 % → 82 %, meilleur conservé 91 % ; suggestions J1 est puis J1 nord (orthogonales, autorisées par la dédup) — reproduit exactement le plancher 91 % documenté` | `2026-07-19T17:35:00Z` |
| `kicad-cli pcb drc` (juge final) | `non exécuté — pertinent quand un run atteint 100 % routé` | — |

Bilan mesuré (iso-prod Docker, backend C++) : la chaîne déterministe complète
(placement GA → route 36 % → rescue+dédup → **91 % conservé**) reproduit le
plancher 91 % documenté sur un tirage défavorable. Le critère « 3 runs
consécutifs à 100 % » n'est PAS atteint dans cette session. Le dernier net est
*partiellement connecté* → le routeur n'émet pas de suggestion → au-delà de
91 %, les deux leviers de prod sont : retry placement orchestrateur (tirage GA
neuf — certains tirages routent 100 %, benchmark PR #48) et voie LLM du
reasoner (bloquée : clé API invalide — action humaine).

## Risques et blocages

- Non-déterminisme GA/routeur (56–89 % observés run à run, upstream #2673/#2802)
  → toute mesure se fait sur ≥3 runs ; garde anti-régression obligatoire.
- Clé `ANTHROPIC_API_KEY` invalide (401) → voie LLM du reasoner indisponible ;
  si les pistes déterministes plafonnent < 100 %, la régénération de la clé
  devient l'action humaine bloquante.
- Windows : `PYTHONUTF8=1` obligatoire (bug charmap historique).

## Travail restant

- Runs de validation supplémentaires en environnement Docker (backend C++) —
  critère : 3 runs consécutifs à 100 %.
- Review Codex de la PR #63 (pistes 2 + 4).

## Cause racine des runs locaux faibles (27 % / 9 % / 45 %) — mesurée 2026-07-19

`kct build-native --check` en local Windows : **backend C++ absent** (pas de
compilateur C++20 ; la compilation échoue). Le routeur retombe en silence sur
l'A* Python pur 10-100× plus lent → mur de deadline wall-clock. Le même
pipeline avec backend compilé (conteneur `cirqix-kicad`, vérifié
`C++ backend: available 1.0.0`) route le board STM32 de référence à 100 % en
121 s (mesure documentée kct_route.py). **Toute mesure de % routé faite en
local Windows sans le backend C++ n'est PAS représentative de la prod.**

## Prochaine action atomique

Codex : relire le diff de `services/kicad/tools/reasoning.py` +
`services/kicad/tests/test_reasoning_feedback.py` (points d'attention listés
dans « Tâches assignées ») et rapporter les constats à l'owner.

## Git

- **État initial du worktree:** `docs/fork-strategy-pipelines-local-cloud propre (hors untracked .cursor/.gemini/GEMINI.md)`
- **État final du worktree:** `à mettre à jour`
- **Commit:** `none`
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-19T12:10:00Z` | `Claude Code` | `Codex` | `proposé` | `Review du diff à venir (Status REVIEW)` |
| `2026-07-19T12:10:00Z` | `Claude Code` | `Kimi` | `proposé` | `Validation croisée multi-boards après review` |
