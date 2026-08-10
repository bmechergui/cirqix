-- ============================================================
-- Migration 014 - Footprint cache and waitlist RLS hardening
-- ============================================================
--
-- Numérotée 012 à l'origine ; renumérotée en 014 après la fusion de 012
-- (simulator_no_billing) et 013 (webhook_credit_atomique) sur main, qui ont
-- occupé ces deux numéros entre-temps.
--
-- Défaut fermé ici, vérifié actif en production le 2026-08-10 :
--
--   footprints_own_or_community (SELECT) : auth.uid() = user_id OR is_community
--   footprints_insert_own (INSERT)       : WITH CHECK (auth.uid() = user_id)
--   footprints_update_own (UPDATE)       : USING owner, AUCUN WITH CHECK
--
-- Rien n'empêchait donc un utilisateur authentifié de poser `is_community =
-- true, validated = true` sur sa propre ligne — à l'insertion, ou après coup par
-- UPDATE, l'absence de WITH CHECK ne revérifiant pas la ligne résultante. Or la
-- policy de lecture sert toute ligne communautaire à TOUS les comptes.
--
-- Conséquence : injection arbitraire dans le cache de footprints partagé que
-- consomme l'agent Footprint. Un mauvais footprint donne une carte dont les
-- composants ne rentrent pas — infabricable, et payée.

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
