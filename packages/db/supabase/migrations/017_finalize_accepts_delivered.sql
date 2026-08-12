-- 017 — La finalisation accepte aussi `PCB_LIVRÉ` (défaut trouvé le 2026-08-12).
--
-- DÉFAUT CORRIGÉ
--
-- `prompts.ts` fait enchaîner l'export APRÈS le DRC : un pipeline qui réussit
-- COMPLÈTEMENT se termine donc en `PCB_LIVRÉ`, jamais en `DRC_CLEAN`. Or les
-- trois couches de la finalisation n'acceptaient que `DRC_CLEAN` :
--
--   1. le pont SSE levait sur le `done` (exception avalée par son propre
--      `catch`, donc erreur affichée et run « terminé » sans débit) ;
--   2. `finalizePipelineSuccess` (TS) rejetait l'état ;
--   3. cette RPC le rejetait aussi, et forçait `status = 'DRC_CLEAN'`.
--
-- Conséquence : sur le chemin NOMINAL, `finalize_pipeline_success` n'était
-- jamais appelée. Aucun débit — alors que le board, ses Gerbers et
-- `agent_mode: 'orchestrator'` venaient d'être persistés par le pont, et que
-- `POST /api/jlcpcb/order` accepte `PCB_LIVRÉ`. Un PCB fabricable, commandable
-- et gratuit.
--
-- C'est le MIROIR des défauts corrigés cette semaine. Toutes les gardes
-- existantes vérifient qu'un statut de succès n'est pas accordé SANS contrôle ;
-- aucune ne vérifiait qu'un contrôle réussi aboutit bien à un DÉBIT. Trouvé par
-- deux audits externes indépendants (Grok, Codex) le même jour.
--
-- POURQUOI `PCB_LIVRÉ` N'AFFAIBLIT PAS LA GARDE
--
-- `handleExport` n'émet `PCB_LIVRÉ` QUE si `drc_clean` est vrai en cache,
-- c'est-à-dire après un DRC réellement exécuté ET réellement propre
-- (migration 011 et suivantes). C'est un état strictement PLUS avancé que
-- `DRC_CLEAN` : l'accepter élargit la facturation aux pipelines les plus
-- complets, pas aux moins vérifiés.
--
-- Le statut écrit est désormais celui RÉELLEMENT atteint, plus un `DRC_CLEAN`
-- codé en dur : rétrograder un run allé jusqu'aux Gerbers ferait « reculer » le
-- projet aux yeux de l'utilisateur.
--
-- Recopie conforme de 015 ; seuls le contrôle d'entrée, la garde de rejeu et
-- l'UPDATE final changent. On ne réécrit jamais une migration appliquée.

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
  v_final_status text;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: finalize_pipeline_success requires service role'
      USING ERRCODE = '42501';
  END IF;

  IF p_agent_mode IS NULL OR p_agent_mode NOT IN ('orchestrator', 'simulator') THEN
    RAISE EXCEPTION 'invalid_agent_mode' USING ERRCODE = '22023';
  END IF;

  v_final_status := p_pcb_state ->> 'status';

  IF p_iteration_count IS NULL OR p_iteration_count < 1
     OR p_pcb_state IS NULL OR jsonb_typeof(p_pcb_state) <> 'object'
     -- SEUL CHANGEMENT DE FOND : deux etats terminaux facturables.
     OR v_final_status IS NULL
     OR v_final_status NOT IN ('DRC_CLEAN', 'PCB_LIVRÉ')
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

  -- Garde de rejeu : la meme iteration deja finalisee ne facture pas deux fois.
  -- Elle couvre desormais les DEUX etats terminaux — sinon un rejeu en
  -- `PCB_LIVRÉ` sur une iteration deja facturee passerait au travers.
  IF v_project.iteration_count = p_iteration_count
     AND v_project.status IN ('DRC_CLEAN', 'PCB_LIVRÉ') THEN
    RETURN false;
  END IF;

  IF p_iteration_count <> coalesce(v_project.iteration_count, 0) + 1 THEN
    RAISE EXCEPTION 'stale_iteration' USING ERRCODE = '22023';
  END IF;

  UPDATE public.credit_reservations
  SET released_at = now()
  WHERE user_id = p_user_id
    AND project_id = p_project_id
    AND released_at IS NULL;

  IF p_agent_mode = 'orchestrator' THEN
    PERFORM public.deduct_credits(
      p_user_id,
      8.5,
      'full_pcb_pipeline',
      p_project_id
    );
  END IF;

  UPDATE public.projects
  SET status = v_final_status,   -- l'etat REELLEMENT atteint, plus un litteral
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
