-- Credits integrity hardening.
-- Migration 009 has already been applied on at least one remote environment;
-- this follow-up migration is therefore required for existing deployments.

CREATE OR REPLACE FUNCTION public.add_credits(
  p_user_id uuid,
  p_amount numeric,
  p_action text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: add_credits requires service role'
      USING ERRCODE = '42501';
  END IF;

  IF p_amount IS NULL OR p_amount < 0.01 OR p_amount <> round(p_amount, 2) THEN
    RAISE EXCEPTION 'invalid_amount: use a positive amount with at most 2 decimals'
      USING ERRCODE = '22023';
  END IF;

  IF p_action IS NULL OR btrim(p_action) = '' THEN
    RAISE EXCEPTION 'invalid_action: p_action is required'
      USING ERRCODE = '22023';
  END IF;

  UPDATE public.credits
  SET balance = balance + p_amount,
      updated_at = now()
  WHERE user_id = p_user_id;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'user_not_found';
  END IF;

  INSERT INTO public.credit_transactions (user_id, action, amount)
  VALUES (p_user_id, p_action, p_amount);
END;
$$;

CREATE OR REPLACE FUNCTION public.deduct_credits(
  p_user_id uuid,
  p_amount numeric,
  p_action text,
  p_project_id uuid DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
DECLARE
  v_balance numeric;
  v_role text := coalesce(auth.jwt() ->> 'role', '');
BEGIN
  IF v_role <> 'service_role'
     AND (auth.uid() IS NULL OR auth.uid() <> p_user_id) THEN
    RAISE EXCEPTION 'forbidden: caller must own these credits'
      USING ERRCODE = '42501';
  END IF;

  IF p_amount IS NULL OR p_amount < 0.01 OR p_amount <> round(p_amount, 2) THEN
    RAISE EXCEPTION 'invalid_amount: use a positive amount with at most 2 decimals'
      USING ERRCODE = '22023';
  END IF;

  IF p_action IS NULL OR btrim(p_action) = '' THEN
    RAISE EXCEPTION 'invalid_action: p_action is required'
      USING ERRCODE = '22023';
  END IF;

  IF v_role <> 'service_role'
     AND (p_amount <> 8.5
       OR p_action <> 'full_pcb_pipeline'
       OR p_project_id IS NULL) THEN
    RAISE EXCEPTION 'forbidden: unsupported client credit operation'
      USING ERRCODE = '42501';
  END IF;

  IF p_project_id IS NOT NULL AND NOT EXISTS (
    SELECT 1
    FROM public.projects
    WHERE id = p_project_id AND user_id = p_user_id
  ) THEN
    RAISE EXCEPTION 'invalid_project: project does not belong to user'
      USING ERRCODE = '22023';
  END IF;

  SELECT balance
  INTO v_balance
  FROM public.credits
  WHERE user_id = p_user_id
  FOR UPDATE;

  IF v_balance IS NULL THEN
    RAISE EXCEPTION 'user_not_found';
  END IF;

  IF v_balance < p_amount THEN
    RAISE EXCEPTION 'insufficient_credits';
  END IF;

  UPDATE public.credits
  SET balance = balance - p_amount,
      updated_at = now()
  WHERE user_id = p_user_id;

  INSERT INTO public.credit_transactions (user_id, project_id, action, amount)
  VALUES (p_user_id, p_project_id, p_action, -p_amount);
END;
$$;

CREATE OR REPLACE FUNCTION public.init_user_credits()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = ''
AS $$
BEGIN
  INSERT INTO public.credits (user_id, balance, plan)
  VALUES (NEW.id, 5, 'free')
  ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$;

REVOKE EXECUTE ON FUNCTION public.add_credits(uuid, numeric, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.add_credits(uuid, numeric, text)
  TO service_role;

REVOKE EXECUTE ON FUNCTION public.deduct_credits(uuid, numeric, text, uuid)
  FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.deduct_credits(uuid, numeric, text, uuid)
  TO authenticated, service_role;

REVOKE EXECUTE ON FUNCTION public.init_user_credits()
  FROM PUBLIC, anon, authenticated, service_role;

-- Authenticated clients can read their own rows through RLS. All writes go
-- through the guarded functions above.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
  ON TABLE public.credits, public.credit_transactions
  FROM PUBLIC, anon, authenticated;
GRANT SELECT ON TABLE public.credits, public.credit_transactions
  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE
  ON TABLE public.credits, public.credit_transactions
  TO service_role;

DROP POLICY IF EXISTS credits_own ON public.credits;
DROP POLICY IF EXISTS credits_select_own ON public.credits;
CREATE POLICY credits_select_own ON public.credits
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

DROP POLICY IF EXISTS transactions_own ON public.credit_transactions;
DROP POLICY IF EXISTS transactions_select_own ON public.credit_transactions;
CREATE POLICY transactions_select_own ON public.credit_transactions
  FOR SELECT TO authenticated
  USING ((SELECT auth.uid()) = user_id);

-- Enforce the invariant for every future insert/update, including trusted
-- service-role paths. NOT VALID avoids blocking deployment if legacy rows need
-- a separate cleanup before the constraint can be validated globally.
DO $$
BEGIN
  ALTER TABLE public.credits
    ADD CONSTRAINT credits_balance_nonnegative
    CHECK (balance IS NOT NULL AND balance >= 0) NOT VALID;
EXCEPTION WHEN duplicate_object THEN
  NULL;
END $$;
