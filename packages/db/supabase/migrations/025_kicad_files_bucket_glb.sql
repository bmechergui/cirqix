-- Migration 025 — le bucket kicad-files accepte les modèles 3D GLB
--
-- Mesuré le 2026-09-14, premier affichage de la 3D interactive : le modèle
-- exporté par KiCad (`kicad-cli pcb export glb`, ~850 ko) est servi, mais
-- REFUSÉ au dépôt en cache — « mime type model/gltf-binary is not supported ».
-- Même cause que la migration 024 pour les PNG : la liste blanche de 002 ne
-- connaît que les fichiers KiCad. Sans ce dépôt, chaque ouverture de la vue
-- 3D ré-exporte le modèle (2 à 3 s) au lieu de le lire du stockage.
-- Les modèles vivent sous `<user>/<projet>/renders/<clé>.glb`, servis par
-- GET /api/projects/[id]/model après vérification du propriétaire ; les
-- policies RLS de 002 s'appliquent inchangées.
UPDATE storage.buckets
SET allowed_mime_types = (
  SELECT array_agg(DISTINCT t)
  FROM unnest(COALESCE(allowed_mime_types, ARRAY[]::text[]) || ARRAY['model/gltf-binary']) AS t
)
WHERE id = 'kicad-files';
