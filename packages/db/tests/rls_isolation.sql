-- Credits/RLS security regression tests through migration 016.
-- Run against a disposable local Supabase database:
--   supabase db reset
--   psql "$LOCAL_POSTGRES_URL" -f packages/db/tests/rls_isolation.sql

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

-- Second projet d'Alice : sépare le refus « solde épuisé » (test Q) du refus
-- « ce projet a déjà un run » (test T). Réserver deux fois sur le MÊME projet
-- déclencherait la seconde garde et ferait passer Q sans rien prouver du solde.
INSERT INTO public.projects (id, user_id, name)
VALUES (
  '55555555-5555-5555-5555-555555555555',
  '11111111-1111-1111-1111-111111111111',
  'Alice second project'
)
ON CONFLICT (id) DO NOTHING;

INSERT INTO public.footprints (
  id, user_id, is_community, name, part_number, source, validated
)
VALUES (
  '44444444-4444-4444-4444-444444444444',
  '11111111-1111-1111-1111-111111111111',
  false,
  'Alice private security test footprint',
  'ALICE-PRIVATE-012',
  'ai_generated',
  false
)
ON CONFLICT (id) DO UPDATE SET
  is_community = false,
  validated = false;

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

-- D. Authenticated owners cannot create standalone pipeline debits.
DO $$
DECLARE
  blocked boolean := false;
  alice_before numeric;
  alice_after numeric;
BEGIN
  SELECT balance INTO alice_before
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
      '11111111-1111-1111-1111-111111111111',
      8.5,
      'full_pcb_pipeline',
      '33333333-3333-3333-3333-333333333333'
    );
  EXCEPTION WHEN insufficient_privilege THEN
    blocked := true;
  END;
  RESET ROLE;

  SELECT balance INTO alice_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF NOT blocked OR alice_after <> alice_before THEN
    RAISE EXCEPTION
      'FAIL D: standalone deduction blocked=%, before=%, after=%',
      blocked, alice_before, alice_after;
  END IF;
  RAISE NOTICE 'PASS D - standalone authenticated deduction blocked';
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

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  BEGIN
    PERFORM public.deduct_credits(
      '11111111-1111-1111-1111-111111111111', -1000, 'negative-mint'
    );
  EXCEPTION WHEN invalid_parameter_value THEN
    blocked_negative := true;
  END;
  RESET ROLE;

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
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

-- H. Authenticated users may edit metadata but not pipeline-owned columns.
DO $$
DECLARE
  protected_update_blocked boolean := false;
  protected_insert_blocked boolean := false;
  saved_description text;
BEGIN
  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;

  UPDATE public.projects
  SET description = 'metadata update allowed'
  WHERE id = '33333333-3333-3333-3333-333333333333';

  SELECT description INTO saved_description
  FROM public.projects
  WHERE id = '33333333-3333-3333-3333-333333333333';

  BEGIN
    UPDATE public.projects
    SET status = 'DRC_CLEAN', pcb_state = '{"status":"DRC_CLEAN"}'::jsonb
    WHERE id = '33333333-3333-3333-3333-333333333333';
  EXCEPTION WHEN insufficient_privilege THEN
    protected_update_blocked := true;
  END;

  BEGIN
    INSERT INTO public.projects (user_id, name, status)
    VALUES (
      '11111111-1111-1111-1111-111111111111',
      'forged finalized project',
      'DRC_CLEAN'
    );
  EXCEPTION WHEN insufficient_privilege THEN
    protected_insert_blocked := true;
  END;
  RESET ROLE;

  IF saved_description <> 'metadata update allowed'
     OR NOT protected_update_blocked OR NOT protected_insert_blocked THEN
    RAISE EXCEPTION
      'FAIL H: metadata=%, protected_update=%, protected_insert=%',
      saved_description, protected_update_blocked, protected_insert_blocked;
  END IF;
  RAISE NOTICE 'PASS H - project pipeline columns are server-managed';
END $$;

-- I. Authenticated callers cannot execute pipeline finalization.
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
    PERFORM public.finalize_pipeline_success(
      '11111111-1111-1111-1111-111111111111',
      '33333333-3333-3333-3333-333333333333',
      1,
      '{"projectId":"33333333-3333-3333-3333-333333333333","status":"DRC_CLEAN","iteration":1}'::jsonb,
      'orchestrator'
    );
  EXCEPTION WHEN insufficient_privilege THEN
    blocked := true;
  END;
  RESET ROLE;

  IF NOT blocked THEN
    RAISE EXCEPTION 'FAIL I: authenticated role executed finalize_pipeline_success';
  END IF;
  RAISE NOTICE 'PASS I - authenticated finalization blocked';
END $$;

-- J. Service role finalizes atomically and a replay cannot double-charge.
DO $$
DECLARE
  balance_before numeric;
  balance_after numeric;
  balance_replay numeric;
  first_result boolean;
  replay_result boolean;
  saved_status text;
  saved_iteration integer;
  saved_mode text;
BEGIN
  SELECT balance INTO balance_before
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  UPDATE public.projects
  SET status = 'ROUTING_DONE',
      pcb_state = '{"projectId":"33333333-3333-3333-3333-333333333333","status":"ROUTING_DONE","iteration":1}'::jsonb,
      iteration_count = 0,
      agent_mode = 'orchestrator'
  WHERE id = '33333333-3333-3333-3333-333333333333';

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  SELECT public.finalize_pipeline_success(
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    1,
    '{"projectId":"33333333-3333-3333-3333-333333333333","status":"DRC_CLEAN","iteration":1}'::jsonb,
    'orchestrator'
  ) INTO first_result;
  RESET ROLE;

  SELECT balance INTO balance_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  SELECT status, iteration_count, agent_mode
  INTO saved_status, saved_iteration, saved_mode
  FROM public.projects
  WHERE id = '33333333-3333-3333-3333-333333333333';

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  SELECT public.finalize_pipeline_success(
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    1,
    '{"projectId":"33333333-3333-3333-3333-333333333333","status":"DRC_CLEAN","iteration":1}'::jsonb,
    'orchestrator'
  ) INTO replay_result;
  RESET ROLE;

  SELECT balance INTO balance_replay
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  IF first_result IS DISTINCT FROM true
     OR replay_result IS DISTINCT FROM false
     OR balance_after <> balance_before - 8.5
     OR balance_replay <> balance_after
     OR saved_status <> 'DRC_CLEAN'
     OR saved_iteration <> 1
     OR saved_mode <> 'orchestrator' THEN
    RAISE EXCEPTION
      'FAIL J: first=%, replay=%, balances=%/%/%, project=%/%/%',
      first_result, replay_result, balance_before, balance_after, balance_replay,
      saved_status, saved_iteration, saved_mode;
  END IF;
  RAISE NOTICE 'PASS J - atomic finalization and replay protection hold';
END $$;

-- K. Invalid iteration jumps are rejected without another debit.
DO $$
DECLARE
  blocked boolean := false;
  balance_before numeric;
  balance_after numeric;
BEGIN
  SELECT balance INTO balance_before
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  BEGIN
    PERFORM public.finalize_pipeline_success(
      '11111111-1111-1111-1111-111111111111',
      '33333333-3333-3333-3333-333333333333',
      3,
      '{"projectId":"33333333-3333-3333-3333-333333333333","status":"DRC_CLEAN","iteration":3}'::jsonb,
      'orchestrator'
    );
  EXCEPTION WHEN invalid_parameter_value THEN
    blocked := true;
  END;
  RESET ROLE;

  SELECT balance INTO balance_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  IF NOT blocked OR balance_after <> balance_before THEN
    RAISE EXCEPTION 'FAIL K: blocked=%, balance=%/%', blocked, balance_before, balance_after;
  END IF;
  RAISE NOTICE 'PASS K - stale iteration rejected';
END $$;

-- L. Only service role may populate the shared footprint cache.
DO $$
DECLARE
  blocked boolean := false;
  footprint_id uuid;
BEGIN
  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;
  BEGIN
    PERFORM public.upsert_community_footprint(
      'forged', 'FORGED-011', 'lcsc', '(module forged)', NULL
    );
  EXCEPTION WHEN insufficient_privilege THEN
    blocked := true;
  END;
  RESET ROLE;

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  SELECT public.upsert_community_footprint(
    'service test', 'SERVICE-011', 'lcsc', '(module service)', NULL
  ) INTO footprint_id;
  RESET ROLE;

  IF NOT blocked OR footprint_id IS NULL THEN
    RAISE EXCEPTION 'FAIL L: authenticated_blocked=%, service_id=%', blocked, footprint_id;
  END IF;
  RAISE NOTICE 'PASS L - community footprint upsert is service-only';
END $$;

-- M. Authenticated users cannot insert directly into the community cache.
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
    INSERT INTO public.footprints (
      user_id, is_community, name, part_number, source, validated
    ) VALUES (
      '11111111-1111-1111-1111-111111111111',
      true,
      'forged community footprint',
      'FORGED-DIRECT-012',
      'ai_generated',
      false
    );
  EXCEPTION WHEN insufficient_privilege THEN
    blocked := true;
  END;
  RESET ROLE;

  IF NOT blocked THEN
    RAISE EXCEPTION 'FAIL M: authenticated role inserted a community footprint';
  END IF;
  RAISE NOTICE 'PASS M - direct community footprint insert blocked';
END $$;

-- N. Authenticated owners cannot promote their private footprint.
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
    UPDATE public.footprints
    SET is_community = true
    WHERE id = '44444444-4444-4444-4444-444444444444';
  EXCEPTION WHEN insufficient_privilege THEN
    blocked := true;
  END;
  RESET ROLE;

  IF NOT blocked THEN
    RAISE EXCEPTION 'FAIL N: authenticated owner promoted a private footprint';
  END IF;
  RAISE NOTICE 'PASS N - private footprint promotion blocked';
END $$;

-- O. Authenticated users cannot read waitlist emails.
DO $$
DECLARE
  select_blocked boolean := false;
  leaked integer;
BEGIN
  INSERT INTO public.waitlist (email)
  VALUES ('authenticated-reader-o@test.local')
  ON CONFLICT (email) DO NOTHING;

  PERFORM set_config(
    'request.jwt.claims',
    '{"sub":"11111111-1111-1111-1111-111111111111","role":"authenticated"}',
    true
  );
  SET LOCAL ROLE authenticated;
  BEGIN
    SELECT count(*) INTO leaked FROM public.waitlist;
  EXCEPTION WHEN insufficient_privilege THEN
    select_blocked := true;
  END;
  RESET ROLE;

  IF NOT select_blocked AND leaked <> 0 THEN
    RAISE EXCEPTION 'FAIL O: authenticated waitlist select leaked % rows', leaked;
  END IF;
  RAISE NOTICE 'PASS O - authenticated waitlist select isolated';
END $$;

-- P. Les réservations de crédits sont hors de portée du client (migration 015).
DO $$
DECLARE
  reserve_blocked boolean := false;
  release_blocked boolean := false;
  insert_blocked boolean := false;
  available_blocked boolean := false;
BEGIN
  PERFORM set_config('request.jwt.claims',
    '{"role":"authenticated","sub":"11111111-1111-1111-1111-111111111111"}', true);
  SET LOCAL ROLE authenticated;

  BEGIN
    PERFORM public.reserve_pipeline_credits(
      '11111111-1111-1111-1111-111111111111',
      '33333333-3333-3333-3333-333333333333',
      8.5, 360);
  EXCEPTION WHEN OTHERS THEN reserve_blocked := true;
  END;

  BEGIN
    PERFORM public.release_pipeline_reservation(gen_random_uuid());
  EXCEPTION WHEN OTHERS THEN release_blocked := true;
  END;

  BEGIN
    PERFORM public.available_credits('22222222-2222-2222-2222-222222222222');
  EXCEPTION WHEN OTHERS THEN available_blocked := true;
  END;

  -- Une écriture directe contournerait les RPC : pouvoir LIBÉRER une retenue à
  -- la main rouvrirait exactement la fenêtre que 015 ferme.
  BEGIN
    INSERT INTO public.credit_reservations (user_id, project_id, amount, expires_at)
    VALUES ('11111111-1111-1111-1111-111111111111',
            '33333333-3333-3333-3333-333333333333',
            8.5, now() + interval '1 hour');
  EXCEPTION WHEN OTHERS THEN insert_blocked := true;
  END;

  RESET ROLE;

  IF NOT (reserve_blocked AND release_blocked AND available_blocked AND insert_blocked) THEN
    RAISE EXCEPTION
      'FAIL P: reserve=%, release=%, available=%, insert=%',
      reserve_blocked, release_blocked, available_blocked, insert_blocked;
  END IF;
  RAISE NOTICE 'PASS P - credit reservations are service-role only';
END $$;

-- Q. Une retenue engage le solde : un second pipeline ne peut plus le réengager.
DO $$
DECLARE
  first_id uuid;
  second_blocked boolean := false;
  available_after numeric;
  balance_after numeric;
BEGIN
  -- Solde ramené à 10 : de quoi financer UN pipeline (8,5), pas deux.
  UPDATE public.credits SET balance = 10
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;

  SELECT public.reserve_pipeline_credits(
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    8.5, 360) INTO first_id;

  -- Le défaut d'origine : ce second appel lisait le même solde et passait.
  -- Sur un AUTRE projet, pour que seul le solde puisse le refuser — la garde
  -- « un run par projet » (test T) ne doit pas répondre à sa place.
  BEGIN
    PERFORM public.reserve_pipeline_credits(
      '11111111-1111-1111-1111-111111111111',
      '55555555-5555-5555-5555-555555555555',
      8.5, 360);
  EXCEPTION WHEN OTHERS THEN second_blocked := true;
  END;

  SELECT public.available_credits('11111111-1111-1111-1111-111111111111')
  INTO available_after;
  RESET ROLE;

  SELECT balance INTO balance_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  -- La retenue n'est PAS un débit : le solde n'a pas bougé, seul le disponible.
  IF first_id IS NULL
     OR NOT second_blocked
     OR available_after <> 1.5
     OR balance_after <> 10 THEN
    RAISE EXCEPTION
      'FAIL Q: first=%, second_blocked=%, available=%, balance=%',
      first_id, second_blocked, available_after, balance_after;
  END IF;
  RAISE NOTICE 'PASS Q - an active hold blocks a second concurrent pipeline';
END $$;

-- R. La finalisation consomme la retenue dans la transaction du débit.
DO $$
DECLARE
  balance_before numeric;
  balance_after numeric;
  available_after numeric;
  still_held numeric;
  finalized boolean;
BEGIN
  UPDATE public.credits SET balance = 50
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  UPDATE public.projects
  SET status = 'ROUTING_DONE', iteration_count = 0, agent_mode = 'orchestrator'
  WHERE id = '33333333-3333-3333-3333-333333333333';
  -- Q a laissé une retenue active sur ce couple (utilisateur, projet).

  SELECT balance INTO balance_before
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  SELECT public.finalize_pipeline_success(
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    1,
    '{"projectId":"33333333-3333-3333-3333-333333333333","status":"DRC_CLEAN","iteration":1}'::jsonb,
    'orchestrator'
  ) INTO finalized;
  SELECT public.available_credits('11111111-1111-1111-1111-111111111111')
  INTO available_after;
  RESET ROLE;

  SELECT balance INTO balance_after
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  SELECT coalesce(sum(amount), 0) INTO still_held
  FROM public.credit_reservations
  WHERE user_id = '11111111-1111-1111-1111-111111111111'
    AND released_at IS NULL
    AND expires_at > now();

  -- Le crédit ne doit être compté QU'UNE fois : si la retenue survivait au
  -- débit, `available` vaudrait 8,5 de moins que le solde jusqu'à expiration.
  IF finalized IS DISTINCT FROM true
     OR balance_after <> balance_before - 8.5
     OR still_held <> 0
     OR available_after <> balance_after THEN
    RAISE EXCEPTION
      'FAIL R: finalized=%, balance=%/%, held=%, available=%',
      finalized, balance_before, balance_after, still_held, available_after;
  END IF;
  RAISE NOTICE 'PASS R - finalization consumes the hold without double counting';
END $$;

-- S. Une retenue expirée cesse de bloquer — sinon un crash gèlerait le solde.
DO $$
DECLARE
  reservation_id uuid;
  available_with_expired numeric;
  balance_now numeric;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  SELECT public.reserve_pipeline_credits(
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    8.5, 360) INTO reservation_id;
  RESET ROLE;

  -- Le processus qui devait libérer cette retenue est mort.
  UPDATE public.credit_reservations
  SET expires_at = now() - interval '1 second'
  WHERE id = reservation_id;

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  SELECT public.available_credits('11111111-1111-1111-1111-111111111111')
  INTO available_with_expired;
  RESET ROLE;

  SELECT balance INTO balance_now
  FROM public.credits
  WHERE user_id = '11111111-1111-1111-1111-111111111111';

  IF available_with_expired <> balance_now THEN
    RAISE EXCEPTION 'FAIL S: available=% but balance=%',
      available_with_expired, balance_now;
  END IF;
  RAISE NOTICE 'PASS S - an expired hold stops blocking the balance';
END $$;

-- T. Un seul run par projet — sinon la finalisation du premier libère la
--    retenue du second, encore en cours, et la course revient.
DO $$
DECLARE
  first_id uuid;
  second_blocked boolean := false;
  refusal text := '';
  active_holds integer;
BEGIN
  UPDATE public.credits SET balance = 100
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  -- Solde largement suffisant : seul le doublon peut refuser ici.
  UPDATE public.credit_reservations
  SET released_at = now()
  WHERE user_id = '11111111-1111-1111-1111-111111111111'
    AND released_at IS NULL;

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;

  SELECT public.reserve_pipeline_credits(
    '11111111-1111-1111-1111-111111111111',
    '33333333-3333-3333-3333-333333333333',
    8.5, 360) INTO first_id;

  BEGIN
    PERFORM public.reserve_pipeline_credits(
      '11111111-1111-1111-1111-111111111111',
      '33333333-3333-3333-3333-333333333333',
      8.5, 360);
  EXCEPTION WHEN OTHERS THEN
    second_blocked := true;
    refusal := SQLERRM;
  END;
  RESET ROLE;

  SELECT count(*) INTO active_holds
  FROM public.credit_reservations
  WHERE project_id = '33333333-3333-3333-3333-333333333333'
    AND released_at IS NULL
    AND expires_at > now();

  -- Le motif compte autant que le refus : un rejet pour solde insuffisant
  -- serait un faux positif, et masquerait l'absence de cette garde.
  IF first_id IS NULL
     OR NOT second_blocked
     OR refusal NOT LIKE '%pipeline_already_running%'
     OR active_holds <> 1 THEN
    RAISE EXCEPTION
      'FAIL T: first=%, blocked=%, refusal=%, active=%',
      first_id, second_blocked, refusal, active_holds;
  END IF;
  RAISE NOTICE 'PASS T - a project cannot hold two concurrent pipelines';
END $$;

-- U. La fin d'abonnement est hors de portée du client (migration 016).
DO $$
DECLARE blocked boolean := false;
BEGIN
  PERFORM set_config('request.jwt.claims',
    '{"role":"authenticated","sub":"11111111-1111-1111-1111-111111111111"}', true);
  SET LOCAL ROLE authenticated;
  BEGIN
    PERFORM public.expire_subscription_plan(
      'rls-u', 'subscription_expired', '11111111-1111-1111-1111-111111111111');
  EXCEPTION WHEN OTHERS THEN blocked := true;
  END;
  RESET ROLE;

  IF NOT blocked THEN
    RAISE EXCEPTION 'FAIL U: un role authentifie a pu declasser un abonnement';
  END IF;
  RAISE NOTICE 'PASS U - expire_subscription_plan is service-role only';
END $$;

-- V. Le déclassement ne confisque pas les crédits déjà achetés, et le rejeu
--    d'un webhook Lemon Squeezy est absorbé.
DO $$
DECLARE
  first_call boolean;
  replay boolean;
  plan_after text;
  balance_before numeric;
  balance_after numeric;
BEGIN
  UPDATE public.credits SET plan = 'pro'
  WHERE user_id = '11111111-1111-1111-1111-111111111111';
  SELECT balance INTO balance_before
  FROM public.credits WHERE user_id = '11111111-1111-1111-1111-111111111111';

  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  SELECT public.expire_subscription_plan(
    'rls-v', 'subscription_expired', '11111111-1111-1111-1111-111111111111') INTO first_call;
  SELECT public.expire_subscription_plan(
    'rls-v', 'subscription_expired', '11111111-1111-1111-1111-111111111111') INTO replay;
  RESET ROLE;

  SELECT plan, balance INTO plan_after, balance_after
  FROM public.credits WHERE user_id = '11111111-1111-1111-1111-111111111111';

  -- Un abonnement qui s'achève retire un DROIT, pas un solde : les crédits
  -- achetés restent acquis.
  IF first_call IS DISTINCT FROM true
     OR replay IS DISTINCT FROM false
     OR plan_after <> 'free'
     OR balance_after <> balance_before THEN
    RAISE EXCEPTION 'FAIL V: first=%, replay=%, plan=%, balance=%/%',
      first_call, replay, plan_after, balance_before, balance_after;
  END IF;
  RAISE NOTICE 'PASS V - expiry downgrades once and never seizes credits';
END $$;

-- W. Utilisateur inconnu → refus DÉFINITIF (22023), et le marqueur n'est pas
--    posé : sinon le rejeu serait classé « duplicate » et l'événement perdu.
DO $$
DECLARE
  code text := '';
  marker integer;
BEGIN
  PERFORM set_config('request.jwt.claims', '{"role":"service_role"}', true);
  SET LOCAL ROLE service_role;
  BEGIN
    PERFORM public.expire_subscription_plan(
      'rls-w', 'subscription_expired', '99999999-9999-9999-9999-999999999999');
  EXCEPTION WHEN OTHERS THEN code := SQLSTATE;
  END;
  RESET ROLE;

  SELECT count(*) INTO marker
  FROM public.processed_webhook_events WHERE event_key = 'rls-w';

  IF code <> '22023' OR marker <> 0 THEN
    RAISE EXCEPTION 'FAIL W: sqlstate=%, marqueur=%', code, marker;
  END IF;
  RAISE NOTICE 'PASS W - unknown user is a permanent refusal, marker rolled back';
END $$;

ROLLBACK;

DO $$
BEGIN
  RAISE NOTICE 'All security invariants hold.';
END $$;
