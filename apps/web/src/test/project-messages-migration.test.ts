import { readFileSync } from 'node:fs';
import path from 'node:path';
import { describe, expect, it } from 'vitest';

/**
 * Garde statique de la migration `project_messages`.
 *
 * L'isolation user A / user B se PROUVE en base (voir le rapport de la PR : la
 * migration n'est pas encore appliquée). Ce test verrouille ce que le fichier
 * doit porter pour qu'elle tienne : RLS activée, lecture bornée au propriétaire
 * du message ET du projet, et AUCUNE politique d'écriture pour `authenticated`
 * — seuls la route (client admin, après contrôle du propriétaire) et le worker
 * écrivent. Un client capable d'insérer pourrait fabriquer une réponse de
 * l'agent dans l'historique.
 */
const SQL = readFileSync(
  path.resolve(__dirname, '../../../../packages/db/supabase/migrations/026_project_messages.sql'),
  'utf8',
);
const code = SQL.split('\n').filter((l) => !l.trim().startsWith('--')).join('\n');

describe('migration 026_project_messages', () => {
  it('crée la table avec un rôle borné à user | assistant', () => {
    expect(code).toMatch(/CREATE TABLE IF NOT EXISTS public\.project_messages/);
    expect(code).toMatch(/role\s+text NOT NULL CHECK \(role IN \('user',\s*'assistant'\)\)/);
  });

  it('suit la vie du projet (suppression en cascade)', () => {
    expect(code).toMatch(/project_id\s+uuid NOT NULL REFERENCES public\.projects[^,]*ON DELETE CASCADE/);
  });

  it('active la RLS', () => {
    expect(code).toMatch(/ALTER TABLE public\.project_messages ENABLE ROW LEVEL SECURITY/);
  });

  it('borne la lecture au propriétaire du message et du projet', () => {
    const policy = code.match(/CREATE POLICY project_messages_select_own[\s\S]*?;/)?.[0] ?? '';
    expect(policy).toMatch(/FOR SELECT TO authenticated/);
    expect(policy).toMatch(/auth\.uid\(\) = user_id/);
    expect(policy).toMatch(/p\.user_id = auth\.uid\(\)/);
  });

  it('n’ouvre aucune écriture aux clients', () => {
    expect(code).not.toMatch(/FOR (INSERT|UPDATE|DELETE|ALL)/);
  });
});
