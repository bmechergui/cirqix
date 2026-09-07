-- `finalize_pipeline_success` accepte la provenance « driver ».
--
-- UN SEUL CHANGEMENT par rapport à la migration 018 : la liste des provenances
-- valides. Tout le reste du corps est reproduit à l'identique, y compris la
-- garde de rôle, `stale_iteration`, la libération de la retenue et la
-- vérification de propriété du projet.
--
-- ⚠️ LA FACTURATION NE BOUGE PAS. Le débit reste conditionné à
-- `p_agent_mode = 'orchestrator'` : un run du driver ne consomme aucun crédit.
-- C'est cohérent — l'utilisateur n'a pas payé un modèle qui n'a pas tourné, et
-- le schéma vient de l'extérieur du produit.
--
-- ⚠️ ET ELLE N'ACCORDE PAS LA COMMANDABILITÉ. `POST /api/jlcpcb/order` exige
-- `agent_mode = 'orchestrator'` et échoue fermé sur toute autre valeur. Un board
-- du driver est réel et fabricable, mais non commandable — il n'a pas traversé
-- la boucle autonome que le produit vend. Ne PAS assouplir ce gate.
--
-- Sans cette migration, un run du driver arrivé jusqu'à `PCB_LIVRÉ` lèverait
-- `invalid_agent_mode` à la toute dernière étape : tout le travail fait, et le
-- run marqué en échec.

CREATE OR REPLACE FUNCTION public.finalize_pipeline_success(
  p_user_id uuid,
  p_project_id uuid,
  p_iteration_count integer,
  p_pcb_state jsonb,
  p_agent_mode text
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO ''
AS $function$
DECLARE
  v_project public.projects%ROWTYPE;
  v_state_iteration integer;
  v_final_status text;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: finalize_pipeline_success requires service role'
      USING ERRCODE = '42501';
  END IF;

  -- SEULE LIGNE MODIFIÉE : « driver » rejoint les provenances connues.
  IF p_agent_mode IS NULL
     OR p_agent_mode NOT IN ('orchestrator', 'simulator', 'local_fallback', 'driver') THEN
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

  -- Seul le pipeline COMPLET facture. « driver » ne facture pas : aucun modèle
  -- n'a tourné, et le schéma vient de l'extérieur du produit.
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
$function$;

REVOKE EXECUTE ON FUNCTION public.finalize_pipeline_success(uuid, uuid, integer, jsonb, text)
  FROM anon, authenticated;
