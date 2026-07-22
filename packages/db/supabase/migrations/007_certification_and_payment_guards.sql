-- Certification and payment integrity guards.
-- Clients may manage project metadata, but cannot set manufacturing status,
-- PCB evidence, credit balances, or payment events directly.

-- ---------- Project and credit table privileges ----------
DROP POLICY IF EXISTS projects_own ON projects;
CREATE POLICY projects_select_own ON projects
  FOR SELECT TO authenticated USING (auth.uid() = user_id);
CREATE POLICY projects_insert_own ON projects
  FOR INSERT TO authenticated WITH CHECK (auth.uid() = user_id);
CREATE POLICY projects_update_own ON projects
  FOR UPDATE TO authenticated
  USING (auth.uid() = user_id)
  WITH CHECK (auth.uid() = user_id);
CREATE POLICY projects_delete_own ON projects
  FOR DELETE TO authenticated USING (auth.uid() = user_id);

-- Keep ordinary project editing available, while server-side pipeline code is
-- the sole writer of certification and generated-board fields.
REVOKE UPDATE ON projects FROM PUBLIC, anon, authenticated;
GRANT UPDATE (name, description, updated_at) ON projects TO authenticated;
REVOKE INSERT ON projects FROM PUBLIC, anon, authenticated;
GRANT INSERT (user_id, name, description) ON projects TO authenticated;

DROP POLICY IF EXISTS credits_own ON credits;
CREATE POLICY credits_select_own ON credits
  FOR SELECT TO authenticated USING (auth.uid() = user_id);
REVOKE INSERT, UPDATE, DELETE ON credits FROM PUBLIC, anon, authenticated;

DROP POLICY IF EXISTS transactions_own ON credit_transactions;
CREATE POLICY transactions_select_own ON credit_transactions
  FOR SELECT TO authenticated USING (auth.uid() = user_id);
REVOKE INSERT, UPDATE, DELETE ON credit_transactions FROM PUBLIC, anon, authenticated;

-- ---------- Idempotent payment processing ----------
CREATE TABLE IF NOT EXISTS payment_webhook_events (
  event_id text PRIMARY KEY,
  provider text NOT NULL DEFAULT 'lemon_squeezy',
  event_name text NOT NULL,
  user_id uuid NOT NULL REFERENCES auth.users,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE payment_webhook_events ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON payment_webhook_events FROM PUBLIC, anon, authenticated;

CREATE TABLE IF NOT EXISTS lemon_subscriptions (
  subscription_id text PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users,
  product_id text NOT NULL,
  plan text NOT NULL,
  credits numeric NOT NULL CHECK (credits > 0),
  updated_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE lemon_subscriptions ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON lemon_subscriptions FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION register_lemon_subscription(
  p_subscription_id text,
  p_user_id uuid,
  p_product_id text,
  p_plan text,
  p_credits numeric
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: register_lemon_subscription requires service role';
  END IF;
  IF coalesce(length(trim(p_subscription_id)), 0) = 0
     OR coalesce(length(trim(p_product_id)), 0) = 0
     OR coalesce(length(trim(p_plan)), 0) = 0
     OR p_credits <= 0 THEN
    RAISE EXCEPTION 'invalid subscription record';
  END IF;

  INSERT INTO lemon_subscriptions (subscription_id, user_id, product_id, plan, credits)
  VALUES (p_subscription_id, p_user_id, p_product_id, p_plan, p_credits)
  ON CONFLICT (subscription_id) DO UPDATE
    SET user_id = EXCLUDED.user_id,
        product_id = EXCLUDED.product_id,
        plan = EXCLUDED.plan,
        credits = EXCLUDED.credits,
        updated_at = now();
END;
$$;

REVOKE EXECUTE ON FUNCTION register_lemon_subscription(text, uuid, text, text, numeric) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION register_lemon_subscription(text, uuid, text, text, numeric) TO service_role;

-- ---------- Manufacturing intent, not supplier submission ----------
CREATE TABLE IF NOT EXISTS manufacturing_intents (
  id uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  reference text NOT NULL UNIQUE,
  project_id uuid NOT NULL REFERENCES projects(id),
  user_id uuid NOT NULL REFERENCES auth.users,
  qty integer NOT NULL CHECK (qty > 0),
  supplier_target text NOT NULL DEFAULT 'JLCPCB',
  confirmation text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now()
);

ALTER TABLE manufacturing_intents ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON manufacturing_intents FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION record_manufacturing_intent(
  p_reference text,
  p_project_id uuid,
  p_user_id uuid,
  p_qty integer,
  p_confirmation text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: record_manufacturing_intent requires service role';
  END IF;
  IF coalesce(length(trim(p_reference)), 0) = 0
     OR p_qty IS NULL OR p_qty <= 0
     OR p_confirmation <> 'OUI JE CONFIRME' THEN
    RAISE EXCEPTION 'invalid manufacturing intent';
  END IF;

  INSERT INTO manufacturing_intents (reference, project_id, user_id, qty, confirmation)
  VALUES (p_reference, p_project_id, p_user_id, p_qty, p_confirmation);
END;
$$;

REVOKE EXECUTE ON FUNCTION record_manufacturing_intent(text, uuid, uuid, integer, text) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION record_manufacturing_intent(text, uuid, uuid, integer, text) TO service_role;

-- ---------- Durable, non-debited pipeline credit reservations ----------
CREATE TABLE IF NOT EXISTS pipeline_credit_reservations (
  id uuid PRIMARY KEY,
  user_id uuid NOT NULL REFERENCES auth.users,
  project_id uuid NOT NULL REFERENCES projects(id),
  amount numeric NOT NULL CHECK (amount > 0),
  status text NOT NULL CHECK (status IN ('reserved', 'completed', 'released')),
  created_at timestamptz NOT NULL DEFAULT now(),
  expires_at timestamptz NOT NULL,
  completed_at timestamptz,
  released_at timestamptz
);

CREATE INDEX IF NOT EXISTS pipeline_credit_reservations_active_user_idx
  ON pipeline_credit_reservations (user_id, expires_at)
  WHERE status = 'reserved';

ALTER TABLE pipeline_credit_reservations ENABLE ROW LEVEL SECURITY;
REVOKE ALL ON pipeline_credit_reservations FROM PUBLIC, anon, authenticated;

CREATE OR REPLACE FUNCTION reserve_pipeline_credits(
  p_reservation_id uuid,
  p_user_id uuid,
  p_project_id uuid,
  p_amount numeric
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_balance numeric;
  v_reserved numeric;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: reserve_pipeline_credits requires service role';
  END IF;
  IF p_reservation_id IS NULL OR p_amount IS NULL OR p_amount <= 0 THEN
    RAISE EXCEPTION 'invalid pipeline credit reservation';
  END IF;

  -- The credit-row lock serializes concurrent reservations for one user.
  SELECT balance INTO v_balance FROM credits WHERE user_id = p_user_id FOR UPDATE;
  IF v_balance IS NULL THEN
    RAISE EXCEPTION 'user_not_found';
  END IF;

  UPDATE pipeline_credit_reservations
    SET status = 'released', released_at = now()
    WHERE user_id = p_user_id
      AND status = 'reserved'
      AND expires_at <= now();

  SELECT coalesce(sum(amount), 0) INTO v_reserved
    FROM pipeline_credit_reservations
    WHERE user_id = p_user_id
      AND status = 'reserved'
      AND expires_at > now();
  IF v_balance - v_reserved < p_amount THEN
    RAISE EXCEPTION 'insufficient_credits';
  END IF;

  INSERT INTO pipeline_credit_reservations
    (id, user_id, project_id, amount, status, expires_at)
  VALUES
    (p_reservation_id, p_user_id, p_project_id, p_amount, 'reserved', now() + interval '15 minutes')
  ON CONFLICT (id) DO NOTHING;
END;
$$;

CREATE OR REPLACE FUNCTION complete_pipeline_credit_reservation(
  p_reservation_id uuid
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_reservation pipeline_credit_reservations%ROWTYPE;
  v_balance numeric;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: complete_pipeline_credit_reservation requires service role';
  END IF;

  SELECT * INTO v_reservation
    FROM pipeline_credit_reservations
    WHERE id = p_reservation_id
    FOR UPDATE;
  IF NOT FOUND THEN
    RAISE EXCEPTION 'pipeline_credit_reservation_not_found';
  END IF;
  IF v_reservation.status = 'completed' THEN
    RETURN true;
  END IF;
  IF v_reservation.status <> 'reserved' THEN
    RETURN false;
  END IF;
  IF v_reservation.expires_at <= now() THEN
    UPDATE pipeline_credit_reservations
      SET status = 'released', released_at = now()
      WHERE id = p_reservation_id;
    RETURN false;
  END IF;

  SELECT balance INTO v_balance FROM credits
    WHERE user_id = v_reservation.user_id
    FOR UPDATE;
  IF v_balance IS NULL THEN
    RAISE EXCEPTION 'user_not_found';
  END IF;
  IF v_balance < v_reservation.amount THEN
    RAISE EXCEPTION 'insufficient_credits';
  END IF;

  UPDATE credits
    SET balance = balance - v_reservation.amount,
        updated_at = now()
    WHERE user_id = v_reservation.user_id;
  INSERT INTO credit_transactions (user_id, project_id, action, amount)
    VALUES (v_reservation.user_id, v_reservation.project_id, 'full_pcb_pipeline', -v_reservation.amount);
  UPDATE pipeline_credit_reservations
    SET status = 'completed', completed_at = now()
    WHERE id = p_reservation_id;
  RETURN true;
END;
$$;

CREATE OR REPLACE FUNCTION release_pipeline_credit_reservation(
  p_reservation_id uuid
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_released boolean;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: release_pipeline_credit_reservation requires service role';
  END IF;

  UPDATE pipeline_credit_reservations
    SET status = 'released', released_at = now()
    WHERE id = p_reservation_id AND status = 'reserved'
    RETURNING true INTO v_released;
  RETURN coalesce(v_released, false);
END;
$$;

REVOKE EXECUTE ON FUNCTION reserve_pipeline_credits(uuid, uuid, uuid, numeric) FROM PUBLIC, authenticated;
REVOKE EXECUTE ON FUNCTION complete_pipeline_credit_reservation(uuid) FROM PUBLIC, authenticated;
REVOKE EXECUTE ON FUNCTION release_pipeline_credit_reservation(uuid) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION reserve_pipeline_credits(uuid, uuid, uuid, numeric) TO service_role;
GRANT EXECUTE ON FUNCTION complete_pipeline_credit_reservation(uuid) TO service_role;
GRANT EXECUTE ON FUNCTION release_pipeline_credit_reservation(uuid) TO service_role;

-- The web route now calls this RPC with the service role after user ownership
-- has been checked. Remove the user-callable surface and reject malformed
-- amounts defensively inside the function as well.
CREATE OR REPLACE FUNCTION deduct_credits(
  p_user_id uuid,
  p_amount numeric,
  p_action text,
  p_project_id uuid DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_balance numeric;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: deduct_credits requires service role';
  END IF;
  IF p_amount IS NULL OR p_amount <= 0 THEN
    RAISE EXCEPTION 'invalid credit amount';
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
    SET balance = balance - p_amount,
        updated_at = now()
    WHERE user_id = p_user_id;
  INSERT INTO credit_transactions (user_id, project_id, action, amount)
    VALUES (p_user_id, p_project_id, p_action, -p_amount);
END;
$$;

REVOKE EXECUTE ON FUNCTION deduct_credits(uuid, numeric, text, uuid) FROM PUBLIC, authenticated;
GRANT EXECUTE ON FUNCTION deduct_credits(uuid, numeric, text, uuid) TO service_role;

CREATE OR REPLACE FUNCTION process_payment_event(
  p_event_id text,
  p_event_name text,
  p_user_id uuid,
  p_amount numeric,
  p_plan text DEFAULT NULL,
  p_replace_balance boolean DEFAULT false
) RETURNS boolean
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_inserted text;
BEGIN
  IF coalesce(auth.jwt() ->> 'role', '') <> 'service_role' THEN
    RAISE EXCEPTION 'forbidden: process_payment_event requires service role';
  END IF;
  IF coalesce(length(trim(p_event_id)), 0) = 0 OR p_amount <= 0 THEN
    RAISE EXCEPTION 'invalid payment event';
  END IF;
  IF p_replace_balance AND p_plan IS NULL THEN
    RAISE EXCEPTION 'plan required when replacing balance';
  END IF;

  INSERT INTO payment_webhook_events (event_id, event_name, user_id)
  VALUES (p_event_id, p_event_name, p_user_id)
  ON CONFLICT (event_id) DO NOTHING
  RETURNING event_id INTO v_inserted;

  IF v_inserted IS NULL THEN
    RETURN false;
  END IF;

  IF p_replace_balance THEN
    UPDATE credits
      SET balance = p_amount,
          plan = p_plan,
          updated_at = now()
      WHERE user_id = p_user_id;
  ELSE
    UPDATE credits
      SET balance = balance + p_amount,
          updated_at = now()
      WHERE user_id = p_user_id;
  END IF;

  IF NOT FOUND THEN
    RAISE EXCEPTION 'user_not_found';
  END IF;

  INSERT INTO credit_transactions (user_id, action, amount)
  VALUES (p_user_id, p_event_name, p_amount);

  RETURN true;
END;
$$;

REVOKE EXECUTE ON FUNCTION process_payment_event(text, text, uuid, numeric, text, boolean) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION process_payment_event(text, text, uuid, numeric, text, boolean) TO service_role;
