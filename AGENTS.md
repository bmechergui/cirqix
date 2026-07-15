# Cirqix.ai — adaptateur Codex

> Ce fichier est l’entrée **Codex** du dépôt. Le nom reconnu est `AGENTS.md`
> (au pluriel) : ne pas créer de fichier concurrent `AGENT.md`.

## Lecture obligatoire

Après chargement de ce fichier, lire dans cet ordre :

1. `CLAUDE.md` — source canonique transitoire des règles projet Cirqix.
2. `docs/agents/COLLABORATION.md` — propriété, branches et handoffs.
3. Le handoff actif dans `docs/agents/handoffs/`, s’il existe.
4. `PLAN.md` et le skill Cirqix pertinent pour la tâche.

Déterminer d’abord la branche Git courante. Si elle est vide ou inconnue
(`HEAD` détaché), arrêter avant toute écriture. Le handoff actif est ensuite
l’unique fichier non `DONE` dont le champ `Branch` correspond à cette branche.
Un handoff aux métadonnées `Status` ou `Branch` absentes/invalides bloque
également l’écriture. S’il n’existe aucun candidat valide, continuer sans
handoff. Si plusieurs fichiers correspondent, demander lequel fait autorité.

Les faits produit, l’architecture, le pipeline PCB et les contraintes métier ne
doivent pas être recopiés ici. Ils sont maintenus une seule fois dans
`CLAUDE.md` jusqu’à leur future extraction dans un document neutre partagé.

## Précédence

La hiérarchie native système/développeur/utilisateur de la plateforme reste
souveraine. Entre documents du dépôt chargés au même niveau :

1. `AGENTS.md` prévaut uniquement pour l’adaptation des outils Codex.
2. `CLAUDE.md` prévaut pour les règles projet partagées.
3. `docs/agents/COLLABORATION.md` organise le transfert sans modifier ces règles.
4. Le handoff actif est informatif et ne crée aucune nouvelle autorité.

Pour déterminer l’état réel d’une implémentation, le code, les migrations et
les tests priment sur les descriptions historiques. Un handoff ne peut jamais
assouplir une règle de sécurité ou une quality gate.

## Adaptation des instructions Claude vers Codex

- Avant toute tâche, appliquer `cirqix-prompt-improver` : l’invoquer réellement
  s’il est exposé dans la session ; sinon appliquer le fallback ci-dessous.
- Utiliser en priorité les skills exposés dans la session ou présents sous
  `.agents/skills/`.
- Si un skill Cirqix obligatoire n’est pas exposé mais existe dans
  `.claude/skills/<skill>/SKILL.md`, lire ce fichier en entier et annoncer
  explicitement le fallback d’instructions du dépôt. Ne jamais prétendre qu’un
  outil de skill absent a été invoqué.
- Traduire `everything-claude-code:plan` par le plan Codex disponible
  (`update_plan`) lorsqu’aucun skill de planification équivalent n’est installé.
- Traduire le workflow TDD par : critères/tests en échec d’abord, implémentation
  ensuite, puis preuve du passage des tests.
- Traduire `code-reviewer`, `security-reviewer` et `architect` par des sous-agents
  dédiés lorsque ces agents nommés ne sont pas disponibles.
- Traduire `/commit-commands:commit-push-pr` par les commandes Git explicites du
  dépôt si ce plugin n’est pas installé ; ne jamais inventer son exécution.
- Les règles `.claude/rules/planning.md`, `.claude/rules/git.md` et
  `.claude/rules/code.md` restent des règles projet applicables. Le préfixe
  `.claude` indique leur emplacement, pas une exclusion de Codex.
- Les mentions de Claude, Sonnet ou Haiku dans l’architecture produit désignent
  le runtime Anthropic de Cirqix. Elles ne doivent pas être remplacées par Codex.

## Workflow Codex obligatoire

1. Améliorer le prompt et annoncer le skill réellement utilisé.
2. Examiner `git status` et le handoff actif avant toute écriture.
3. Pour une tâche touchant au moins deux fichiers, maintenir un plan explicite.
4. Définir les critères de réussite ou tests avant l’implémentation.
5. Pour une tâche partagée, parallèle, transférée ou longue, revendiquer la
   tâche et les chemins dans un handoff dédié.
6. Si un handoff est requis, implémenter uniquement dans les chemins revendiqués.
   Sinon, rester dans le périmètre explicitement demandé et préserver les
   modifications préexistantes.
7. Faire relire l’implémentation ; ajouter une revue sécurité pour auth,
   paiement, secrets, RPC, RLS ou endpoints exposés.
8. Exécuter les validations proportionnées au risque, dont `pnpm type-check`
   avant tout commit lorsqu’il est disponible.
9. Si un handoff existe, l’owner le met à jour avec les commandes et résultats
   exacts ; un reviewer en lecture seule renvoie seulement ses constats.
10. Stager uniquement les fichiers possédés, puis commit, push et PR selon les
    règles Git du projet.

## Collaboration et propriété

- Une tâche a un seul propriétaire actif.
- Une branche ou un worktree correspond à une tâche clairement délimitée.
- Deux agents ne modifient jamais simultanément le même fichier.
- Un reviewer reste en lecture seule jusqu’à un transfert explicite.
- Avant de reprendre le travail de Claude, Codex vérifie le content commit, le
  head Git courant, le diff, les validations et l’état du worktree indiqués
  dans le handoff.
- Codex ne stage, ne restaure et ne commit jamais les changements préexistants
  de Claude ou de l’utilisateur.
- Tout transfert utilise `docs/agents/HANDOFF_TEMPLATE.md` et produit un fichier
  `docs/agents/handoffs/<task-id>.md`.

## Sécurité absolue

- Ne jamais écrire de secret, token, cookie, clé API ou contenu de `.env` dans
  un prompt, un log, un handoff, un commit ou une PR.
- `.codex/config.toml` est une configuration locale secrète : elle ne doit jamais
  être suivie par Git.
- Appliquer sans exception les quality gates PCB et la confirmation JLCPCB
  définies dans `CLAUDE.md` ; l’adaptateur Codex ne les redéfinit pas.

## Fin de tâche

Lorsqu’un handoff existe, il doit contenir avant la fin de tâche : périmètre
réalisé, fichiers modifiés, décisions, validations exactes, risques restants,
état Git, commit/PR éventuels et prochaine action atomique.

Après un commit ou une PR, terminer la réponse avec l’unique bloc
`## Prochaine étape recommandée` exigé par `CLAUDE.md`.
