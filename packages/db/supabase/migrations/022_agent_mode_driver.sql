-- Provenance « driver » : la chaîne réelle, sans le moindre appel au modèle.
--
-- POURQUOI UNE QUATRIÈME VALEUR, ET PAS UNE DES TROIS EXISTANTES
--
-- Le solde de l'API du modèle est épuisé depuis le 2026-09-06. L'orchestrateur
-- étant la première étape du pipeline, plus aucun PCB ne peut aboutir par la
-- voie normale — et `call_agent_schema` est le SEUL maillon de la chaîne qui
-- appelle un modèle. Le banc des dix cartes a mesuré que tout le reste va
-- jusqu'aux Gerbers sans lui : 5 à 70 composants, 100 % routées, 0 erreur.
--
-- Aucune des trois provenances existantes ne dit la vérité sur ces runs :
--
--   simulator      états FABRIQUÉS. Ici tout est réel, DRC compris.
--   local_fallback vrais handlers, mais footprint/gen_pcb/export SAUTÉS.
--                  La chaîne du driver les exécute tous.
--   orchestrator   la boucle autonome Sonnet, qui n'a pas tourné.
--
-- Réutiliser l'une d'elles serait un mensonge inscrit en base, et ce dépôt en
-- a déjà payé plusieurs — un rapport DRC vide lu « 0 erreur », un `via_count`
-- jamais calculé rendu à zéro. Une provenance inexacte est du même ordre : elle
-- se lit comme une mesure.
--
-- CE QUE CETTE VALEUR N'ACCORDE PAS
--
-- `POST /api/jlcpcb/order` exige `agent_mode = 'orchestrator'` et échoue fermé
-- sur toute autre valeur. Un board du driver est donc NON COMMANDABLE, quelle
-- que soit sa qualité — et c'est voulu : le schéma n'a pas traversé la boucle
-- autonome que le produit vend. Cette migration ne touche pas au gate, et il ne
-- faut PAS l'assouplir pour laisser passer un board du driver.
--
-- Élargir un CHECK est additif : aucune ligne existante ne peut le violer.

alter table pcb_runs drop constraint if exists pcb_runs_agent_mode_check;
alter table pcb_runs add constraint pcb_runs_agent_mode_check
  check (agent_mode = any (array['orchestrator', 'local_fallback', 'simulator', 'driver']));

alter table projects drop constraint if exists projects_agent_mode_check;
alter table projects add constraint projects_agent_mode_check
  check (agent_mode is null
         or agent_mode = any (array['simulator', 'orchestrator', 'local_fallback', 'driver']));
