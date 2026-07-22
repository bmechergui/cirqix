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
--   C. deduct_credits rejects authenticated callers
--   D. deduct_credits accepts the trusted server
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
  SET LOCAL ROLE authenticated;
  PERFORM set_config('request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
  BEGIN
    PERFORM add_credits('11111111-1111-1111-1111-111111111111', 9999, 'self-mint');
  EXCEPTION WHEN OTHERS THEN
    ok := true;  -- expected: blocked
  END;
  RESET ROLE;
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
  SET LOCAL ROLE authenticated;
  PERFORM set_config('request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
  BEGIN
    PERFORM deduct_credits('22222222-2222-2222-2222-222222222222', 5, 'theft');
  EXCEPTION WHEN OTHERS THEN
    ok := true;
  END;
  RESET ROLE;
  IF NOT ok THEN
    RAISE EXCEPTION 'FAIL C: deduct_credits allowed cross-user deduction';
  END IF;
  RAISE NOTICE 'PASS C — deduct_credits rejects cross-user caller';
END $$;

-- ---------- D. deduct_credits must ACCEPT the trusted server ----------
DO $$
DECLARE
  alice_after numeric;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
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

-- ---------- D2. trusted callers cannot submit a negative debit ----------
DO $$
DECLARE
  ok boolean := false;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  BEGIN
    PERFORM deduct_credits('11111111-1111-1111-1111-111111111111', -9999, 'mint');
  EXCEPTION WHEN OTHERS THEN
    ok := true;
  END;
  RESET ROLE;
  IF NOT ok THEN
    RAISE EXCEPTION 'FAIL D2: negative debit minted credits';
  END IF;
  RAISE NOTICE 'PASS D2 — negative debit is rejected';
END $$;

-- ---------- F. authenticated callers cannot forge balance or DRC status ----------
DO $$
DECLARE
  blocked_credit boolean := false;
  blocked_status boolean := false;
  blocked_insert boolean := false;
  blocked_intent boolean := false;
  project_id uuid := '33333333-3333-3333-3333-333333333333';
BEGIN
  INSERT INTO projects (id, user_id, name, status)
  VALUES (project_id, '11111111-1111-1111-1111-111111111111', 'RLS test', 'INITIAL')
  ON CONFLICT (id) DO UPDATE SET status = 'INITIAL';

  SET LOCAL ROLE authenticated;
  PERFORM set_config('request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}', true);
  BEGIN
    UPDATE credits SET balance = 9999
      WHERE user_id = '11111111-1111-1111-1111-111111111111';
  EXCEPTION WHEN OTHERS THEN
    blocked_credit := true;
  END;
  BEGIN
    UPDATE projects SET status = 'DRC_CLEAN' WHERE id = project_id;
  EXCEPTION WHEN OTHERS THEN
    blocked_status := true;
  END;
  BEGIN
    INSERT INTO projects (user_id, name, status, pcb_state)
    VALUES (
      '11111111-1111-1111-1111-111111111111',
      'Forged certification',
      'DRC_CLEAN',
      '{"drc_clean": true, "drc_validation": "kicad-cli"}'::jsonb
    );
  EXCEPTION WHEN OTHERS THEN
    blocked_insert := true;
  END;
  BEGIN
    INSERT INTO manufacturing_intents (reference, project_id, user_id, qty, confirmation)
    VALUES (
      'FORGED-INTENT', project_id,
      '11111111-1111-1111-1111-111111111111', 5, 'OUI JE CONFIRME'
    );
  EXCEPTION WHEN OTHERS THEN
    blocked_intent := true;
  END;
  RESET ROLE;

  IF NOT blocked_credit THEN
    RAISE EXCEPTION 'FAIL F: authenticated caller changed credit balance';
  END IF;
  IF NOT blocked_status THEN
    RAISE EXCEPTION 'FAIL F: authenticated caller forged DRC status';
  END IF;
  IF NOT blocked_insert THEN
    RAISE EXCEPTION 'FAIL F: authenticated caller inserted forged certification';
  END IF;
  IF NOT blocked_intent THEN
    RAISE EXCEPTION 'FAIL F: authenticated caller inserted a manufacturing intent';
  END IF;
  RAISE NOTICE 'PASS F â€” sensitive table fields require server authority';
END $$;

-- ---------- G. payment event IDs are idempotent ----------
DO $$
DECLARE
  first_apply boolean;
  second_apply boolean;
  alice_after numeric;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  first_apply := process_payment_event(
    'evt-rls-idempotency', 'topup',
    '11111111-1111-1111-1111-111111111111', 20, NULL, false);
  second_apply := process_payment_event(
    'evt-rls-idempotency', 'topup',
    '11111111-1111-1111-1111-111111111111', 20, NULL, false);
  SELECT balance INTO alice_after FROM credits
    WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF first_apply IS NOT TRUE OR second_apply IS NOT FALSE OR alice_after <> 71.5 THEN
    RAISE EXCEPTION 'FAIL G: payment event idempotency failed (first=%, second=%, balance=%)',
      first_apply, second_apply, alice_after;
  END IF;
  RAISE NOTICE 'PASS G â€” duplicate payment event did not duplicate credits';
END $$;

-- ---------- H. reservation holds credit before one idempotent final debit ----------
DO $$
DECLARE
  reservation_id uuid := '44444444-4444-4444-4444-444444444444';
  balance_after_reserve numeric;
  balance_after_complete numeric;
  first_complete boolean;
  second_complete boolean;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  PERFORM reserve_pipeline_credits(
    reservation_id,
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    8.5
  );
  SELECT balance INTO balance_after_reserve FROM credits
    WHERE user_id = '11111111-1111-1111-1111-111111111111';
  first_complete := complete_pipeline_credit_reservation(reservation_id);
  second_complete := complete_pipeline_credit_reservation(reservation_id);
  SELECT balance INTO balance_after_complete FROM credits
    WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF balance_after_reserve <> 71.5
     OR first_complete IS NOT TRUE
     OR second_complete IS NOT TRUE
     OR balance_after_complete <> 63 THEN
    RAISE EXCEPTION
      'FAIL H: reservation accounting failed (reserve=%, first=%, second=%, complete=%)',
      balance_after_reserve, first_complete, second_complete, balance_after_complete;
  END IF;
  RAISE NOTICE 'PASS H â€” reservation defers and deduplicates the debit';
END $$;

-- ---------- cleanup (service role) ----------
SELECT set_config('request.jwt.claims', '{"role":"service_role"}', true);
DELETE FROM waitlist WHERE email = 'joiner-e@test.local';
DELETE FROM credit_transactions
  WHERE user_id IN ('11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222');
DELETE FROM credits
  WHERE user_id IN ('11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222');
DELETE FROM payment_webhook_events WHERE event_id = 'evt-rls-idempotency';
DELETE FROM pipeline_credit_reservations WHERE id = '44444444-4444-4444-4444-444444444444';
DELETE FROM projects WHERE id = '33333333-3333-3333-3333-333333333333';
DELETE FROM auth.users
  WHERE id   IN ('11111111-1111-1111-1111-111111111111','22222222-2222-2222-2222-222222222222');

DO $$ BEGIN RAISE NOTICE 'All security invariants hold.'; END $$;
