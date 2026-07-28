-- ============================================================
-- Migration 009 — Credits RPC lockdown
-- ------------------------------------------------------------
-- Constat (2026-07-28, advisors Supabase + inspection pg_proc) : la base
-- distante exécute encore les versions 001 de add_credits / deduct_credits
-- — SECURITY DEFINER, SANS garde d'authentification, et EXECUTE accordé
-- explicitement à anon + authenticated (defaut privileges Supabase).
-- La clé anon est publique (bundle frontend) : n'importe qui pouvait
-- appeler /rest/v1/rpc/add_credits et se créditer arbitrairement, ou
-- deduct_credits sur le compte d'un autre utilisateur.
--
-- Cette migration :
--   1. Ré-applique les corps sécurisés de la migration 006 (jamais
--      appliquée sur le distant — les versions distantes n'ont aucune
--      garde, vérifié via pg_get_functiondef).
--   2. Remplace le REVOKE FROM PUBLIC de 006 (insuffisant : les grants
--      anon/authenticated sont EXPLICITES, pas hérités de PUBLIC) par des
--      REVOKE nommés + GRANT ciblés.
--   3. Retire EXECUTE sur init_user_credits (fonction de trigger : le
--      trigger s'exécute comme definer, aucun GRANT nécessaire).
--
-- Idempotent : CREATE OR REPLACE + REVOKE/GRANT réapplicables sans effet
-- de bord. Les corps ci-dessous sont copiés verbatim de 006.
-- ============================================================

-- ---------- 1. add_credits : réservé au backend de confiance ----------
-- Appelée uniquement par le webhook Lemon Squeezy (createAdminClient =
-- service_role). Tout autre caller est rejeté.
CREATE OR REPLACE FUNCTION add_credits(
  p_user_id uuid,
  p_amount  numeric,
  p_action  text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: add_credits requires service role';
  END IF;

  UPDATE credits
    SET balance    = balance + p_amount,
        updated_at = now()
    WHERE user_id  = p_user_id;

  INSERT INTO credit_transactions (user_id, action, amount)
    VALUES (p_user_id, p_action, p_amount);
END;
$$;

-- ---------- 2. deduct_credits : propriétaire OU service_role ----------
-- Callers légitimes : l'orchestrator bridge (JWT utilisateur,
-- p_user_id = self — apps/web/src/app/api/agent/route.ts) et tout chemin
-- serveur (service_role). Jamais de débit sur le compte d'un tiers.
CREATE OR REPLACE FUNCTION deduct_credits(
  p_user_id    uuid,
  p_amount     numeric,
  p_action     text,
  p_project_id uuid DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_balance numeric;
  v_role    text := coalesce(auth.jwt() ->> 'role', '');
BEGIN
  IF v_role <> 'service_role'
     AND (auth.uid() IS NULL OR auth.uid() <> p_user_id) THEN
    RAISE EXCEPTION 'forbidden: caller must own these credits';
  END IF;

  SELECT balance INTO v_balance
    FROM credits
    WHERE user_id = p_user_id
    FOR UPDATE;

  IF v_balance IS NULL THEN
    RAISE EXCEPTION 'user_not_found';
  END IF;

  IF v_balance < p_amount THEN
    RAISE EXCEPTION 'insufficient_credits';
  END IF;

  UPDATE credits
    SET balance    = balance - p_amount,
        updated_at = now()
    WHERE user_id  = p_user_id;

  INSERT INTO credit_transactions (user_id, project_id, action, amount)
    VALUES (p_user_id, p_project_id, p_action, -p_amount);
END;
$$;

-- ---------- 3. Privilèges EXECUTE (grants explicites, pas PUBLIC) ----------
-- add_credits    : service_role uniquement (chemin webhook).
-- deduct_credits : authenticated (bridge, p_user_id = self) + service_role.
-- init_user_credits : personne — fonction de trigger (auth.users), le
--   trigger s'exécute comme definer sans grant EXECUTE.
REVOKE EXECUTE ON FUNCTION add_credits(uuid, numeric, text) FROM PUBLIC, anon, authenticated;
GRANT  EXECUTE ON FUNCTION add_credits(uuid, numeric, text) TO service_role;

REVOKE EXECUTE ON FUNCTION deduct_credits(uuid, numeric, text, uuid) FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION deduct_credits(uuid, numeric, text, uuid) TO authenticated, service_role;

REVOKE EXECUTE ON FUNCTION init_user_credits() FROM PUBLIC, anon, authenticated, service_role;
