-- 015 — Réservation de crédits pendant le pipeline (issue #117).
--
-- Défaut corrigé : `POST /api/agent` lisait le solde, le jugeait suffisant, puis
-- lançait un pipeline pouvant durer 300 s ; le débit n'arrivait qu'à la fin,
-- dans `finalize_pipeline_success`. Entre les deux, RIEN n'engageait le crédit :
-- N requêtes simultanées lisaient le même solde et passaient toutes le contrôle.
-- Le débit final restait exact — ce n'est pas un vol de crédits — mais chaque
-- pipeline consommait Sonnet, le service KiCad et Freerouting.
--
-- Le quota par utilisateur (PR #120) borne la CADENCE d'allumage ; il ignore le
-- solde et il est fail-open. C'est ici que se pose la garantie durable.
--
-- Invariant : disponible = credits.balance − Σ(réservations actives).
-- Une réservation est active tant qu'elle n'est ni libérée ni expirée.
--
-- Sérialisation : `reserve_pipeline_credits` verrouille la ligne `credits` du
-- porteur en `FOR UPDATE` — le même mécanisme que `deduct_credits`. Deux
-- réservations concurrentes du même utilisateur s'ordonnent donc ; la seconde
-- voit la première et ne peut plus se croire seule sur le solde.
--
-- Expiration : un pipeline dont le processus meurt ne libérera jamais sa
-- réservation. `expires_at` est le filet — sans lui, un crash gèlerait le crédit
-- pour toujours. Le TTL applicatif (360 s) couvre `maxDuration = 300 s` avec une
-- marge ; il n'existe volontairement AUCUN nettoyage périodique : une ligne
-- expirée cesse simplement de compter, et rester en table la garde auditable.

CREATE TABLE IF NOT EXISTS public.credit_reservations (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     uuid NOT NULL REFERENCES auth.users,
  project_id  uuid NOT NULL REFERENCES public.projects ON DELETE CASCADE,
  amount      numeric(10, 2) NOT NULL CHECK (amount > 0),
  created_at  timestamptz NOT NULL DEFAULT now(),
  expires_at  timestamptz NOT NULL,
  released_at timestamptz
);

-- Le seul accès chaud : la somme des réservations actives d'un utilisateur,
-- calculée sous le verrou, donc sur le chemin critique de chaque démarrage.
CREATE INDEX IF NOT EXISTS credit_reservations_active_idx
  ON public.credit_reservations (user_id)
  WHERE released_at IS NULL;

ALTER TABLE public.credit_reservations ENABLE ROW LEVEL SECURITY;

-- Lecture de ses propres retenues (« pourquoi mon solde disponible est-il plus
-- bas que mon solde ? »). AUCUNE politique d'écriture : seul le service_role,
-- qui contourne RLS, crée et libère des réservations. Un client capable
-- d'insérer une réservation pourrait geler son propre solde — nuisance mineure
-- — mais surtout en libérer une, ce qui rouvrirait exactement la fenêtre que
-- cette migration ferme.
DROP POLICY IF EXISTS credit_reservations_select_own ON public.credit_reservations;
CREATE POLICY credit_reservations_select_own ON public.credit_reservations
  FOR SELECT TO authenticated
  USING (auth.uid() = user_id);

-- ---------------------------------------------------------------------------
-- Solde réellement engageable.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.available_credits(p_user_id uuid)
RETURNS numeric
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = ''
AS $$
  SELECT coalesce(
           (SELECT c.balance FROM public.credits c WHERE c.user_id = p_user_id),
           0
         )
       - coalesce(
           (SELECT sum(r.amount)
            FROM public.credit_reservations r
            WHERE r.user_id = p_user_id
              AND r.released_at IS NULL
              AND r.expires_at > now()),
           0
         );
$$;

-- SECURITY DEFINER : sans restriction, cette fonction révélerait le solde de
-- n'importe quel utilisateur à partir de son seul UUID.
REVOKE EXECUTE ON FUNCTION public.available_credits(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.available_credits(uuid) TO service_role;

-- ---------------------------------------------------------------------------
-- Poser une retenue.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.reserve_pipeline_credits(
  p_user_id uuid,
  p_project_id uuid,
  p_amount numeric,
  p_ttl_seconds integer
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_balance numeric;
  v_held numeric;
  v_id uuid;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: reserve_pipeline_credits requires service role'
      USING ERRCODE = '42501';
  END IF;

  IF p_amount IS NULL OR p_amount < 0.01 OR p_amount <> round(p_amount, 2) THEN
    RAISE EXCEPTION 'invalid_amount: use a positive amount with at most 2 decimals'
      USING ERRCODE = '22023';
  END IF;

  -- Une retenue sans borne supérieure crédible serait un moyen de geler un
  -- solde durablement.
  IF p_ttl_seconds IS NULL OR p_ttl_seconds < 1 OR p_ttl_seconds > 3600 THEN
    RAISE EXCEPTION 'invalid_ttl: expected 1..3600 seconds'
      USING ERRCODE = '22023';
  END IF;

  IF NOT EXISTS (
    SELECT 1 FROM public.projects
    WHERE id = p_project_id AND user_id = p_user_id
  ) THEN
    RAISE EXCEPTION 'invalid_project: project does not belong to user'
      USING ERRCODE = '22023';
  END IF;

  -- LE point de sérialisation. Tout ce qui suit lit un état que personne
  -- d'autre ne peut modifier pour cet utilisateur avant le COMMIT.
  SELECT balance INTO v_balance
  FROM public.credits
  WHERE user_id = p_user_id
  FOR UPDATE;

  IF v_balance IS NULL THEN
    RAISE EXCEPTION 'user_not_found' USING ERRCODE = '22023';
  END IF;

  SELECT coalesce(sum(amount), 0) INTO v_held
  FROM public.credit_reservations
  WHERE user_id = p_user_id
    AND released_at IS NULL
    AND expires_at > now();

  IF v_balance - v_held < p_amount THEN
    RAISE EXCEPTION 'insufficient_credits' USING ERRCODE = '22023';
  END IF;

  -- UNE SEULE retenue active par projet.
  --
  -- Sans cette garde, un double-clic ou un réessai après timeout pose deux
  -- retenues sur le même projet ; `finalize_pipeline_success` libère par
  -- (utilisateur, projet) et le premier run à finaliser lèverait donc AUSSI la
  -- retenue du second, encore en cours — la course reviendrait, simplement
  -- déplacée. C'est le verrou `FOR UPDATE` ci-dessus qui rend ce contrôle sûr :
  -- deux appels concurrents du même utilisateur sont sérialisés, le second voit
  -- forcément la retenue du premier.
  --
  -- La contrainte est de toute façon celle du domaine : deux pipelines sur un
  -- même projet se disputeraient `iteration_count` et le second échouerait sur
  -- `stale_iteration`. Autant le refuser tout de suite, et gratuitement.
  IF EXISTS (
    SELECT 1 FROM public.credit_reservations
    WHERE project_id = p_project_id
      AND released_at IS NULL
      AND expires_at > now()
  ) THEN
    RAISE EXCEPTION 'pipeline_already_running' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.credit_reservations (user_id, project_id, amount, expires_at)
  VALUES (
    p_user_id,
    p_project_id,
    p_amount,
    now() + make_interval(secs => p_ttl_seconds)
  )
  RETURNING id INTO v_id;

  RETURN v_id;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.reserve_pipeline_credits(uuid, uuid, numeric, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.reserve_pipeline_credits(uuid, uuid, numeric, integer)
  TO service_role;

-- ---------------------------------------------------------------------------
-- Lever une retenue. Idempotent : appelée depuis un `finally`, elle peut
-- suivre une libération déjà faite par la finalisation.
--
-- Elle ne vérifie PAS que la retenue appartient à l'appelant : elle est
-- réservée au service_role, et l'identifiant qu'elle reçoit provient toujours
-- d'un `reserve_pipeline_credits` du même processus. Un identifiant venu du
-- client permettrait de libérer la retenue d'autrui — donc jamais l'exposer sur
-- une route.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.release_pipeline_reservation(p_reservation_id uuid)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_released boolean;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: release_pipeline_reservation requires service role'
      USING ERRCODE = '42501';
  END IF;

  UPDATE public.credit_reservations
  SET released_at = now()
  WHERE id = p_reservation_id
    AND released_at IS NULL;

  GET DIAGNOSTICS v_released = ROW_COUNT;
  RETURN v_released;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.release_pipeline_reservation(uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.release_pipeline_reservation(uuid)
  TO service_role;

-- ---------------------------------------------------------------------------
-- La finalisation consomme la retenue.
--
-- Recopie conforme de 012 ; le SEUL ajout est la libération des réservations
-- actives du couple (utilisateur, projet), DANS LA MÊME TRANSACTION que le
-- débit. L'ordre importe peu, l'atomicité seule compte : libérer dans une
-- transaction séparée ouvrirait un intervalle où le solde a déjà baissé pendant
-- que la retenue compte encore — le crédit serait décompté deux fois, jusqu'à
-- expiration. C'est l'exact symétrique du défaut que cette migration corrige.
--
-- La libération est inconditionnelle : en mode simulateur aucune retenue n'est
-- posée (le simulateur ne facture pas, cf. 012), donc l'UPDATE ne trouve rien.
-- On ne réécrit jamais une migration appliquée : 012 est en production.
-- ---------------------------------------------------------------------------
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

  -- AJOUT 015 : la retenue a rempli son office, le débit réel la remplace.
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
