-- Échafaudage minimal d'une base Supabase, pour rejouer les migrations et le
-- test d'isolation RLS sur un PostgreSQL nu en CI.
--
-- Les migrations et `rls_isolation.sql` supposent un environnement Supabase :
-- trois rôles, un schéma `auth` avec `users`, `uid()` et `jwt()`, et les
-- privilèges par défaut que Supabase accorde à `anon` / `authenticated`. Sans
-- cet échafaudage, le test échouerait sur l'absence de ces objets — pour la
-- mauvaise raison.
--
-- Ce fichier ne s'applique JAMAIS à une base réelle : Supabase fournit déjà tout
-- ce qui suit.

-- ---------------------------------------------------------------------------
-- Rôles
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
  END IF;
END $$;

GRANT anon, authenticated, service_role TO CURRENT_USER;
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Schéma auth
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS auth;
GRANT USAGE ON SCHEMA auth TO anon, authenticated, service_role;

CREATE TABLE IF NOT EXISTS auth.users (
  id    uuid PRIMARY KEY,
  email text UNIQUE
);

-- Mêmes signatures que Supabase : lecture des claims JWT posés par
-- `set_config('request.jwt.claims', …)`, exactement ce que fait
-- `rls_isolation.sql` pour se faire passer pour un utilisateur donné.
CREATE OR REPLACE FUNCTION auth.jwt() RETURNS jsonb
LANGUAGE sql STABLE AS $$
  SELECT coalesce(
    nullif(current_setting('request.jwt.claims', true), ''),
    '{}'
  )::jsonb;
$$;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
LANGUAGE sql STABLE AS $$
  SELECT nullif(auth.jwt() ->> 'sub', '')::uuid;
$$;

GRANT EXECUTE ON FUNCTION auth.jwt(), auth.uid()
  TO anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Schéma storage
-- ---------------------------------------------------------------------------
-- La migration 002 crée le bucket `kicad-files` et ses policies sur
-- `storage.objects`. Ces objets appartiennent au service Storage de Supabase,
-- absent d'un PostgreSQL nu. On en pose la forme minimale : le test d'isolation
-- ne porte pas sur le stockage, mais 002 doit s'appliquer pour que la chaîne de
-- migrations aille jusqu'au bout.
CREATE SCHEMA IF NOT EXISTS storage;
GRANT USAGE ON SCHEMA storage TO anon, authenticated, service_role;

CREATE TABLE IF NOT EXISTS storage.buckets (
  id                 text PRIMARY KEY,
  name               text NOT NULL,
  public             boolean DEFAULT false,
  file_size_limit    bigint,
  allowed_mime_types text[]
);

CREATE TABLE IF NOT EXISTS storage.objects (
  id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  bucket_id text REFERENCES storage.buckets(id),
  name      text,
  owner     uuid
);
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;

-- Même sémantique que Supabase : découpe le chemin de l'objet en segments, le
-- premier étant l'identifiant du propriétaire dans nos policies.
CREATE OR REPLACE FUNCTION storage.foldername(name text) RETURNS text[]
LANGUAGE sql IMMUTABLE AS $$
  SELECT string_to_array(name, '/');
$$;

GRANT EXECUTE ON FUNCTION storage.foldername(text)
  TO anon, authenticated, service_role;

-- ---------------------------------------------------------------------------
-- Privilèges par défaut
-- ---------------------------------------------------------------------------
-- Supabase accorde ces privilèges AVANT que les tables n'existent, via
-- ALTER DEFAULT PRIVILEGES : toute table créée ensuite en hérite, et les REVOKE
-- explicites des migrations viennent les restreindre par-dessus. Reproduire cet
-- ordre est indispensable — accorder après coup annulerait les REVOKE que les
-- migrations posent, et le test validerait une base plus permissive que la
-- production.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON TABLES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT ALL ON SEQUENCES TO anon, authenticated, service_role;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;

-- Publication Realtime : sur une instance Supabase elle existe déjà. Ici elle
-- permet à la migration 020 d'exécuter réellement `ADD TABLE` et au test
-- d'isolation de vérifier l'appartenance (pcb_run_events in, pcb_runs out).
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_publication WHERE pubname = 'supabase_realtime') THEN
    CREATE PUBLICATION supabase_realtime;
  END IF;
END $$;
