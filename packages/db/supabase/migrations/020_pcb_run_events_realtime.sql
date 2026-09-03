-- 020 — Publier pcb_run_events sur Supabase Realtime.
--
-- Le navigateur suit un run 15–20 min. Le sondage HTTP
-- (`GET /api/agent/runs/:runId/events`) reste le repli et le catch-up.
-- Pour que le transport principal fonctionne, Postgres doit diffuser les
-- INSERT du journal.
--
-- REPLICA IDENTITY FULL : exigence Supabase Realtime + RLS (et les old-tuples
-- d'un UPDATE/DELETE). L'INSERT WAL porte déjà la ligne complète en DEFAULT ;
-- FULL reste le réglage documenté, pas un substitut de la politique SQL.
--
-- ⚠️ Ne PAS ajouter `pcb_runs` à la publication : le client lit le journal,
-- pas le cycle de vie. Heartbeat toutes les 30 s = du bruit, et un UPDATE
-- de statut n'est pas un événement d'orchestrateur.
--
-- La publication `supabase_realtime` n'existe que sur une instance Supabase.
-- Sur un PostgreSQL nu (CI `rls_isolation.sql`) l'ALTER est un no-op.

ALTER TABLE public.pcb_run_events REPLICA IDENTITY FULL;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime')
     AND NOT EXISTS (
       SELECT 1
         FROM pg_publication_tables
        WHERE pubname = 'supabase_realtime'
          AND schemaname = 'public'
          AND tablename = 'pcb_run_events'
     )
  THEN
    ALTER PUBLICATION supabase_realtime ADD TABLE public.pcb_run_events;
  END IF;
END $$;

-- InitPlan : même règle que 010/011/014. Cette politique est désormais le
-- chemin chaud Realtime (un INSERT toutes les ~250 ms de tokens agrégés).
DROP POLICY IF EXISTS pcb_run_events_select_own ON public.pcb_run_events;
CREATE POLICY pcb_run_events_select_own ON public.pcb_run_events
  FOR SELECT TO authenticated
  USING (EXISTS (
    SELECT 1 FROM public.pcb_runs r
    WHERE r.id = pcb_run_events.run_id
      AND r.user_id = (SELECT auth.uid())
  ));

DROP POLICY IF EXISTS pcb_runs_select_own ON public.pcb_runs;
CREATE POLICY pcb_runs_select_own ON public.pcb_runs
  FOR SELECT TO authenticated
  USING (user_id = (SELECT auth.uid()));

-- Même barrière GRANT que projects/credits : sans write policy, un GRANT ALL
-- héritée laisserait une future policy INSERT ouvrir l'écriture client.
REVOKE ALL PRIVILEGES ON TABLE public.pcb_runs FROM PUBLIC, anon, authenticated;
REVOKE ALL PRIVILEGES ON TABLE public.pcb_run_events FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.pcb_runs TO authenticated;
GRANT SELECT ON TABLE public.pcb_run_events TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.pcb_runs TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.pcb_run_events TO service_role;
