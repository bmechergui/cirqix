-- ============================================================
-- Cirqix — Migration initiale
-- Extensions, tables, RLS, triggers
-- ============================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "vector";

-- ============================================================
-- Tables
-- ============================================================

-- Projets PCB
CREATE TABLE IF NOT EXISTS projects (
  id              uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id         uuid REFERENCES auth.users NOT NULL,
  name            text NOT NULL,
  description     text,
  status          text DEFAULT 'INITIAL'
    CHECK (status IN ('INITIAL','SCHEMA_DONE','PLACEMENT_DONE','ROUTING_DONE','DRC_CLEAN','PCB_LIVRÉ')),
  pcb_state       jsonb,
  iteration_count int DEFAULT 0,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

-- Crédits par utilisateur
CREATE TABLE IF NOT EXISTS credits (
  id         uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id    uuid REFERENCES auth.users UNIQUE NOT NULL,
  balance    numeric(10, 2) DEFAULT 5,
  plan       text DEFAULT 'free'
    CHECK (plan IN ('free','pro','pro_max','enterprise')),
  updated_at timestamptz DEFAULT now()
);

-- Historique des transactions de crédits
CREATE TABLE IF NOT EXISTS credit_transactions (
  id         uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id    uuid REFERENCES auth.users NOT NULL,
  project_id uuid REFERENCES projects,
  action     text NOT NULL,
  amount     numeric(10, 2) NOT NULL,
  created_at timestamptz DEFAULT now()
);

-- Footprints (librairie utilisateur + communauté)
CREATE TABLE IF NOT EXISTS footprints (
  id           uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  user_id      uuid REFERENCES auth.users,
  is_community boolean DEFAULT false,
  name         text NOT NULL,
  part_number  text,
  source       text CHECK (source IN ('kicad_official','snapmagic','octopart','ai_generated')),
  kicad_mod    text,
  embedding    vector(1536),
  validated    boolean DEFAULT false,
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

-- Waitlist landing page
CREATE TABLE IF NOT EXISTS waitlist (
  id         uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
  email      text UNIQUE NOT NULL,
  created_at timestamptz DEFAULT now()
);

-- ============================================================
-- Index
-- ============================================================

CREATE INDEX IF NOT EXISTS idx_projects_user_id ON projects(user_id);
CREATE INDEX IF NOT EXISTS idx_credit_transactions_user_id ON credit_transactions(user_id);
CREATE INDEX IF NOT EXISTS idx_footprints_user_id ON footprints(user_id);
CREATE INDEX IF NOT EXISTS idx_footprints_community ON footprints(is_community) WHERE is_community = true;
CREATE INDEX IF NOT EXISTS idx_footprints_embedding ON footprints USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- Row Level Security
-- ============================================================

ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
ALTER TABLE credits ENABLE ROW LEVEL SECURITY;
ALTER TABLE credit_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE footprints ENABLE ROW LEVEL SECURITY;

-- Projects : l'utilisateur voit uniquement ses projets
CREATE POLICY "projects_own" ON projects
  FOR ALL USING (auth.uid() = user_id);

-- Credits : l'utilisateur voit uniquement ses crédits
CREATE POLICY "credits_own" ON credits
  FOR ALL USING (auth.uid() = user_id);

-- Transactions : l'utilisateur voit uniquement les siennes
CREATE POLICY "transactions_own" ON credit_transactions
  FOR ALL USING (auth.uid() = user_id);

-- Footprints : les siennes + les communautaires
CREATE POLICY "footprints_own_or_community" ON footprints
  FOR SELECT USING (auth.uid() = user_id OR is_community = true);

CREATE POLICY "footprints_insert_own" ON footprints
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "footprints_update_own" ON footprints
  FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "footprints_delete_own" ON footprints
  FOR DELETE USING (auth.uid() = user_id);

-- ============================================================
-- Fonctions RPC
-- ============================================================

-- Déduction atomique de crédits (évite les race conditions)
CREATE OR REPLACE FUNCTION deduct_credits(
  p_user_id    uuid,
  p_amount     numeric,
  p_action     text,
  p_project_id uuid DEFAULT NULL
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
  v_balance numeric;
BEGIN
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

-- Rechargement de crédits (top-up ou renouvellement plan)
CREATE OR REPLACE FUNCTION add_credits(
  p_user_id uuid,
  p_amount  numeric,
  p_action  text
) RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  UPDATE credits
    SET balance    = balance + p_amount,
        updated_at = now()
    WHERE user_id  = p_user_id;

  INSERT INTO credit_transactions (user_id, action, amount)
    VALUES (p_user_id, p_action, p_amount);
END;
$$;

-- ============================================================
-- Trigger : initialiser les crédits à la création d'un user
-- ============================================================

CREATE OR REPLACE FUNCTION init_user_credits()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
BEGIN
  INSERT INTO credits (user_id, balance, plan)
    VALUES (NEW.id, 5, 'free')
    ON CONFLICT (user_id) DO NOTHING;
  RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS on_auth_user_created ON auth.users;
CREATE TRIGGER on_auth_user_created
  AFTER INSERT ON auth.users
  FOR EACH ROW EXECUTE FUNCTION init_user_credits();

-- ============================================================
-- Trigger : updated_at automatique
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE TRIGGER projects_updated_at
  BEFORE UPDATE ON projects
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER footprints_updated_at
  BEFORE UPDATE ON footprints
  FOR EACH ROW EXECUTE FUNCTION update_updated_at();
