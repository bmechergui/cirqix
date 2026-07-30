-- Project integrity hardening.
-- Pipeline-owned fields are no longer writable by authenticated clients.
-- A service-role RPC atomically charges one iteration and publishes DRC_CLEAN.

DROP POLICY IF EXISTS projects_own ON public.projects;
DROP POLICY IF EXISTS projects_select_own ON public.projects;
DROP POLICY IF EXISTS projects_insert_own ON public.projects;
DROP POLICY IF EXISTS projects_update_own ON public.projects;
DROP POLICY IF EXISTS projects_delete_own ON public.projects;

CREATE POLICY projects_select_own ON public.projects
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

CREATE POLICY projects_insert_own ON public.projects
  FOR INSERT TO authenticated
  WITH CHECK ((SELECT auth.uid()) = user_id);

CREATE POLICY projects_update_own ON public.projects
  FOR UPDATE TO authenticated
  USING ((SELECT auth.uid()) = user_id)
  WITH CHECK ((SELECT auth.uid()) = user_id);

CREATE POLICY projects_delete_own ON public.projects
  FOR DELETE TO authenticated
  USING ((SELECT auth.uid()) = user_id);

REVOKE ALL PRIVILEGES ON TABLE public.projects FROM PUBLIC, anon, authenticated;
GRANT SELECT, DELETE ON TABLE public.projects TO authenticated;
GRANT INSERT (user_id, name, description) ON TABLE public.projects TO authenticated;
GRANT UPDATE (name, description) ON TABLE public.projects TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.projects TO service_role;

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

  PERFORM public.deduct_credits(
    p_user_id,
    8.5,
    'full_pcb_pipeline',
    p_project_id
  );

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

REVOKE EXECUTE ON FUNCTION public.deduct_credits(uuid, numeric, text, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.deduct_credits(uuid, numeric, text, uuid)
  TO service_role;

CREATE OR REPLACE FUNCTION public.upsert_community_footprint(
  p_name text,
  p_part_number text,
  p_source text,
  p_kicad_mod text DEFAULT NULL,
  p_embedding vector(1536) DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_id uuid;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: upsert_community_footprint requires service role'
      USING ERRCODE = '42501';
  END IF;

  INSERT INTO public.footprints (
    name, part_number, source, kicad_mod, embedding, is_community, validated
  ) VALUES (
    p_name, p_part_number, p_source, p_kicad_mod, p_embedding, true, true
  )
  ON CONFLICT (part_number) WHERE is_community = true AND part_number IS NOT NULL
  DO UPDATE SET
    embedding = coalesce(EXCLUDED.embedding, public.footprints.embedding),
    updated_at = now()
  RETURNING id INTO v_id;

  RETURN v_id;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.upsert_community_footprint(text, text, text, text, vector)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.upsert_community_footprint(text, text, text, text, vector)
  TO service_role;

CREATE INDEX IF NOT EXISTS idx_credit_transactions_project_id
  ON public.credit_transactions(project_id);

CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SET search_path = ''
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;
