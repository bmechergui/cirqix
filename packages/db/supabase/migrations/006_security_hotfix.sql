-- ============================================================
-- Migration 006 — Security hotfix
-- 1. add_credits     : service_role only (block user self-minting)
-- 2. deduct_credits  : caller must own the credits OR be service_role
-- 3. waitlist        : enable RLS (was world-readable) + anon INSERT only
-- 4. SET search_path = public on the rewritten SECURITY DEFINER functions
-- ------------------------------------------------------------
-- BEFORE THIS MIGRATION (001_initial.sql):
--   * add_credits / deduct_credits were SECURITY DEFINER with NO auth
--     check → any authenticated user could call add_credits(self, 99999)
--     to mint unlimited credits, or deduct_credits(other_user, ...) to
--     drain someone else's balance.
--   * waitlist was created but left OUT of the RLS enable block (only
--     projects/credits/credit_transactions/footprints had RLS) → the
--     anon key could SELECT every collected email.
-- These are authenticated-finance + PII issues, fixed below.
-- ============================================================

-- ---------- 1. add_credits : reserved to the trusted backend ----------
-- Called only by the Lemon Squeezy webhook (createAdminClient = service
-- role). Authenticated/anon callers must be rejected so a user cannot
-- grant credits to themselves or anyone else.
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

-- ---------- 2. deduct_credits : own credits OR service_role ----------
-- Legitimate callers: the orchestrator bridge (user-JWT, p_user_id = self)
-- and any future server path (service role). A user must NEVER be able to
-- target another user's id.
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

-- ---------- 3. waitlist : enable RLS, allow JOIN only ----------
-- The landing form needs anon INSERT. No SELECT/UPDATE/DELETE policy is
-- created, so under RLS only the service role (which bypasses RLS) can
-- read the collected emails.
ALTER TABLE waitlist ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS waitlist_insert ON waitlist;
CREATE POLICY waitlist_insert ON waitlist
  FOR INSERT TO anon, authenticated WITH CHECK (true);

-- ---------- 4. EXECUTE privileges (defense in depth) ----------
-- The in-body guards already prevent abuse, but 001 never restricted
-- EXECUTE (defaults to PUBLIC). Tighten at the GRANT layer so anon/auth
-- cannot even spam the RPCs (CPU) before the guard raises.
--   * add_credits    : service_role only (webhook path)
--   * deduct_credits : authenticated (bridge owner path) + service_role
REVOKE EXECUTE ON FUNCTION add_credits(uuid, numeric, text) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION add_credits(uuid, numeric, text) TO service_role;

REVOKE EXECUTE ON FUNCTION deduct_credits(uuid, numeric, text, uuid) FROM PUBLIC;
GRANT  EXECUTE ON FUNCTION deduct_credits(uuid, numeric, text, uuid) TO authenticated, service_role;
