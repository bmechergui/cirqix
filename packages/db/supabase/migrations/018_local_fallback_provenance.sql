-- 018 — Le repli local a sa propre provenance (audit du 2026-08-12).
--
-- DÉFAUT CORRIGÉ
--
-- `runLocalPipeline` s'arme quand le quota Anthropic est épuisé et enchaîne
-- CINQ étapes sur huit : schéma → ERC → placement → routage → DRC.
--
-- Absents : la résolution des FOOTPRINTS (③), la génération native du PCB (④)
-- et l'EXPORT (⑧). Le board repose donc sur le générateur TypeScript de repli,
-- celui-là même dont deux défauts électriques viennent d'être corrigés (PR #135
-- pads sans net, PR #136 broches écrasées sur le pad 1).
--
-- Il se déclarait pourtant `agent_mode: 'orchestrator'` — la provenance qui
-- ouvre le gate JLCPCB — et facturait 8,5 crédits, le prix du pipeline COMPLET.
--
-- Un board sans footprints résolus ni PCB généré nativement devenait ainsi
-- commandable au prix fort. Signalé indépendamment par les deux audits.
--
-- POURQUOI UNE TROISIÈME VALEUR PLUTÔT QU'UN MENSONGE DANS UN SENS OU L'AUTRE
--
-- `simulator` serait faux : ce repli exécute les VRAIS handlers contre le vrai
-- service KiCad, il ne fabrique rien. `orchestrator` est faux aussi : il saute
-- trois étapes qui conditionnent la fabricabilité.
--
-- C'est une troisième provenance, et la nommer est la seule façon de ne pas
-- mentir. Le gate JLCPCB n'accepte que `orchestrator` (`agent_mode !==
-- 'orchestrator'` → refus) : `local_fallback` est donc refusé sans changer une
-- ligne de la route de commande — le fail-closed jouait déjà, il lui manquait
-- une valeur honnête à refuser.
--
-- FACTURATION
--
-- `finalize_pipeline_success` ne débite que pour `orchestrator`. Un run
-- `local_fallback` ne facture donc RIEN. C'est un choix conservateur et
-- assumé : le repli s'arme sur un épuisement de quota Anthropic, une
-- défaillance de NOTRE côté, pas du fait de l'utilisateur. Facturer le prix
-- plein pour cinq étapes sur huit était l'anomalie ; facturer un montant
-- partiel supposerait une décision tarifaire qui n'appartient pas au code.

ALTER TABLE public.projects DROP CONSTRAINT IF EXISTS projects_agent_mode_check;

ALTER TABLE public.projects ADD CONSTRAINT projects_agent_mode_check CHECK (
  agent_mode IS NULL OR agent_mode IN ('simulator', 'orchestrator', 'local_fallback')
);

COMMENT ON COLUMN public.projects.agent_mode IS
  'Producteur de l''état courant : orchestrator (pipeline réel COMPLET, seul '
  'commandable) · local_fallback (vrais handlers mais footprint/gen_pcb/export '
  'sautés — non commandable, non facturé) · simulator (états fabriqués, non '
  'commandable). NULL = provenance inconnue, refusée par le gate JLCPCB.';

-- Recopie conforme de 017 ; seule la liste des provenances acceptées change.
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

  -- SEUL CHANGEMENT DE FOND : `local_fallback` est une provenance valide.
  IF p_agent_mode IS NULL
     OR p_agent_mode NOT IN ('orchestrator', 'simulator', 'local_fallback') THEN
    RAISE EXCEPTION 'invalid_agent_mode' USING ERRCODE = '22023';
  END IF;

  v_final_status := p_pcb_state ->> 'status';

  IF p_iteration_count IS NULL OR p_iteration_count < 1
     OR p_pcb_state IS NULL OR jsonb_typeof(p_pcb_state) <> 'object'
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

  -- Seul le pipeline COMPLET facture. Ni le simulateur (012) ni le repli local
  -- ne débitent : le premier ne valide rien, le second saute trois étapes.
  IF p_agent_mode = 'orchestrator' THEN
    PERFORM public.deduct_credits(
      p_user_id,
      8.5,
      'full_pcb_pipeline',
      p_project_id
    );
  END IF;

  UPDATE public.projects
  SET status = v_final_status,
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
