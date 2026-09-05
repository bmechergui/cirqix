-- ---------------------------------------------------------------------------
-- Prolonger une retenue tant que le run prouve qu'il vit.
-- ---------------------------------------------------------------------------
--
-- La retenue posée par `reserve_pipeline_credits` a une échéance FIXE, choisie
-- une fois pour toutes au démarrage. C'est un pari sur la durée du pipeline :
--
--   * trop courte, elle expire pendant que le job tourne — `available_credits`
--     cesse de la compter, un second projet démarre sur le même solde, et les
--     deux consomment le modèle et le service KiCad sans rien engager. C'est
--     exactement la fenêtre que `015_credit_reservations.sql` a fermée, et elle
--     s'était rouverte : 360 s de retenue pour 19 minutes de pipeline mesurées ;
--   * trop longue, elle gèle le solde après un crash du worker, puisque plus
--     rien ne la libère.
--
-- Aucune valeur ne satisfait les deux. Un pipeline dure de 30 s à plus d'une
-- heure selon la carte, et `reserve_pipeline_credits` refuse au-delà de 3600 s.
--
-- ⚠️ LE BATTEMENT DE CŒUR EXISTE DÉJÀ ET NE SERT À RIEN. `pcb_runs.heartbeat_at`
-- est écrit toutes les 30 s par le worker (migration 019, index compris), et
-- AUCUN code ne le lit — vérifié le 2026-09-05 sur tout le dépôt. Les
-- commentaires de `run-job.ts` et `run-repository.ts` affirment pourtant qu'un
-- run sans battement récent « est réconcilié en failed, ce qui libère aussi sa
-- réservation » : ce réconciliateur n'a jamais été écrit.
--
-- On se sert donc du battement pour ce qu'il prouve : que le run VIT. Chaque
-- battement repousse l'échéance de la retenue. La fenêtre devient glissante —
-- un run vivant garde son crédit engagé aussi longtemps qu'il travaille, un run
-- mort cesse d'être rafraîchi et sa retenue expire d'elle-même.
--
-- ⚠️ Rien ici ne remplace `expires_at` : c'est lui qui reste le filet, et c'est
-- voulu. On ne fait que le repousser tant qu'il y a une preuve de vie.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.extend_pipeline_reservation(
  p_reservation_id uuid,
  p_ttl_seconds    integer
)
RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_touched integer;
BEGIN
  -- Même garde que `reserve_pipeline_credits` : seul le porteur du rôle de
  -- service prolonge une retenue. Un client qui le pourrait s'accorderait un
  -- engagement de crédit sans fin.
  IF current_setting('request.jwt.claim.role', true) IS NOT NULL
     AND current_setting('request.jwt.claim.role', true) <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: extend_pipeline_reservation requires service role'
      USING ERRCODE = '42501';
  END IF;

  IF p_ttl_seconds IS NULL OR p_ttl_seconds < 1 OR p_ttl_seconds > 3600 THEN
    RAISE EXCEPTION 'invalid_ttl: expected 1..3600 seconds' USING ERRCODE = '22023';
  END IF;

  -- ⚠️ `released_at IS NULL` : une retenue déjà consommée par
  -- `finalize_pipeline_success` ne doit JAMAIS revivre. Un battement en retard
  -- ressusciterait sinon un engagement sur un run terminé et payé.
  --
  -- On ne filtre PAS sur `expires_at > now()` : un battement peut arriver juste
  -- après l'échéance, et refuser de prolonger là condamnerait un run vivant à
  -- laisser passer un second pipeline. Ressusciter une retenue non libérée est
  -- sans danger — elle appartient à un run qui prouve à l'instant qu'il vit.
  UPDATE public.credit_reservations
  SET expires_at = now() + make_interval(secs => p_ttl_seconds)
  WHERE id = p_reservation_id
    AND released_at IS NULL;

  GET DIAGNOSTICS v_touched = ROW_COUNT;
  RETURN v_touched > 0;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.extend_pipeline_reservation(uuid, integer)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.extend_pipeline_reservation(uuid, integer)
  TO service_role;

COMMENT ON FUNCTION public.extend_pipeline_reservation(uuid, integer) IS
  'Repousse l''échéance d''une retenue non libérée. Appelée à chaque battement '
  'de cœur du run : la fenêtre suit le travail réel au lieu d''être pariée '
  'd''avance. Voir 015_credit_reservations.sql et 019_pcb_runs.sql.';
