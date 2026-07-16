# Collaboration Claude Code ↔ Codex

Ce document définit le protocole commun des assistants de développement de
Cirqix. Il organise le travail ; il ne décrit pas les agents Anthropic exécutés
par le produit dans `packages/agents`.

## Sources de vérité

| Sujet | Source |
|---|---|
| Règles projet, architecture et contraintes métier | [`CLAUDE.md`](../../CLAUDE.md) |
| Adaptation des outils Codex | [`AGENTS.md`](../../AGENTS.md) |
| Phase et priorités produit | [`PLAN.md`](../../PLAN.md) |
| Protocole de collaboration | Ce document |
| État d’une tâche transférée | `docs/agents/handoffs/<task-id>.md` |
| Prompts des agents PCB du produit | [`docs/agentdescription.md`](../agentdescription.md) |
| État réel de l’implémentation | Code, migrations et tests du commit référencé |

Un handoff périmé ou une note historique ne surclasse jamais le code du SHA
référencé. Les règles de plateforme, de sécurité et la demande actuelle de
l’utilisateur restent prioritaires.

## Rôles

- **Owner** : seul agent autorisé à modifier les chemins revendiqués.
- **Reviewer** : analyse en lecture seule et rapporte ses constats à l’owner.
- **Receiver** : agent désigné pour la prochaine action après transfert.
- **Human approver** : utilisateur requis pour une décision irréversible,
  une extension de périmètre ou la confirmation JLCPCB.

Une tâche ne possède qu’un seul owner actif. Un reviewer ne devient owner
qu’après une entrée explicite dans le journal de transfert.

## États autorisés

Flux normal : `PLANNED` → `IN_PROGRESS` → `REVIEW` → `DONE`.

Transfert en cours de tâche : `IN_PROGRESS | REVIEW | BLOCKED` → `HANDOFF` →
`IN_PROGRESS`. `HANDOFF` → `DONE` est permis seulement si le receiver n’a plus
qu’à accepter un résultat final déjà validé.

`BLOCKED` peut être utilisé avec une cause et une condition précise de reprise.
`DONE` signifie que le critère de terminaison et les validations annoncées sont
réellement satisfaits.

## Sélection du handoff actif

1. Relever la branche avec `git branch --show-current`. Si la sortie est vide
   ou indéterminée (`HEAD` détaché), arrêter toute écriture et demander une
   branche ou un handoff explicite.
2. Vérifier que chaque handoff examiné possède des champs `Status` et `Branch`
   valides. Une métadonnée absente ou invalide bloque toute écriture.
3. Chercher dans `docs/agents/handoffs/` les fichiers dont le champ `Status`
   n’est pas `DONE` et dont le champ `Branch` correspond exactement.
4. Zéro candidat signifie qu’aucun handoff n’est actif.
5. Un candidat devient le handoff actif.
6. Plusieurs candidats constituent une ambiguïté : arrêter toute écriture et
   demander lequel fait autorité.

`HANDOFF_TEMPLATE.md` est un modèle et n’est jamais un candidat.

## Démarrage d’une tâche

1. Lire les fichiers d’instructions et le handoff éventuel.
2. Exécuter `git status --short --branch` et relever le SHA courant.
3. Identifier les modifications préexistantes et leurs propriétaires.
4. Pour une tâche partagée, parallèle, transférée ou longue, créer un handoff
   depuis `HANDOFF_TEMPLATE.md` avant la première écriture.
5. Déclarer l’owner, la branche/worktree et les chemins possédés.
6. Définir le critère de terminaison et les validations prévues.

Nommer le fichier `YYYY-MM-DD-<slug-court>.md`. Ne jamais utiliser un unique
`CURRENT.md` : il deviendrait un point de conflit entre tâches concurrentes.

## Propriété des fichiers et anti-conflit

- Une tâche = une branche ou un worktree = un owner actif.
- Deux owners peuvent travailler en parallèle uniquement sur des chemins disjoints.
- Un fichier revendiqué est en lecture seule pour les autres agents.
- Les fichiers d’instructions (`CLAUDE.md`, `AGENTS.md` et ce protocole) sont
  sérialisés : un seul owner peut les modifier à la fois.
- Un transfert liste explicitement les chemins rendus au receiver.
- Aucun agent ne restaure, déplace, stage ou commit les changements d’un autre.
- Avant un commit, utiliser des chemins explicites ; `git add .` et
  `git add -A` sont interdits.
- En cas de conflit entre le handoff et le worktree, arrêter l’écriture, conserver
  les deux états et demander une décision au propriétaire ou à l’utilisateur.

Quand plusieurs agents doivent écrire dans la même zone, utiliser des worktrees
séparés. Le handoff référence alors le chemin du worktree, le commit de base et
le commit de tête ; il ne transporte pas de patch copié-collé.

## Checkpoint et handoff

Lorsqu’un handoff existe, seul l’owner le met à jour à chaque changement d’owner,
blocage, demande de review ou fin de tâche. Le reviewer renvoie ses constats à
l’owner et ne modifie rien sans transfert explicite. Le document doit indiquer :

- objectif et périmètre autorisé ;
- owner, reviewer/receiver, branche et worktree ;
- SHA de base et content commit à relire ;
- fichiers modifiés et modifications préexistantes non possédées ;
- décisions prises et raisons ;
- commandes de validation avec résultats exacts ;
- travail restant, risques et blocages ;
- prochaine action atomique et critère de terminaison ;
- journal horodaté des transferts.

Le head Git courant n’est pas recopié dans le handoff, car le commit du handoff
le rendrait immédiatement obsolète. Le receiver le vérifie dynamiquement sur la
branche locale et la branche distante avant de reprendre.

Écrire `non exécuté` ou `indisponible` lorsqu’une validation ne l’a pas été.
La formule vague « tests OK » est interdite.

## Réception d’un handoff

Le receiver doit :

1. vérifier que le content commit et la branche existent, puis relever le head
   Git courant local et distant, si une branche distante existe ;
2. relire le diff des chemins transférés ;
3. vérifier que le worktree ne contient pas de modifications non attribuées ;
4. reproduire les validations critiques proportionnées au risque ;
5. consigner l’acceptation ou le refus dans le journal de transfert ;
6. devenir owner seulement après cette consignation.

Un refus décrit les écarts observables et rend la propriété à l’owner précédent.

## Review

Le reviewer ne corrige pas silencieusement le code. Il fournit des constats
classés par sévérité, avec fichiers/lignes, impact et recommandation. L’owner
applique les corrections ou transfère explicitement la propriété.

Une revue sécurité est obligatoire pour auth, paiements, secrets, endpoints,
RLS/RPC, uploads et exécution de code. Une quality gate est obligatoire entre
Schema, ERC, Placement, Routing, DRC et Export.

## Sécurité des informations

Ne jamais écrire dans un handoff ou une PR :

- clés API, tokens Supabase, cookies, JWT ou signatures ;
- contenu de `.env`, `.mcp.json` ou `.codex/config.toml` ;
- blobs KiCad/base64, Gerbers ou sorties de test volumineuses ;
- données personnelles ou URLs signées encore valides.

Un secret découvert est seulement décrit par son emplacement. Il doit être
révoqué, remplacé par une variable d’environnement et exclu du suivi Git.

## Clôture

Avant `DONE`, l’owner vérifie le diff, exécute les validations convenues et stage
uniquement ses fichiers. Lorsqu’un handoff existe, il le met à jour puis y
référence le commit et la PR. Le handoff final nomme une seule prochaine action
atomique.
