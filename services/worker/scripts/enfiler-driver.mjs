/**
 * Enfile un run « driver » : la chaîne réelle, sans le moindre appel au modèle.
 *
 * Usage, depuis la racine du dépôt :
 *   node services/worker/scripts/enfiler-driver.mjs \
 *        services/kicad/examples/carte-01-diviseur/input/schema.json \
 *        apps/web/.env.local
 *
 * ## Pourquoi ce script existe
 *
 * Le solde de l'API du modèle est épuisé depuis le 2026-09-06 : l'orchestrateur
 * étant la première étape, plus aucun PCB ne peut aboutir par la voie normale.
 * `call_agent_schema` est pourtant le SEUL maillon qui appelle un modèle — le
 * banc des dix cartes a mesuré que tout le reste va jusqu'aux Gerbers sans lui.
 *
 * Ce script exerce donc la chaîne COMPLÈTE — route → file → worker → journal →
 * Realtime — avec un schéma écrit par le driver.
 *
 * ## Ce qu'il n'accorde pas
 *
 * ⚠️ La provenance posée est `driver`, et `POST /api/jlcpcb/order` exige
 * `orchestrator` : le board produit est réel et fabricable, mais NON
 * COMMANDABLE. C'est voulu — il n'a pas traversé la boucle autonome que le
 * produit vend. Ne PAS assouplir ce gate pour le faire passer.
 *
 * ⚠️ `agent_mode` ne voyage PAS dans le payload du job, délibérément : il est
 * écrit ici, dans `pcb_runs`, et relu par le worker. Sans quoi enfiler un job
 * reviendrait à décerner la commandabilité.
 */
import { createClient } from '@supabase/supabase-js';
import { Queue } from 'bullmq';
import { readFileSync } from 'node:fs';
import { randomUUID } from 'node:crypto';

const [, , cheminSchema, cheminEnv = 'apps/web/.env.local'] = process.argv;
if (!cheminSchema) {
  console.error('usage : node enfiler-driver.mjs <schema.json> [.env.local]');
  process.exit(2);
}

const env = Object.fromEntries(
  readFileSync(cheminEnv, 'utf8')
    .split(/\r?\n/).filter((l) => l && !l.startsWith('#') && l.includes('='))
    .map((l) => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)]),
);

const admin = createClient(env.NEXT_PUBLIC_SUPABASE_URL, env.SUPABASE_SERVICE_KEY,
                           { auth: { persistSession: false } });

const schema = JSON.parse(readFileSync(cheminSchema, 'utf8'));
if (!Array.isArray(schema.components) || schema.components.length === 0) {
  console.error('schéma sans composants — rien à router');
  process.exit(2);
}
// Le banc écrit ses schémas avec des clés de commentaire ; elles ne servent à
// rien ici et alourdiraient le payload du job.
for (const cle of Object.keys(schema)) if (cle.startsWith('_')) delete schema[cle];

const nom = cheminSchema.split(/[\\/]/).slice(-3)[0] ?? 'driver';

// L'utilisateur : le premier compte réel du projet. On ne CRÉE pas de compte —
// ce run laisse un projet et des artefacts derrière lui, il doit appartenir à
// quelqu'un de réel.
const { data: users, error: eUsers } = await admin.auth.admin.listUsers({ perPage: 1 });
if (eUsers) throw eUsers;
const userId = users.users[0]?.id;
if (!userId) {
  console.error('aucun utilisateur dans le projet — impossible de rattacher le run');
  process.exit(1);
}

const { data: projet, error: eProjet } = await admin
  .from('projects')
  .insert({ user_id: userId, name: `driver — ${nom}`, status: 'INITIAL' })
  .select('id').single();
if (eProjet) throw eProjet;

const runId = randomUUID();
const { error: eRun } = await admin.from('pcb_runs').insert({
  id: runId,
  project_id: projet.id,
  user_id: userId,
  status: 'queued',
  // ⚠️ La provenance est posée ICI, jamais transmise par le job.
  agent_mode: 'driver',
});
if (eRun) throw eRun;

const file = new Queue('pcb-pipeline', { connection: { url: env.REDIS_URL } });
await file.add('run', {
  runId,
  projectId: projet.id,
  userId,
  prompt: `Carte ${nom} — schéma fourni par le driver.`,
  iterationStart: 0,
  schema,
}, { jobId: `project-${projet.id}`, attempts: 1 });

console.log(`run ${runId} enfilé · projet ${projet.id} · ${schema.components.length} composants`);
console.log('suivi du journal (Ctrl+C pour arrêter le suivi, le run continue) :\n');

let vus = 0;
const debut = Date.now();
for (;;) {
  const { data: evs } = await admin
    .from('pcb_run_events').select('seq, kind, payload')
    .eq('run_id', runId).order('seq').range(vus, vus + 199);

  for (const e of evs ?? []) {
    // Les jetons de texte sont bruyants et sans intérêt ici.
    if (e.kind === 'token') continue;
    const p = e.payload ?? {};
    const detail = p.step ?? p.status ?? p.message ?? p.percent ?? '';
    console.log(`  +${String(Math.round((Date.now() - debut) / 1000)).padStart(4)}s  ${e.kind}  ${JSON.stringify(detail).slice(0, 120)}`);
  }
  vus += (evs ?? []).length;

  const { data: run } = await admin.from('pcb_runs')
    .select('status, error').eq('id', runId).single();
  if (run && run.status !== 'queued' && run.status !== 'running') {
    console.log(`\nrun ${run.status}${run.error ? ` — ${run.error}` : ''}`);
    const { data: proj } = await admin.from('projects')
      .select('status, agent_mode').eq('id', projet.id).single();
    console.log(`projet : ${proj?.status} · provenance ${proj?.agent_mode}`);
    // ⚠️ Rappel volontaire : ce board n'est PAS commandable.
    if (proj?.agent_mode !== 'orchestrator') {
      console.log('→ non commandable chez JLCPCB (provenance ≠ orchestrator), c\'est voulu.');
    }
    break;
  }
  await new Promise((r) => setTimeout(r, 3000));
}

await file.close();
process.exit(0);
