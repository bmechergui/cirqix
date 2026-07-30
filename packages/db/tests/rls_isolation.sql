-- Credits/RLS security regression tests through migration 010.
-- Run against a disposable local Supabase database:
--   supabase db reset
--   psql "$LOCAL_POSTGRES_URL" -f packages/db/tests/rls_isolation.sql

\set ON_ERROR_STOP on

BEGIN;

INSERT INTO auth.users (id, email)
VALUES
  ('11111111-1111-1111-1111-111111111111', 'alice@test.local'),
  ('22222222-2222-2222-2222-222222222222', 'bob@test.local')
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.credits (user_id, balance, plan)
VALUES
  ('11111111-1111-1111-1111-111111111111', 50, 'free'),
  ('22222222-2222-2222-2222-222222222222', 50, 'free')
ON CONFLICT (user_id) DO UPDATE SET balance = 50, plan = 'free';

INSERT INTO public.projects (id, user_id, name)
VALUES (
  '33333333-3333-3333-3333-333333333333',
  '11111111-1111-1111-1111-111111111111',
  'Alice security test project'
)
ON CONFLICT (id) DO NOTHING;

-- A. An authenticated role cannot call add_credits.
DO $$
DECLARE
  blocked boolean := false;
BEGIN
  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;
  BEGIN
    PERFORM public.add_credits(
      '11111111-1111-1111-1111-111111111111', 9999, 'self-mint'
    );
  EXCEPTION WHEN insufficient_privilege THEN
    blocked := true;
  END;
  RESET ROLE;

  IF NOT blocked THEN
    RAISE EXCEPTION 'FAIL A: authenticated role executed add_credits';
  END IF;
  RAISE NOTICE 'PASS A - authenticated add_credits blocked';
END $$;

-- B. The service role can add a strictly positive amount.
DO $$
DECLARE
  alice_after numeric;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  PERFORM public.add_credits(
    '11111111-1111-1111-1111-111111111111', 10, 'topup'
  );
  RESET ROLE;

  SELECT balance INTO alice_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF alice_after <> 60 THEN
    RAISE EXCEPTION 'FAIL B: service-role credit balance=%', alice_after;
  END IF;
  RAISE NOTICE 'PASS B - service-role add_credits accepted';
END $$;

-- C. An authenticated owner cannot deduct another user's balance.
DO $$
DECLARE
  blocked boolean := false;
  bob_before numeric;
  bob_after numeric;
BEGIN
  SELECT balance INTO bob_before
  FROM public.credits
  WHERE user_id = '22222222-2222-2222-2222-222222222222';

  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;
  BEGIN
    PERFORM public.deduct_credits(
      '22222222-2222-2222-2222-222222222222', 5, 'theft'
    );
  EXCEPTION WHEN insufficient_privilege THEN
    blocked := true;
  END;
  RESET ROLE;

  SELECT balance INTO bob_after
  FROM public.credits
  WHERE user_id = '22222222-2222-2222-2222-222222222222';

  IF NOT blocked OR bob_after <> bob_before THEN
    RAISE EXCEPTION
      'FAIL C: cross-user blocked=%, before=%, after=%',
      blocked, bob_before, bob_after;
  END IF;
  RAISE NOTICE 'PASS C - cross-user deduction blocked';
END $$;

-- D. The authenticated owner can deduct a positive amount.
DO $$
DECLARE
  alice_after numeric;
BEGIN
  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;
  PERFORM public.deduct_credits(
    '11111111-1111-1111-1111-111111111111',
    8.5,
    'full_pcb_pipeline',
    '33333333-3333-3333-3333-333333333333'
  );
  RESET ROLE;

  SELECT balance INTO alice_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF alice_after <> 51.5 THEN
    RAISE EXCEPTION 'FAIL D: owner deduction balance=%', alice_after;
  END IF;
  RAISE NOTICE 'PASS D - owner deduction accepted';
END $$;

-- E. Negative and zero amounts are rejected without changing the balance.
DO $$
DECLARE
  blocked_negative boolean := false;
  blocked_zero boolean := false;
  blocked_tiny boolean := false;
  balance_before numeric;
  balance_after numeric;
BEGIN
  SELECT balance INTO balance_before
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;
  BEGIN
    PERFORM public.deduct_credits(
      '11111111-1111-1111-1111-111111111111', -1000, 'negative-mint'
    );
  EXCEPTION WHEN invalid_parameter_value THEN
    blocked_negative := true;
  END;
  RESET ROLE;

  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;
  BEGIN
    PERFORM public.deduct_credits(
      '11111111-1111-1111-1111-111111111111',
      0.001,
      'full_pcb_pipeline',
      '33333333-3333-3333-3333-333333333333'
    );
  EXCEPTION WHEN invalid_parameter_value THEN
    blocked_tiny := true;
  END;
  RESET ROLE;

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  BEGIN
    PERFORM public.add_credits(
      '11111111-1111-1111-1111-111111111111', 0, 'zero-topup'
    );
  EXCEPTION WHEN invalid_parameter_value THEN
    blocked_zero := true;
  END;
  RESET ROLE;

  SELECT balance INTO balance_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  IF NOT blocked_negative
     OR NOT blocked_zero
     OR NOT blocked_tiny
     OR balance_after <> balance_before THEN
    RAISE EXCEPTION
      'FAIL E: amount validation negative=%, zero=%, tiny=%, before=%, after=%',
      blocked_negative, blocked_zero, blocked_tiny, balance_before, balance_after;
  END IF;
  RAISE NOTICE 'PASS E - non-positive amounts blocked';
END $$;

-- F. Authenticated users can read their rows but cannot mutate credit tables.
DO $$
DECLARE
  visible_balance numeric;
  update_blocked boolean := false;
  insert_blocked boolean := false;
BEGIN
  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;

  SELECT balance INTO visible_balance
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  BEGIN
    UPDATE public.credits
    SET balance = 999999
    WHERE user_id = '11111111-1111-1111-1111-111111111111';
  EXCEPTION WHEN insufficient_privilege THEN
    update_blocked := true;
  END;

  BEGIN
    INSERT INTO public.credit_transactions (user_id, action, amount)
    VALUES ('11111111-1111-1111-1111-111111111111', 'forged', 999999);
  EXCEPTION WHEN insufficient_privilege THEN
    insert_blocked := true;
  END;
  RESET ROLE;

  IF visible_balance IS NULL OR NOT update_blocked OR NOT insert_blocked THEN
    RAISE EXCEPTION
      'FAIL F: read=%, update_blocked=%, insert_blocked=%',
      visible_balance, update_blocked, insert_blocked;
  END IF;
  RAISE NOTICE 'PASS F - credits are read-only to authenticated users';
END $$;

-- G. Anon can join the waitlist but cannot read it.
DO $$
DECLARE
  inserted boolean := false;
  select_blocked boolean := false;
  leaked integer;
BEGIN
  SET LOCAL ROLE anon;
  INSERT INTO public.waitlist (email) VALUES ('joiner-g@test.local');
  inserted := true;
  BEGIN
    SELECT count(*) INTO leaked FROM public.waitlist;
  EXCEPTION WHEN insufficient_privilege THEN
    select_blocked := true;
  END;
  RESET ROLE;

  IF NOT inserted OR (NOT select_blocked AND leaked <> 0) THEN
    RAISE EXCEPTION
      'FAIL G: waitlist inserted=%, select_blocked=%, leaked=%',
      inserted, select_blocked, leaked;
  END IF;
  RAISE NOTICE 'PASS G - waitlist insert allowed and select isolated';
END $$;

ROLLBACK;

DO $$
BEGIN
  RAISE NOTICE 'All security invariants hold.';
END $$;
