-- 013 — Le marquage d'idempotence et le crédit deviennent une seule transaction.
--
-- Défaut corrigé : le webhook Lemon Squeezy posait le marqueur d'événement
-- (`processed_webhook_events`) AVANT d'appeler `add_credits`. Entre les deux, le
-- process peut mourir — Vercel coupe une fonction serverless à son `maxDuration`,
-- un déploiement remplace l'instance, un pod redémarre. Le marqueur survit, le
-- crédit non : le réessai de Lemon Squeezy est alors classé « duplicate » et le
-- paiement encaissé n'est jamais crédité. Perte définitive, silencieuse.
--
-- Le rattrapage prévu — `releaseEvent`, qui supprime le marqueur en cas d'échec —
-- ne couvre que l'échec *retourné* par la RPC, pas la mort du process. Et il
-- ignorait lui-même l'erreur de son `DELETE` : un marqueur pouvait rester en
-- place sans que personne ne le sache.
--
-- `credit_webhook_event` fait les deux dans la même transaction PostgreSQL.
-- Si le crédit échoue, l'insertion du marqueur est annulée avec lui : le réessai
-- repart proprement. Si le process meurt en cours, rien n'est validé. Il n'y a
-- plus de fenêtre entre les deux écritures, donc plus rien à rattraper.
--
-- Renvoie `false` si l'événement était déjà traité (duplicata), `true` s'il vient
-- d'être crédité. Le plan d'abonnement est mis à jour dans la même transaction
-- quand `p_plan` est fourni.

CREATE OR REPLACE FUNCTION public.credit_webhook_event(
  p_event_key text,
  p_event_name text,
  p_user_id uuid,
  p_amount numeric,
  p_action text,
  p_plan text DEFAULT NULL
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_claimed boolean := false;
  v_rows integer;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: credit_webhook_event requires service role'
      USING ERRCODE = '42501';
  END IF;

  IF p_event_key IS NULL OR length(p_event_key) = 0
     OR p_event_name IS NULL OR length(p_event_name) = 0
     OR p_user_id IS NULL
     OR p_action IS NULL OR length(p_action) = 0 THEN
    RAISE EXCEPTION 'invalid_webhook_event' USING ERRCODE = '22023';
  END IF;

  -- Même validation de montant que `add_credits` (migration 010), appliquée avant
  -- de poser le marqueur : un montant invalide ne doit pas consommer la clé
  -- d'idempotence de l'événement.
  IF p_amount IS NULL OR p_amount < 0.01 OR p_amount <> round(p_amount, 2) THEN
    RAISE EXCEPTION 'invalid_amount' USING ERRCODE = '22023';
  END IF;

  INSERT INTO public.processed_webhook_events (event_key, event_name)
  VALUES (p_event_key, p_event_name)
  ON CONFLICT (event_key) DO NOTHING;

  GET DIAGNOSTICS v_rows = ROW_COUNT;
  v_claimed := v_rows = 1;

  IF NOT v_claimed THEN
    RETURN false;
  END IF;

  -- À partir d'ici, toute exception annule AUSSI l'insertion du marqueur : c'est
  -- précisément ce que `releaseEvent` tentait d'obtenir depuis l'application.
  IF p_plan IS NOT NULL THEN
    UPDATE public.credits
    SET plan = p_plan,
        updated_at = now()
    WHERE user_id = p_user_id;

    GET DIAGNOSTICS v_rows = ROW_COUNT;
    IF v_rows <> 1 THEN
      RAISE EXCEPTION 'unknown_user: no credits row for user' USING ERRCODE = '22023';
    END IF;
  END IF;

  PERFORM public.add_credits(p_user_id, p_amount, p_action);

  RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.credit_webhook_event(text, text, uuid, numeric, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.credit_webhook_event(text, text, uuid, numeric, text, text)
  TO service_role;
