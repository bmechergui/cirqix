/**
 * Preuve : l'historique de discussion d'un projet est ecrit par la VRAIE route,
 * relu par la VRAIE route, et invisible pour un autre compte.
 *
 * Usage : node packages/db/scripts/preuve-historique.mjs apps/web/.env.local [http://localhost:3333]
 *
 * #198 est couvert par des tests unitaires et par le worker (reponse de l'agent
 * ecrite a la fin d'un run enfile). Restait le chemin du NAVIGATEUR : le message
 * de l'utilisateur, ecrit par `POST /api/agent` apres verification du projet
 * sous RLS. On l'exerce ici avec un vrai compte, une vraie session et le cookie
 * que `@supabase/ssr` 0.4 lit — sans navigateur.
 *
 * Les deux comptes de test sont SUPPRIMES a la fin, succes ou echec, et le
 * nettoyage relit ce qui reste (piege du 2026-09-07 : il annoncait « supprimes »
 * pendant que quinze comptes s'accumulaient).
 */
import { createClient } from '@supabase/supabase-js';
import { readFileSync } from 'node:fs';

const env = Object.fromEntries(
  readFileSync(process.argv[2], 'utf8')
    .split(/\r?\n/)
    .filter((l) => l && !l.startsWith('#') && l.includes('='))
    .map((l) => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1).replace(/^"|"$/g, '')]),
);
const APP = process.argv[3] ?? 'http://localhost:3333';
const URL_SB = env.NEXT_PUBLIC_SUPABASE_URL;
const ANON = env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const SERVICE = env.SUPABASE_SERVICE_KEY;
if (!URL_SB || !ANON || !SERVICE) throw new Error('variables Supabase manquantes');

const REF = new URL(URL_SB).hostname.split('.')[0];
const admin = createClient(URL_SB, SERVICE, { auth: { persistSession: false } });
const marque = `preuve-historique-${Date.now()}`;
const motDePasse = `Preuve!${Math.random().toString(36).slice(2)}Aa1`;
const PROMPT = 'Preuve historique : diviseur de tension 5 V vers 3,3 V avec deux resistances.';
const ATTENTE_RUN_MS = 15 * 60 * 1000;

const comptes = [];
const constats = [];
function dire(ok, texte) {
  constats.push({ ok, texte });
  console.log(`${ok ? 'OK   ' : 'ECHEC'} ${texte}`);
}

/** Le cookie de session tel que `@supabase/ssr` 0.4 l'ecrit : JSON, decoupe au-dela de 3180. */
function cookieDeSession(session) {
  const nom = `sb-${REF}-auth-token`;
  const valeur = encodeURIComponent(JSON.stringify(session));
  const TAILLE = 3180;
  if (valeur.length <= TAILLE) return `${nom}=${valeur}`;
  const morceaux = [];
  for (let i = 0; i * TAILLE < valeur.length; i++) {
    morceaux.push(`${nom}.${i}=${valeur.slice(i * TAILLE, (i + 1) * TAILLE)}`);
  }
  return morceaux.join('; ');
}

async function creerCompte(suffixe) {
  const email = `${marque}${suffixe}@cirqix.invalid`;
  const { data, error } = await admin.auth.admin.createUser({ email, password: motDePasse, email_confirm: true });
  if (error) throw error;
  comptes.push(data.user.id);
  const client = createClient(URL_SB, ANON, { auth: { persistSession: false } });
  const { data: s, error: eS } = await client.auth.signInWithPassword({ email, password: motDePasse });
  if (eS) throw eS;
  return { id: data.user.id, cookie: cookieDeSession(s.session) };
}

async function messages(projectId) {
  const { data, error } = await admin.from('project_messages')
    .select('role, content, created_at').eq('project_id', projectId).order('created_at');
  if (error) throw error;
  return data;
}

async function nettoyer() {
  const restes = [];
  for (const id of comptes) {
    for (const p of (await admin.from('projects').select('id').eq('user_id', id)).data ?? []) {
      for (const r of (await admin.from('pcb_runs').select('id').eq('project_id', p.id)).data ?? []) {
        await admin.from('pcb_run_events').delete().eq('run_id', r.id);
        await admin.from('pcb_runs').delete().eq('id', r.id);
      }
      await admin.from('project_messages').delete().eq('project_id', p.id);
      await admin.from('projects').delete().eq('id', p.id);
    }
    for (const table of ['credit_reservations', 'credit_transactions', 'credits', 'footprints']) {
      await admin.from(table).delete().eq('user_id', id);
    }
    const { error } = await admin.auth.admin.deleteUser(id);
    if (error) restes.push(`${id} (${error.message})`);
  }
  const { count } = await admin.from('project_messages').select('id', { count: 'exact', head: true })
    .like('content', 'Preuve historique%');
  if (restes.length === 0 && !count) {
    console.log('\nnettoyage verifie : comptes, projet, runs, evenements et messages supprimes');
    return;
  }
  console.log(`\n⚠️ NETTOYAGE INCOMPLET — comptes : ${restes.join(', ') || 'aucun'} · messages de preuve restants : ${count}`);
  constats.push({ ok: false, texte: 'nettoyage complet' });
}

async function main() {
  const a = await creerCompte('');
  const b = await creerCompte('-autre');
  dire(true, `deux comptes de test crees et connectes (${a.id.slice(0, 8)}…, ${b.id.slice(0, 8)}…)`);

  const { data: proj, error: eProj } = await admin.from('projects')
    .insert({ user_id: a.id, name: marque, status: 'INITIAL' }).select('id').single();
  if (eProj) throw eProj;
  const projectId = proj.id;

  // Un compte neuf recoit 5 credits ; la route exige le cout d'un pipeline AVANT
  // de regarder le mode (402 mesure au premier essai). Le compte de test est
  // supprime a la fin, et un run driver ne debite rien.
  const { error: eCred } = await admin.from('credits').update({ balance: 100 }).eq('user_id', a.id);
  if (eCred) throw eCred;

  // 1. La VRAIE route, avec la session du proprietaire.
  const rep = await fetch(`${APP}/api/agent`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Cookie: a.cookie },
    body: JSON.stringify({ projectId, prompt: PROMPT }),
  });
  const corps = await rep.text();
  const accepte = rep.status === 200 || rep.status === 202;
  dire(accepte, `POST /api/agent -> ${rep.status} ${corps.slice(0, 120).replace(/\s+/g, ' ')}`);
  if (!accepte) return; // rien n'a demarre : attendre un run serait attendre pour rien

  // 2. Le message de l'utilisateur, ecrit tout de suite par la route.
  let lus = [];
  for (const limite = Date.now() + 15000; Date.now() < limite; await new Promise((r) => setTimeout(r, 500))) {
    lus = await messages(projectId);
    if (lus.some((m) => m.role === 'user')) break;
  }
  const user = lus.find((m) => m.role === 'user');
  dire(user?.content === PROMPT, `message utilisateur enregistre par la route : ${user ? 'oui, contenu identique' : 'NON'}`);

  // 3. La reponse de l'agent, a la fin du run.
  let fin = null;
  for (const limite = Date.now() + ATTENTE_RUN_MS; Date.now() < limite; await new Promise((r) => setTimeout(r, 5000))) {
    const { data: runs } = await admin.from('pcb_runs').select('status').eq('project_id', projectId);
    fin = runs?.find((r) => ['succeeded', 'failed', 'cancelled'].includes(r.status))?.status ?? null;
    if (fin) break;
  }
  await new Promise((r) => setTimeout(r, 3000));
  lus = await messages(projectId);
  const reponse = lus.find((m) => m.role === 'assistant');
  dire(Boolean(reponse), `run termine (${fin ?? 'pas termine dans le delai'}) · reponse de l'agent enregistree : ${reponse ? 'oui' : 'NON'}`);
  dire(lus[0]?.role === 'user', `ordre : ${lus.map((m) => m.role).join(' -> ') || 'vide'}`);

  // 4. Relecture par la VRAIE route : le proprietaire voit, l'autre non.
  // La route rend `{ success, data: { messages } }`. Une forme inattendue rend
  // `null`, jamais 0 : un « 0 message » lu sur une reponse illisible passerait
  // pour une isolation reussie (piege du 2026-09-07, sonde Realtime).
  const compter = (json) => (Array.isArray(json?.data?.messages) ? json.data.messages.length : null);

  const pourA = await fetch(`${APP}/api/projects/${projectId}/messages`, { headers: { Cookie: a.cookie } });
  const nA = compter(await pourA.json().catch(() => null));
  dire(pourA.status === 200 && nA === lus.length, `GET messages (proprietaire) -> ${pourA.status}, ${nA} message(s) sur ${lus.length} en base`);

  const pourB = await fetch(`${APP}/api/projects/${projectId}/messages`, { headers: { Cookie: b.cookie } });
  const nB = compter(await pourB.json().catch(() => null));
  // L'autre compte doit etre refuse, OU recevoir une liste LISIBLE et vide.
  const refuse = pourB.status === 401 || pourB.status === 403 || pourB.status === 404;
  dire(refuse || (pourB.status === 200 && nB === 0), `GET messages (autre compte) -> ${pourB.status}, ${nB} message(s)`);
}

try {
  await main();
} catch (err) {
  dire(false, `exception : ${err?.message ?? err}`);
} finally {
  await nettoyer();
  const echecs = constats.filter((c) => !c.ok).length;
  console.log(`\n${echecs === 0 ? 'PREUVE COMPLETE' : `${echecs} ECHEC(S)`}`);
  process.exit(echecs === 0 ? 0 : 1);
}
