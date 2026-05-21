-- ============================================================
-- Migration 005 — Footprint pgvector search RPCs
-- ============================================================

-- 1. Add 'lcsc' to the source check constraint
ALTER TABLE footprints DROP CONSTRAINT IF EXISTS footprints_source_check;
ALTER TABLE footprints ADD CONSTRAINT footprints_source_check
  CHECK (source IN ('kicad_official', 'snapmagic', 'octopart', 'lcsc', 'ai_generated'));

-- 2. Fast exact-match index on part_number for community rows
CREATE INDEX IF NOT EXISTS idx_footprints_community_part_number
  ON footprints (part_number)
  WHERE is_community = true AND part_number IS NOT NULL;

-- 3. Unique index so ON CONFLICT works in upsert_community_footprint
CREATE UNIQUE INDEX IF NOT EXISTS idx_footprints_community_part_unique
  ON footprints (part_number)
  WHERE is_community = true AND part_number IS NOT NULL;

-- 4. RPC: exact/ILIKE part number lookup in the community cache
CREATE OR REPLACE FUNCTION search_footprint_by_part_number(
  p_part_number text
) RETURNS TABLE (
  id          uuid,
  name        text,
  part_number text,
  source      text,
  kicad_mod   text
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT id, name, part_number, source, kicad_mod
  FROM footprints
  WHERE (is_community = true OR user_id IS NULL)
    AND part_number ILIKE p_part_number
  ORDER BY validated DESC, created_at DESC
  LIMIT 1;
$$;

-- 5. RPC: pgvector cosine similarity search
CREATE OR REPLACE FUNCTION search_footprint_by_embedding(
  p_embedding vector(1536),
  p_threshold float DEFAULT 0.80
) RETURNS TABLE (
  id          uuid,
  name        text,
  part_number text,
  source      text,
  kicad_mod   text,
  similarity  float
)
LANGUAGE sql
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    id,
    name,
    part_number,
    source,
    kicad_mod,
    1 - (embedding <-> p_embedding) AS similarity
  FROM footprints
  WHERE (is_community = true OR user_id IS NULL)
    AND embedding IS NOT NULL
    AND 1 - (embedding <-> p_embedding) > p_threshold
  ORDER BY embedding <-> p_embedding
  LIMIT 3;
$$;

-- 6. RPC: upsert a resolved footprint into the community cache
CREATE OR REPLACE FUNCTION upsert_community_footprint(
  p_name        text,
  p_part_number text,
  p_source      text,
  p_kicad_mod   text         DEFAULT NULL,
  p_embedding   vector(1536) DEFAULT NULL
) RETURNS uuid
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
  v_id uuid;
BEGIN
  INSERT INTO footprints (name, part_number, source, kicad_mod, embedding, is_community, validated)
  VALUES (p_name, p_part_number, p_source, p_kicad_mod, p_embedding, true, true)
  ON CONFLICT (part_number) WHERE is_community = true AND part_number IS NOT NULL
  DO UPDATE SET
    embedding  = COALESCE(EXCLUDED.embedding, footprints.embedding),
    updated_at = now()
  RETURNING id INTO v_id;

  RETURN v_id;
END;
$$;
