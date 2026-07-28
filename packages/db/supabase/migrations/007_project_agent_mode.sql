-- Phase 5 — provenance du board, pour que le gate JLCPCB ne soit pas dupable.
--
-- resolveAgentMode() renvoie 'simulator' par DÉFAUT (il faut
-- CIRQIX_AGENT_MODE=orchestrator|real pour le pipeline réel), et simulator.ts
-- persiste status:'DRC_CLEAN' avec des drcViolations:[] fabriqués. Le gate de
-- POST /api/jlcpcb/order ne regardait que projects.status : un board entièrement
-- simulé atteignait donc l'état qui autorise une commande de fabrication.
--
-- La colonne enregistre qui a produit l'état courant du projet. Volontairement
-- NULLABLE et SANS valeur par défaut : NULL = provenance inconnue (projets
-- antérieurs à cette migration). Le gate est fail closed — il n'accepte que
-- 'orchestrator' explicite, car « inconnu » n'est pas « vérifié ». Les projets
-- existants devront donc être rejoués par le pipeline réel avant commande ;
-- c'est voulu, et sans conséquence aujourd'hui puisque /api/jlcpcb/order est
-- encore un stub qui ne contacte aucune API JLCPCB.
--
-- Idempotent : réapplicable sans effet de bord.

ALTER TABLE projects ADD COLUMN IF NOT EXISTS agent_mode text;

ALTER TABLE projects DROP CONSTRAINT IF EXISTS projects_agent_mode_check;

ALTER TABLE projects ADD CONSTRAINT projects_agent_mode_check CHECK (
  agent_mode IS NULL OR agent_mode IN ('simulator', 'orchestrator')
);

COMMENT ON COLUMN projects.agent_mode IS
  'Producteur de l''état courant : orchestrator (pipeline réel, commandable) '
  'ou simulator (états fabriqués, non commandable). NULL = provenance inconnue, '
  'refusée par le gate JLCPCB.';
