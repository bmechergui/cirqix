-- ============================================================
-- Migration 012 - Footprint cache and waitlist RLS hardening
-- ============================================================

-- Authenticated users may only create private, unvalidated footprints.
DROP POLICY IF EXISTS "footprints_insert_own" ON public.footprints;
CREATE POLICY "footprints_insert_own" ON public.footprints
  FOR INSERT
  TO authenticated
  WITH CHECK (
    (SELECT auth.uid()) = user_id
    AND is_community IS FALSE
    AND validated IS FALSE
  );

-- Owners may edit their footprints, but cannot promote or validate them.
DROP POLICY IF EXISTS "footprints_update_own" ON public.footprints;
CREATE POLICY "footprints_update_own" ON public.footprints
  FOR UPDATE
  TO authenticated
  USING ((SELECT auth.uid()) = user_id)
  WITH CHECK (
    (SELECT auth.uid()) = user_id
    AND is_community IS FALSE
    AND validated IS FALSE
  );

-- Public waitlist sign-up is insert-only. The service role bypasses RLS.
ALTER TABLE IF EXISTS public.waitlist ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "waitlist_insert" ON public.waitlist;
CREATE POLICY "waitlist_insert" ON public.waitlist
  FOR INSERT
  TO anon
  WITH CHECK (true);

GRANT INSERT ON TABLE public.waitlist TO anon;
REVOKE SELECT, UPDATE, DELETE ON TABLE public.waitlist
  FROM anon, authenticated;
