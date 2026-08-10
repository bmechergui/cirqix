# Handoff — `fix-routing-mesure-reelle`

- **Status:** `IN_PROGRESS`
- **Owner:** `Codex`
- **Reviewer:** `owner human`
- **Receiver:** `owner human`
- **Branch:** `fix/routing-mesure-reelle`
- **Worktree:** `C:\tmp\cirqix-fix-routing`
- **Base commit:** `bf56cfb6c9f3682fa14e2198b99bb1dcaf4b0bd1`
- **Content commit:** `uncommitted`
- **Updated UTC:** `2026-08-09T00:00:00Z`

## Objectif

Mesurer réellement la connectivité après Freerouting et isoler toutes les opérations `pcbnew` de `routers/routing.py` dans un processus enfant borné.

## Critère de terminaison

Les quatre régressions demandées sont couvertes, les tests ciblés passent ou leurs blocages locaux sont consignés exactement, et aucun fichier hors périmètre n'est modifié.

## Périmètre autorisé

### Chemins possédés

- `services/kicad/routers/routing.py`
- `services/kicad/tools/routing_pcbnew_runner.py`
- `services/kicad/tests/test_routing_measurement.py`
- `docs/agents/handoffs/2026-08-09-fix-routing-mesure-reelle.md`

### Lecture seule

- `services/kicad/tools/cmaes_runner.py`
- `services/kicad/tools/placement.py`
- `services/kicad/tests/test_routing_netlist_guard.py`

### Hors périmètre

- `services/kicad/routers/drc.py`, `services/kicad/routers/erc.py`, `services/kicad/routers/export.py`, `services/kicad/routers/placement.py`
- `services/kicad/kicad-tools/**`, `services/kicad/circuit_synth/**`, `apps/**`, `packages/**`
- commit, push, PR, staging et installation de dépendances

## Modifications préexistantes non possédées

- Aucune ; `git status --short` était vide au démarrage.

## Décisions prises

- Échec fermé si la mesure enfant est absente, invalide ou expire : un job Freerouting terminé ne prouve pas la connexion.
- `_count_routable_nets` reste l'unique règle de totalisation des nets routables.

## Travail réalisé

- Tests de régression en cours d'écriture avant l'implémentation.

## Fichiers modifiés

- `docs/agents/handoffs/2026-08-09-fix-routing-mesure-reelle.md` — revendication et transfert de la tâche.

## Validations exactes

| Commande | Résultat | Date UTC |
|---|---|---|
| `non exécuté` | `non exécuté` | `2026-08-09T00:00:00Z` |

## Risques et blocages

- La présence réelle de `pcbnew` et Freerouting ne peut être prouvée hors Docker ; les tests locaux doivent les simuler par `monkeypatch`.

## Travail restant

- Écrire les tests rouges, implémenter le runner et l'intégration, valider, puis transférer à l'owner.

## Prochaine action atomique

Exécuter les tests de régression rouges avant d'écrire le code de production.

## Git

- **État initial du worktree:** `clean`
- **État final du worktree:** `en cours`
- **Commit:** `none`
- **PR:** `none`

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-08-09T00:00:00Z` | `owner human` | `Codex` | `accepté` | Implémentation sans commit ni push. |
