-- 019 — Le pipeline devient un job : cycle de vie et journal de progression.
--
-- Mesuré le 2026-08-19 sur le board STM32 de `examples/stm32-validation` :
-- génération 3 s, placement 175 s, ROUTAGE 861 s — soit ~17 min au total.
-- `apps/web/src/app/api/agent/route.ts` déclare `maxDuration = 300` : un plafond
-- d'HORLOGE MURALE que la plateforme applique à l'invocation entière. Le routage
-- seul dure presque trois fois ce budget.
--
-- Conséquence : AUCUN PCB complet ne peut aboutir pour un utilisateur réel.
-- La chaîne ne fonctionne aujourd'hui qu'exécutée à la main dans le conteneur,
-- où rien ne la chronomètre. `async` n'y change rien — `await` libère la boucle
-- d'événements de Node, il ne rend pas la main à la plateforme : la fonction
-- reste ouverte tant qu'elle tient le flux SSE.
--
-- Le pipeline sort donc de l'invocation et devient un job exécuté par un worker
-- persistant. Ces deux tables en sont le socle. Elles ne sont encore LUES NI
-- ÉCRITES par personne : cette migration ne change aucun comportement.
--
-- Répartition assumée des rôles (la dérive de l'une vers l'autre est le risque
-- principal de la migration, d'où ce rappel en tête de fichier) :
--   * `pcb_runs`        — cycle de vie du JOB. Éphémère, technique.
--   * `projects`        — état du PRODUIT. Seul `finalize_pipeline_success` y écrit.
--   * Supabase Storage  — les blobs KiCad. Jamais en base.
--   * Redis             — la file et le verrou. JAMAIS l'état PCB.
--
-- ⚠️ Le gate de commande JLCPCB (`apps/web/src/app/api/jlcpcb/order/route.ts`)
-- ne doit JAMAIS être dérivé de `pcb_runs`. Il reste sur `projects.status` et
-- `projects.agent_mode`, écrits par la seule RPC de finalisation. Un run est une
-- tentative ; seul le projet porte un résultat prouvé. Confondre les deux
-- rouvrirait la classe de bugs la plus coûteuse du projet — un statut de succès
-- émis sans que le contrôle correspondant ait tourné.

-- ---------------------------------------------------------------------------
-- Cycle de vie d'un run.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.pcb_runs (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id          uuid NOT NULL REFERENCES public.projects ON DELETE CASCADE,
  user_id             uuid NOT NULL REFERENCES auth.users,

  status              text NOT NULL DEFAULT 'queued'
                        CHECK (status IN ('queued','running','succeeded','failed','cancelled')),

  -- Provenance, posée par la ROUTE à la création — jamais transportée dans le
  -- payload du job. Enfiler un job ne doit pas revenir à décerner la
  -- commandabilité : la RPC de finalisation compare la provenance qu'elle
  -- reçoit à celle enregistrée ici.
  agent_mode          text NOT NULL CHECK (agent_mode IN ('orchestrator','local_fallback','simulator')),

  reservation_id      uuid REFERENCES public.credit_reservations,
  iteration           integer NOT NULL DEFAULT 0 CHECK (iteration >= 0),

  -- Dernière étape TERMINÉE dont l'artefact est écrit en Storage. Permet à une
  -- relance de repartir du dernier état prouvé. Jamais un rattrapage silencieux
  -- au milieu d'un job mort : on ne reprend pas sur un artefact dont on ne peut
  -- pas prouver l'état.
  last_completed_step text,

  -- Renouvelé par le worker toutes les 30 s. Son absence prolongée est la seule
  -- preuve fiable qu'un worker est mort : un job de 30 min est indiscernable
  -- d'un worker figé sans ce battement.
  heartbeat_at        timestamptz,

  cancel_requested    boolean NOT NULL DEFAULT false,
  error               text,

  created_at          timestamptz NOT NULL DEFAULT now(),
  started_at          timestamptz,
  finished_at         timestamptz
);

-- Réconciliation des runs orphelins : `status='running'` sans battement récent.
CREATE INDEX IF NOT EXISTS pcb_runs_alive_idx
  ON public.pcb_runs (heartbeat_at)
  WHERE status = 'running';

-- « Où en est mon projet ? » — le run courant, le plus récent d'abord.
CREATE INDEX IF NOT EXISTS pcb_runs_project_idx
  ON public.pcb_runs (project_id, created_at DESC);

-- Un seul run vivant par projet. Deuxième barrière, indépendante de la
-- déduplication BullMQ (`jobId = projectId`) : si Redis est vidé, celle-ci
-- tient encore. Deux runs concurrents se disputeraient `iteration_count` et le
-- cache de projet.
CREATE UNIQUE INDEX IF NOT EXISTS pcb_runs_one_alive_per_project
  ON public.pcb_runs (project_id)
  WHERE status IN ('queued','running');

ALTER TABLE public.pcb_runs ENABLE ROW LEVEL SECURITY;

-- Lecture de ses propres runs. AUCUNE politique d'écriture : seul le
-- service_role, qui contourne RLS, crée et fait progresser un run. Un client
-- capable d'écrire ici pourrait forger une provenance `orchestrator` — c'est-à-
-- dire la condition d'une commande JLCPCB réelle et payante.
DROP POLICY IF EXISTS pcb_runs_select_own ON public.pcb_runs;
CREATE POLICY pcb_runs_select_own ON public.pcb_runs
  FOR SELECT TO authenticated
  USING (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Journal de progression — remplace le flux SSE, qui mourait avec l'invocation.
-- ---------------------------------------------------------------------------
--
-- Append-only. Le worker écrit, le navigateur lit (Supabase Realtime, polling en
-- repli). Deux propriétés que le SSE n'avait pas : le worker n'a pas besoin
-- d'être joignable depuis le navigateur, et un rechargement de page rejoue
-- l'historique complet — l'utilisateur peut fermer son onglet et revenir.
--
-- ⚠️ Volumétrie : l'orchestrateur émet un événement par delta de token. Une
-- ligne par delta produirait des dizaines de milliers d'INSERT par run. Le
-- worker DOIT agréger les deltas texte (~250 ms) ; les événements structurés
-- (step, status, pcb_state, reasoning, error, done) sont écrits tels quels.
CREATE TABLE IF NOT EXISTS public.pcb_run_events (
  run_id     uuid NOT NULL REFERENCES public.pcb_runs ON DELETE CASCADE,
  seq        bigserial PRIMARY KEY,
  kind       text NOT NULL,
  payload    jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

-- Le seul accès chaud : rejouer un run depuis un curseur (`?since=<seq>`),
-- pour la reprise après coupure Realtime comme pour le repli en polling.
CREATE INDEX IF NOT EXISTS pcb_run_events_replay_idx
  ON public.pcb_run_events (run_id, seq);

ALTER TABLE public.pcb_run_events ENABLE ROW LEVEL SECURITY;

-- Lecture des événements de ses propres runs. Pas d'écriture, même raison que
-- ci-dessus : un client capable d'insérer ici pourrait fabriquer un `done`
-- porteur d'un statut de succès.
DROP POLICY IF EXISTS pcb_run_events_select_own ON public.pcb_run_events;
CREATE POLICY pcb_run_events_select_own ON public.pcb_run_events
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.pcb_runs r
    WHERE r.id = pcb_run_events.run_id
      AND r.user_id = auth.uid()
  ));
