# Handoff — `2026-07-28-fiabilisation-pipeline-agents`

- **Status:** `DONE` (mergé sur `main`)
- **Owner:** `Claude Code`
- **Reviewer:** `aucun` — `ultrareview` n'a jamais rendu de rapport (voir « Revue » plus bas)
- **Receiver:** `none`
- **Branch:** `feat/routage-100-industriel` → mergée (merge commit `2aef1de`)
- **Worktree:** `C:\Users\Mechegui\Desktop\dev\cirqix`
- **Base commit:** `de560f5` (dernier commit du chantier routage, avant ce travail)
- **Content commit:** `107d82c` (dont `aaf34f4`..`15eaf9f` = mes 12 commits)
- **Updated UTC:** `2026-07-28T20:00:00Z`

### Revue — ce qui s'est passé

`/code-review ultra 63` a d'abord été silencieusement absorbé par une commande
perso `~/.claude/commands/code-review.md` qui masque la commande intégrée : les
arguments `ultra 63` lui sont arrivés comme simple texte, aucune revue distante
n'a démarré. `/ultrareview 63` a ensuite **refusé le périmètre** (63 fichiers /
11 359 lignes contre un plafond de 8 000). Une branche `review-base/pre-fiabilisation`
(= `de560f5`) a été poussée pour borner la revue aux 12 commits (43 fichiers,
7 283 lignes) ; le dispatch n'a produit aucun rapport, ni commentaire, ni check.

**Cause première : la PR était trop grosse pour l'outillage.** J'ai empilé un
second chantier sur la branche du routage au lieu d'ouvrir une branche par
thème. La carte de relecture rédigée dans la description compense la lisibilité,
pas le volume. Décision prise avec l'owner : merger sur CI verte + tests, sans
revue multi-agents.

> ⚠️ Ce handoff couvre le **chantier B** de la PR #63 uniquement (12 commits,
> `de560f5..15eaf9f`). Le chantier A (routage 100 % industriel, ~31 commits) est
> décrit par `2026-07-19-routage-100-industriel.md` et n'a pas été re-vérifié ici.

---

## Le motif trouvé : le succès fantôme

Point de départ : une demande de couverture de tests sur l'orchestrateur. En
l'écrivant, un motif systémique est apparu — **dix chemins, six fichiers**
annonçaient un succès sans avoir travaillé, tous convergeant vers le même gate de
commande JLCPCB.

| Handler | Annoncé sans travail réel | Commit |
|---|---|---|
| `routing` | `routed_percent: 100` sur 2 replis, sans une piste | `5db621d` |
| `drc` | `DRC_CLEAN` sur 3 chemins, dont « `KICAD_SERVICE_URL` absente » | `7431aa3` |
| `export` | `PCB_LIVRÉ` + **devis 12,50 $ fabriqué** + invitation à « OUI JE CONFIRME » | `b6b07ed` |
| `erc` | `ERC_CLEAN` sur 2 chemins | `b6b07ed` |
| `gen_pcb` | `success` avec un board **vide** | `27c32ad` |
| `local-pipeline` | statut **codé en dur**, ignorant le retour des handlers | `7431aa3` |

Chaîne complète : `pcb_status` → `orchestrator-bridge` → `projects.status` →
`POST /api/jlcpcb/order`, qui autorisait la commande. Un conteneur KiCad éteint
suffisait donc à déclarer fabricable une carte jamais vérifiée.

**Traitement différencié, délibéré :** `erc` bascule sur `runErcFallback` (un
vérificateur RÉEL) au lieu d'échouer ; `reason` a été audité et **non modifié**
(sûr par construction — `runReasoner` ne lève jamais, et `mergeRescueIntoRouting`
empêche la régression). 9 tests verrouillent ces deux propriétés implicites.

## Objectif DRC-clean atteint

`examples/led-blinker-full-pipeline/expected/led_blinker_final.kicad_pcb` :
**100 % routé · 0 violation · 0 net non connecté · 20 fichiers de fabrication.**
Vérifié hors service par `kicad-cli --severity-all --refill-zones`, hash confirmé
identique à l'artefact du run.

Trois causes racines levées :

1. **Valeurs numériques non quotées** (`7e039b6`) — `(property "Value" 330`
   rendait le board illisible par KiCad 10 (`Failed to load board`,
   `pcbnew.LoadBoard` → `None`) alors que kicad-tools l'acceptait : le board se
   plaçait et se routait à 100 %, puis DRC et export échouaient. Touchait toute
   résistance notée sans unité.
2. **VCC jamais routé** (`a69eb83`) — classé « power » par `net_class`, donc exclu
   du pathfinding, mais seul GND est coulé en plan. La table de renommage était
   codée en dur sur `+5V`/`+3.3V` ; elle est désormais dérivée du board.
   *Piège :* `explain.mistakes.is_power_net` n'est **pas** le bon oracle (rate
   `VBUS`, flague `P5V0`) — un premier test écrit contre lui passait sans rien
   prouver. Le bon oracle est `router.net_class.classify_from_name`.
3. **Marge de courtyard** (`a69eb83`) — l'Inspecteur approxime « pads + 0.25 mm »,
   kicad-cli utilise la géométrie réelle `F.CrtYd`. Portée à 0.5 mm.

Campagne (3 runs par configuration, GA stochastique) :
`8/67/58` → `10/17/6` → **`0/12/4`**, soit 2 runs clean sur 3. Le re-tirage
déterministe est étendu au DRC (`aad7c0f`), ce qui ramène l'échec attendu sous
~4 % sur trois tentatives.

## Le Géomètre CMA-ES ne s'exécutait jamais (`bab28ad`)

`signal.signal` hors thread principal sous uvicorn : l'exception tombait avant
toute itération, le filet de sécurité conservait le board pré-CMA-ES. Une étape
entièrement documentée, calibrée et testée, **morte en production** depuis le
passage en conteneur — invisible parce que pytest tourne dans le thread principal.
Corrigé par processus enfant (`tools/cmaes_runner.py`).

**Ablation honnête, 3 runs par bras :** `0/12/4` avec, `4/2/10` sans — 2 clean sur
3 dans les deux cas. **Aucune différence mesurable sur ce board.** À nuancer :
n=3 face à une variance de 0 à 12 est un ordre de grandeur, et le bénéfice
documenté du Géomètre a été mesuré sur le board STM32 dense.

## Bugs de câblage (`27c32ad`)

Premier test faisant tourner la chaîne TS contre le service réel
(`pipeline-live.test.ts`, opt-in `CIRQIX_LIVE_KICAD=1`). Quatre bugs qu'aucun test
mocké ne pouvait voir — les mocks reproduisaient l'hypothèse du client :

1. `handlePlacement` **jetait** le board de `gen_pcb` et le régénérait en TS — que
   le service ne parvenait pas à parser (`500 ParseError`).
2. `PLACEMENT_TIMEOUT_MS` = **10 s** pour une étape mesurée à 34-45 s : le
   placement expirait *systématiquement* face à un vrai service.
3. `ROUTING_TIMEOUT_MS` = 90 s alors que le service s'accorde 300 s.
4. `/place/auto` renvoyait `{ref, x, y}` au lieu du `{ref, x_mm, y_mm}` documenté
   par son propre modèle : le client filtrait **toutes** les positions.

---

## Risques et blocages

- **PR #63 trop grosse pour l'outillage de revue** (63 fichiers, 11 359 lignes ;
  plafond 8 000). `ultrareview` a refusé. Contournement : branche
  `review-base/pre-fiabilisation` (= `de560f5`) poussée, la revue porte sur les 12
  commits (43 fichiers, 7 283 lignes). **Cause : avoir empilé un second chantier
  sur la branche du routage au lieu d'ouvrir une branche par thème.**
- **Migration 007 déjà appliquée** sur le Supabase Cirqix (colonne `agent_mode`,
  contrainte vérifiée). Le gate JLCPCB est **fail-closed** : tout projet de
  provenance inconnue (`NULL`) est refusé à la commande — donc tous les projets
  antérieurs tant qu'ils ne sont pas rejoués. Décision assumée, à valider.
- **`pipeline-live.test.ts` ne tourne pas en CI** (opt-in, exige le conteneur). Il
  ne protège que si quelqu'un le lance — or c'est lui qui a trouvé 4 bugs.
- **Taux de 2/3 fondé sur 3 runs** : ordre de grandeur, pas statistique.
- **Session parallèle active** sur la facturation dans le même worktree
  (`lemon-squeezy`, migration 008). Vérifier la branche avant tout `git`.

## Travail restant

- Traiter le rapport `ultrareview` puis merger la PR #63.
- **Patches `kicad_tools` #9 et #10** : documentés dans `DEPENDENCIES.md`, **non
  poussés** — la procédure exige double revue humaine + force-push sur le fork.
  Le garde `_quote_bare_property_values` les contourne en attendant.
- Solidifier le 2/3 par une campagne plus large.
- Le gate JLCPCB n'est pas conscient de la simulation au-delà d'`agent_mode` : à
  revoir si `POST /api/jlcpcb/order` est un jour branché sur la vraie API.

## Constats transmis à la session facturation (non traités ici)

Revue sécurité manuelle du webhook Lemon Squeezy — **fichiers non commités,
propriété de l'autre session, non modifiés** :

- 🔴 `route.ts:34` — `secret ?? ''` : HMAC à clé vide reste valide, signature
  **forgeable** si la variable manque. Fail-open sur le chemin de paiement, alors
  que `services/kicad/security.py:26` applique la règle inverse.
- 🔴 `route.ts:70-77` — `isDuplicate` renvoie `false` sur toute erreur ≠ `23505` :
  le verrou tombe ouvert quand la base flanche. **Vérifié : la table
  `processed_webhook_events` n'existe pas encore en base** → aujourd'hui chaque
  retry créditerait à nouveau. Appliquer la migration 008 AVANT de déployer.
- 🟠 Aucun contrôle de `attrs.status` sur `order_created` · l'abonnement écrase le
  solde (perte de top-up) · `console.error` au lieu de Pino.

## Chantier CI trouvé et réparé en cours de route (PR #67, mergée)

Les deux workflows de bump de submodule échouaient **à chaque exécution**, pas
ponctuellement : le nom de branche dérive du SHA du submodule, donc identique
d'une semaine à l'autre tant que le fork n'avance pas ; la branche existant déjà
côté distant, `--force-with-lease` refusait de parier sans référence de suivi
locale (`stale info`). **La Porte 3 était hors service** — aucun bump ne pouvait
plus atterrir.

Second défaut trouvé en validant le premier : `|| echo "PR existe peut-être déjà"`
avalait TOUTE erreur, dont `GitHub Actions is not permitted to create or approve
pull requests`. Le job passait **au vert sans produire de PR** — même motif de
succès fantôme que côté pipeline agents. Durci : seul « already exists » est
toléré.

Réglage dépôt activé (owner) : *Allow GitHub Actions to create and approve pull
requests*. Chaîne validée de bout en bout — PR #68 et #69 créées automatiquement.

## Mesure de la PR #69 (bump kicad-tools) — NON CONCLUANTE

Trois tentatives, aucun résultat exploitable :

1. build tué par un `timeout` interne mal placé ;
2. image construite depuis `main` → **KiCad 8 + kicad-tools 0.18.0**, alors que
   la référence tournait sur **KiCad 10 + 0.13.0**. Deux variables changées :
   mesure invalide. J'ai failli en conclure « la PR #69 casse le routage » ;
3. rebuild sur base KiCad 10 → échec `apt` transitoire.

**Piège de méthode à retenir :** l'image `latest` venait de la branche #62
(KiCad 10), pas de `main` (KiCad 8), et mes correctifs arrivaient par **volumes
montés** (`./tools`, `./routers`) et non par l'image. Vérifier `kicad-cli
--version` dans l'image de référence ET de test AVANT de lancer, pas après
l'échec.

Fait solide malgré tout : **kicad-tools 0.18.0 refuse de router un placement
dont des composants sortent du contour** (`7 footprint(s) outside Edge.Cuts —
placement invalid`) là où 0.13.0 le faisait en silence. Validation nouvelle que
le pipeline devra satisfaire.

Depuis le merge de #62 et #63, `main` porte KiCad 10 **et** les correctifs : la
mesure ne fait plus varier qu'une seule chose et redevient faisable simplement.

## Prochaine action atomique

Mesurer la PR #69 depuis `main` (qui porte désormais KiCad 10 + les correctifs) :
image avec le submodule à `f2afb96`, 3 runs de `led-blinker-full-pipeline`,
comparaison au `0/12/4` de référence. Une seule variable change enfin.

Surveiller aussi le premier effet de bord des fail-fast en production : une
panne jusqu'ici silencieuse (conteneur éteint, `KICAD_SERVICE_URL` absente,
kicad-cli indisponible) arrête désormais le pipeline au lieu d'annoncer un board
« routé à 100 % » ou « DRC clean ». C'est l'effet recherché, pas une régression.

## Git

- **État initial du worktree :** `de560f5`, propre hors untracked `.cursor/`,
  `.gemini/`, `GEMINI.md` et 2 suppressions préexistantes non possédées.
- **État final :** `main` = `2aef1de` (KiCad 10 + fiabilisation). Worktree portant
  les fichiers non commités de la session facturation, non touchés.
- **Commits :** `aaf34f4` → `15eaf9f` (12), plus `107d82c` d'une session parallèle.
- **PR mergées :** `#62` (KiCad 10) · `#63` (fiabilisation) · `#67` (Porte 3).
- **PR laissées ouvertes :** `#68` / `#69` (bumps de submodule, Porte 4 = revue humaine).
- **Ref de revue :** `review-base/pre-fiabilisation` → `de560f5` (conservée).
- **Vérification :** 143 tests TS · 172 tests Python · `pnpm type-check` 7/7 ·
  eslint clean · CI 5/5 verte au merge.
- **Migration 007 appliquée** sur le projet Supabase Cirqix (colonne `agent_mode`
  + contrainte, vérifiées par `pg_get_constraintdef`).

## Journal de transfert

| Date UTC | From | To | État | Note |
|---|---|---|---|---|
| `2026-07-28T00:00:00Z` | `Claude Code` | `ultrareview` | `proposé` | `Revue lancée sur review-base/pre-fiabilisation (12 commits)` |
| `2026-07-28T00:00:00Z` | `Claude Code` | `session facturation` | `proposé` | `2 constats critiques webhook LS, fichiers non modifiés` |
