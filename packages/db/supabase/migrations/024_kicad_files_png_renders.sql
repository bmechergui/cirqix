-- Migration 024 — le bucket kicad-files accepte les rendus PNG
--
-- Mesuré le 2026-09-13, premier run après la fusion de #173 : les deux
-- pré-rendus (top, iso) ont été rendus par KiCad puis REFUSÉS au dépôt —
-- « mime type image/png is not supported ». La liste blanche de la migration
-- 002 ne connaît que les fichiers KiCad. Les rendus vivent sous
-- `<user>/<projet>/renders/<clé>.png`, servis par GET /api/projects/[id]/render
-- après vérification du propriétaire ; les policies RLS de 002 s'appliquent
-- inchangées (le chemin commence toujours par l'id de l'utilisateur).
UPDATE storage.buckets
SET allowed_mime_types = (
  SELECT array_agg(DISTINCT t)
  FROM unnest(COALESCE(allowed_mime_types, ARRAY[]::text[]) || ARRAY['image/png']) AS t
)
WHERE id = 'kicad-files';
