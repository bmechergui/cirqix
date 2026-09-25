---
name: cirqix-footprint
description: This skill should be used when the user asks to "chercher un footprint", "générer un footprint", "implémenter l'agent footprint", "cascade footprint", "ajouter un composant KiCad" or mentions footprint, kicad_mod, SnapMagic, Octopart, pad, package, pgvector embeddings.
version: 0.1.0
---

# Cirqix — Agent Footprint

## Cascade (`packages/agents/src/engines/footprint-service.ts::findFootprint`, arrêt à la première réussite)

1. Bibliothèque KiCad standard (locale, instantanée)
1.5. Cache communautaire pgvector (`footprint-cache.ts`)
2. SnapMagic (si `SNAPMAGIC_API_KEY`)
3. LCSC / EasyEDA (HTTP public)
4. Génération du `.kicad_mod` par Haiku 4.5 (3 crédits)

Repli final : empreinte générique (celle du package fourni, sinon `Resistor_SMD:R_0402`).

## Génération .kicad_mod

L'étape 4 est `generateWithAI` (`footprint-service.ts`) : Haiku 4.5 écrit le `.kicad_mod`. Le dépôt n'a pas de générateur paramétrique.

## Supabase — table footprints

DDL et index ivfflat dans `001_initial.sql` ; contrainte `source` étendue à `lcsc` par `005_footprint_search_rpc.sql` ; RLS durcie par `014_rls_hardening.sql` : un compte authentifié n'insère que des empreintes privées et non validées. Seule la RPC `upsert_community_footprint`, réservée au service role (`011_project_integrity.sql`), alimente le cache communautaire.

## Cache pgvector

Embeddings : API embeddings OpenAI, 1536 dimensions (`packages/agents/src/engines/footprint-cache.ts`). RPC : `search_footprint_by_part_number`, `search_footprint_by_embedding`, `upsert_community_footprint` (migrations 005 et 011). Sources admises : kicad_official, snapmagic, octopart, lcsc, ai_generated.
