-- 016 — Fin d'abonnement : le plan redescend à `free` (PLAN.md §4.4).
--
-- Défaut corrigé : le webhook Lemon Squeezy traitait `order_created`,
-- `subscription_created` et `subscription_renewed`, mais AUCUN événement de fin
-- de vie. Un abonné qui résiliait gardait `plan = 'pro'` indéfiniment.
--
-- Portée réelle du défaut, pour ne pas le surestimer : aucun crédit n'était
-- perdu. Les crédits arrivent par `subscription_renewed`, qui cesse d'être émis
-- dès la fin de l'abonnement. Ce qui mentait, c'est le PLAN — affiché sur la
-- page billing, et surtout destiné à gouverner les droits (2/4/8 couches,
-- vue 3D, simulation) en Phase 5. Un droit adossé à une donnée fausse est un
-- droit accordé à tort.
--
-- Pourquoi une RPC dédiée plutôt que `credit_webhook_event` (013) : celle-ci
-- exige un montant strictement positif. Une fin d'abonnement ne crédite RIEN ;
-- lui passer 0 la ferait échouer, et lui passer un montant fictif polluerait
-- `credit_transactions` d'une ligne sans contrepartie.
--
-- Idempotence : même table de marqueurs que 013, donc un rejeu Lemon Squeezy
-- est absorbé. Le déclassement est idempotent par nature, mais le marqueur
-- garde la trace auditable de l'événement — c'est lui qui permet de répondre
-- « pourquoi ce compte est-il repassé free, et quand ».

CREATE OR REPLACE FUNCTION public.expire_subscription_plan(
  p_event_key text,
  p_event_name text,
  p_user_id uuid
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_inserted integer;
  v_updated integer;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: expire_subscription_plan requires service role'
      USING ERRCODE = '42501';
  END IF;

  IF p_event_key IS NULL OR btrim(p_event_key) = '' THEN
    RAISE EXCEPTION 'invalid_event_key' USING ERRCODE = '22023';
  END IF;

  -- Marqueur d'abord, dans la MÊME transaction que le déclassement : si le
  -- process meurt entre les deux, tout est annulé et le rejeu refait le travail.
  INSERT INTO public.processed_webhook_events (event_key, event_name)
  VALUES (p_event_key, p_event_name)
  ON CONFLICT (event_key) DO NOTHING;

  GET DIAGNOSTICS v_inserted = ROW_COUNT;
  IF v_inserted = 0 THEN
    RETURN false;  -- déjà traité
  END IF;

  UPDATE public.credits
  SET plan = 'free',
      updated_at = now()
  WHERE user_id = p_user_id;

  GET DIAGNOSTICS v_updated = ROW_COUNT;
  IF v_updated = 0 THEN
    -- Refus DÉFINITIF : aucun réessai ne fera apparaître cette ligne. Le
    -- SQLSTATE 22023 est celui que la route traduit en 422, pour que Lemon
    -- Squeezy cesse de retenter au lieu de boucler.
    RAISE EXCEPTION 'unknown_user' USING ERRCODE = '22023';
  END IF;

  RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.expire_subscription_plan(text, text, uuid)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.expire_subscription_plan(text, text, uuid)
  TO service_role;
