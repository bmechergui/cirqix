-- ============================================================
-- packages/db/tests/rls_isolation.sql
-- Regression tests for migration 006 (security hotfix).
-- ------------------------------------------------------------
-- How to run (local Supabase stack):
--   supabase db reset
--   psql "$LOCAL_POSTGRES_URL" -f packages/db/tests/rls_isolation.sql
--   # exit code 0 = all invariants hold
-- ------------------------------------------------------------
-- Invariants:
--   A. add_credits rejects authenticated callers (no self-minting)
--   B. add_credits accepts the service role (webhook path)
--   C. deduct_credits rejects cross-user callers
--   D. deduct_credits accepts the owner
--   E. waitlist: anon can INSERT, cannot SELECT
-- ============================================================

\set ON_ERROR_STOP on

-- Two fixed test users (auth.users rows so FKs resolve).
INSERT INTO auth.users (id, email)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'alice@test.local'),
  ('22222222-2222-2222-2222-222222222222', 'bob@test.local')
ON CONFLICT (id) DO NOTHING;

-- Seed credit rows directly (we are superuser; RLS bypassed by owner).
INSERT INTO credits (user_id, balance, plan) VALUES
  ('11111111-1111-1111-1111-111111111111', 50, 'free'),
  ('22222222-2222-2222-2222-222222222222', 50, 'free')
ON CONFLICT (user_id) DO UPDATE SET balance = 50, plan = 'free';

-- ---------- helper: run a block "as" a simulated JWT caller ----------
-- auth.uid() = current_setting('request.jwt.claims')::jsonb ->> 'sub'
-- auth.jwt() = current_setting('request.jwt.claims')::json
-- We toggle these per scenario then restore them.

-- ---------- A. add_credits must REJECT an authenticated user ----------
DO $$
DECLARE
  ok boolean := false;
BEGIN
  PERFORM set_config('request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
  BEGIN
    PERFORM add_credits('11111111-1111-1111-1111-111111111111', 9999, 'self-mint');
  EXCEPTION WHEN OTHERS THEN
    ok := true;  -- expected: blocked
  END;
  IF NOT ok THEN
    RAISE EXCEPTION 'FAIL A: add_credits allowed an authenticated self-mint';
  END IF;
  RAISE NOTICE 'PASS A — add_credits rejects authenticated caller';
END $$;

-- ---------- B. add_credits must ACCEPT the service role ----------
DO $$
DECLARE
  alice_after numeric;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  PERFORM add_credits('11111111-1111-1111-1111-111111111111', 10, 'topup');
  SELECT balance INTO alice_after FROM credits
    WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF alice_after <> 60 THEN
    RAISE EXCEPTION 'FAIL B: service-role add_credits did not credit (balance=%)', alice_after;
  END IF;
  RAISE NOTICE 'PASS B — add_credits accepts service role';
END $$;

-- ---------- C. deduct_credits must REJECT a cross-user caller ----------
DO $$
DECLARE
  ok boolean := false;
BEGIN
  -- Alice tries to deduct Bob's credits.
  PERFORM set_config('request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
  BEGIN
    PERFORM deduct_credits('22222222-2222-2222-2222-222222222222', 5, 'theft');
  EXCEPTION WHEN OTHERS THEN
    ok := true;
  END;
  IF NOT ok THEN
    RAISE EXCEPTION 'FAIL C: deduct_credits allowed cross-user deduction';
  END IF;
  RAISE NOTICE 'PASS C — deduct_credits rejects cross-user caller';
END $$;

-- ---------- D. deduct_credits must ACCEPT the owner ----------
DO $$
DECLARE
  alice_after numeric;
BEGIN
  PERFORM set_config('request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
  PERFORM deduct_credits('11111111-1111-1111-1111-111111111111', 8.5, 'pipeline');
  SELECT balance INTO alice_after FROM credits
    WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF alice_after <> 51.5 THEN
    RAISE EXCEPTION 'FAIL D: owner deduction wrong (balance=%)', alice_after;
  END IF;
  RAISE NOTICE 'PASS D — deduct_credits accepts owner';
END $$;

-- ---------- E. waitlist: anon INSERT ok, anon SELECT denied ----------
-- NOTE: set_config('request.jwt.claims', ...) alone does NOT change the
-- session role, so a superuser test runner would bypass RLS entirely
-- (false PASS on INSERT, false FAIL on SELECT). SET LOCAL ROLE anon makes
-- the statements genuinely subject to the waitlist policies.
DO $$
DECLARE
  ok_insert boolean := false;
  ok_select_blocked boolean := false;
  leaked int;
BEGIN
  SET LOCAL ROLE anon;

  BEGIN
    INSERT INTO waitlist (email) VALUES ('joiner-e@test.local');
    ok_insert := true;
  EXCEPTION WHEN OTHERS THEN
    ok_insert := false;
  END;

  BEGIN
    SELECT count(*) INTO leaked FROM waitlist;
    ok_select_blocked := (leaked = 0);  -- no SELECT policy → RLS returns 0 rows
  EXCEPTION WHEN OTHERS THEN
    ok_select_blocked := true;  -- privilege/RLS denial also acceptable
  END;

  RESET ROLE;  -- back to superuser for the cleanup below

  IF NOT ok_insert THEN
    RAISE EXCEPTION 'FAIL E: anon could not join waitlist';
  END IF;
  IF NOT ok_select_blocked THEN
    RAISE EXCEPTION 'FAIL E: anon leaked % waitlist emails', leaked;
  END IF;
  RAISE NOTICE 'PASS E — waitlist anon INSERT ok, SELECT blocked';
END $$;

-- ---------- cleanup (service role) ----------
PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
DELETE FROM waitlist WHERE email = 'joiner-e@test.local';
DELETE FROM credit_transactions
  WHERE user_id IN ('11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222');
DELETE FROM credits
  WHERE user_id IN ('11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222');
DELETE FROM auth.users
  WHERE id   IN ('11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222');

RAISE NOTICE 'All security invariants hold.';
