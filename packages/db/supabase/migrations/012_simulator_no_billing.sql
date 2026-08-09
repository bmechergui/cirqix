-- 012 — Le mode simulateur ne facture plus.
--
-- Défaut corrigé : `finalize_pipeline_success` (migration 011) débitait 8,5
-- crédits — le prix d'un PCB complet — sans jamais consulter `p_agent_mode`.
-- Or `resolveAgentMode()` (apps/web/src/app/api/agent/lib/agent-mode.ts) renvoie
-- `simulator` par DÉFAUT : toute installation sans `CIRQIX_AGENT_MODE` tourne en
-- simulateur. Celui-ci fabrique un board « DRC clean » qu'il reconnaît lui-même
-- n'avoir jamais soumis à KiCad, puis appelait cette RPC.
--
-- Conséquence : l'utilisateur payait le prix fort pour une démonstration. Le gate
-- de `POST /api/jlcpcb/order` bloquait bien la commande sur la provenance
-- `agent_mode`, mais rien ne bloquait la facturation.
--
-- La fonction est recopiée à l'identique de 011 ; seul l'appel à `deduct_credits`
-- est désormais conditionné au mode `orchestrator`. La persistance du projet
-- (statut, pcb_state, iteration_count, agent_mode) reste inchangée dans les deux
-- modes : le simulateur doit rester utilisable comme démonstration.
--
-- On ne réécrit jamais une migration déjà appliquée : 011 est en production,
-- d'où cette 012.

CREATE OR REPLACE FUNCTION public.finalize_pipeline_success(
  p_user_id uuid,
  p_project_id uuid,
  p_iteration_count integer,
  p_pcb_state jsonb,
  p_agent_mode text
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_project public.projects%ROWTYPE;
  v_state_iteration integer;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: finalize_pipeline_success requires service role'
      USING ERRCODE = '42501';
  END IF;

  IF p_agent_mode IS NULL OR p_agent_mode NOT IN ('orchestrator', 'simulator') THEN
    RAISE EXCEPTION 'invalid_agent_mode' USING ERRCODE = '22023';
  END IF;

  IF p_iteration_count IS NULL OR p_iteration_count < 1
     OR p_pcb_state IS NULL OR jsonb_typeof(p_pcb_state) <> 'object'
     OR p_pcb_state ->> 'status' IS DISTINCT FROM 'DRC_CLEAN'
     OR p_pcb_state ->> 'projectId' IS DISTINCT FROM p_project_id::text
     OR jsonb_typeof(p_pcb_state -> 'iteration') IS DISTINCT FROM 'number' THEN
    RAISE EXCEPTION 'invalid_final_state' USING ERRCODE = '22023';
  END IF;

  BEGIN
    v_state_iteration := (p_pcb_state ->> 'iteration')::integer;
  EXCEPTION WHEN invalid_text_representation OR numeric_value_out_of_range THEN
    RAISE EXCEPTION 'invalid_final_state' USING ERRCODE = '22023';
  END;

  IF v_state_iteration <> p_iteration_count THEN
    RAISE EXCEPTION 'iteration_mismatch' USING ERRCODE = '22023';
  END IF;

  SELECT * INTO v_project
  FROM public.projects
  WHERE id = p_project_id
  FOR UPDATE;

  IF NOT FOUND OR v_project.user_id <> p_user_id THEN
    RAISE EXCEPTION 'invalid_project: project does not belong to user'
      USING ERRCODE = '22023';
  END IF;

  IF v_project.iteration_count = p_iteration_count
     AND v_project.status = 'DRC_CLEAN' THEN
    RETURN false;
  END IF;

  IF p_iteration_count <> coalesce(v_project.iteration_count, 0) + 1 THEN
    RAISE EXCEPTION 'stale_iteration' USING ERRCODE = '22023';
  END IF;

  -- SEUL CHANGEMENT PAR RAPPORT À 011 : on ne facture que le pipeline réel.
  -- Un board simulé n'a été validé par aucun DRC ; il ne peut pas coûter le prix
  -- d'un PCB fabricable.
  IF p_agent_mode = 'orchestrator' THEN
    PERFORM public.deduct_credits(
      p_user_id,
      8.5,
      'full_pcb_pipeline',
      p_project_id
    );
  END IF;

  UPDATE public.projects
  SET status = 'DRC_CLEAN',
      pcb_state = p_pcb_state,
      iteration_count = p_iteration_count,
      agent_mode = p_agent_mode,
      updated_at = now()
  WHERE id = p_project_id;

  RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.finalize_pipeline_success(uuid, uuid, integer, jsonb, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.finalize_pipeline_success(uuid, uuid, integer, jsonb, text)
  TO service_role;
