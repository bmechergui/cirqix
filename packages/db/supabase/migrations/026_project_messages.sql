-- 026 — Historique de discussion par projet.
--
-- Le chat d'un projet vivait UNIQUEMENT dans le store Zustand du navigateur :
-- recharger la page, ou rouvrir le projet, effaçait la conversation.
--
-- `pcb_run_events` ne suffit pas : il ne porte pas la demande de l'utilisateur
-- (le prompt ne voyage que dans le job), il ne couvre que le chemin asynchrone,
-- et il est découpé en deltas techniques. Une table dédiée porte la
-- conversation telle que l'utilisateur l'a lue : un message par tour.
--
-- Écriture : SERVEUR SEULEMENT.
--   * la route `POST /api/agent` écrit la demande (client admin, APRÈS avoir
--     lu le projet sous RLS — la propriété est donc vérifiée) et, en SSE, la
--     réponse de l'agent à la fin du flux ;
--   * le worker écrit la réponse des runs asynchrones (service_role).
-- Aucune politique d'écriture pour `authenticated` : un client capable
-- d'insérer pourrait fabriquer une réponse de l'agent dans l'historique.
--
-- ⚠️ Rien ici ne touche au gate JLCPCB, aux crédits ni à la provenance.

CREATE TABLE IF NOT EXISTS public.project_messages (
  id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  project_id  uuid NOT NULL REFERENCES public.projects ON DELETE CASCADE,
  -- CASCADE aussi côté utilisateur : un FK en NO ACTION a déjà bloqué la
  -- suppression de comptes de test (voir `credits_user_id_fkey`).
  user_id     uuid NOT NULL REFERENCES auth.users ON DELETE CASCADE,
  role        text NOT NULL CHECK (role IN ('user', 'assistant')),
  -- Même borne que `CHAT_MESSAGE_MAX_CHARS` (packages/agents) : l'écrivain
  -- tronque avant d'insérer, la contrainte garde la table si un autre écrit.
  content     text NOT NULL CHECK (char_length(content) BETWEEN 1 AND 100000),
  created_at  timestamptz NOT NULL DEFAULT now()
);

-- Le seul accès chaud : les N derniers messages d'un projet.
CREATE INDEX IF NOT EXISTS project_messages_project_idx
  ON public.project_messages (project_id, created_at DESC);

ALTER TABLE public.project_messages ENABLE ROW LEVEL SECURITY;

-- Lecture de ses propres messages, sur ses propres projets. La double condition
-- tient même si une ligne était un jour écrite avec un `user_id` incohérent.
DROP POLICY IF EXISTS project_messages_select_own ON public.project_messages;
CREATE POLICY project_messages_select_own ON public.project_messages
  FOR SELECT TO authenticated
  USING (
    auth.uid() = user_id
    AND EXISTS (
      SELECT 1 FROM public.projects p
      WHERE p.id = project_messages.project_id
        AND p.user_id = auth.uid()
    )
  );
