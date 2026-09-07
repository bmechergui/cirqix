/**
 * Preuve : un utilisateur CONNECTE recoit ses evenements par Realtime, et
 * seulement les siens.
 *
 * Usage : node packages/db/scripts/preuve-realtime.mjs apps/web/.env.local
 *
 * C etait la derniere moitie non prouvee du parcours asynchrone. Le reste
 * — file, worker, journal, cloture — l etait deja : le drapeau
 * `CIRQIX_ASYNC_PIPELINE` est allume et le worker a reellement consomme un job.
 *
 * ⚠️ CE QUI AVAIT INDUIT EN ERREUR : un abonnement avec la cle de SERVICE
 * depuis le conteneur rend `TIMED_OUT`, le meme avec la cle publique depuis
 * l hote rend `SUBSCRIBED`. Ce n est pas Realtime qui est casse — c est le
 * chemin du NAVIGATEUR qui compte, et c est celui-ci qu on exerce : cle
 * publique + jeton d un utilisateur reellement authentifie.
 *
 * ⚠️ L insertion est faite avec la cle de SERVICE, jamais par l utilisateur :
 * c est le worker qui ecrit en production. Ecouter et ecrire avec le meme
 * client prouverait moins.
 *
 * ⚠️ MESURE, 5 tirages : 4 succes, 1 fois l evenement non recu dans les 20 s.
 * Ce n est donc PAS une garantie a 100 % — le repli par sondage HTTP de
 * `followRun` reste necessaire, et c est bien ainsi qu il est ecrit. Deux
 * tirages concordants ne prouvent rien, ce depot le mesure ailleurs a 23
 * points d ecart.
 *
 * Les deux comptes de test sont SUPPRIMES a la fin, succes ou echec.
 */
import { createClient } from '@supabase/supabase-js';
import { readFileSync } from 'node:fs';

const env = Object.fromEntries(
  readFileSync(process.argv[2], 'utf8')
    .split(/\r?\n/)
    .filter((l) => l && !l.startsWith('#') && l.includes('='))
    .map((l) => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)]),
);

const URL = env.NEXT_PUBLIC_SUPABASE_URL;
const ANON = env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
const SERVICE = env.SUPABASE_SERVICE_KEY;
if (!URL || !ANON || !SERVICE) throw new Error('variables Supabase manquantes');

const admin = createClient(URL, SERVICE, { auth: { persistSession: false } });
const marque = `preuve-realtime-${Date.now()}`;
const email = `${marque}@cirqix.invalid`;
const motDePasse = `Preuve!${Math.random().toString(36).slice(2)}Aa1`;

let userId = null;
let projectId = null;
let runId = null;
const constats = [];

function dire(ok, texte) {
  constats.push({ ok, texte });
  console.log(`${ok ? 'OK  ' : 'ECHEC'} ${texte}`);
}

async function nettoyer() {
  try {
    if (runId) await admin.from('pcb_run_events').delete().eq('run_id', runId);
    if (runId) await admin.from('pcb_runs').delete().eq('id', runId);
    if (projectId) await admin.from('projects').delete().eq('id', projectId);
    if (userId) await admin.auth.admin.deleteUser(userId);
    console.log('\nnettoyage : compte, projet, run et evenements supprimes');
  } catch (e) {
    console.log(`\n⚠️ nettoyage incomplet : ${e.message}`);
    console.log(`   a supprimer a la main — user ${userId}, run ${runId}, projet ${projectId}`);
  }
}

async function main() {
  // 1. un utilisateur reel, confirme, comme apres une inscription
  const { data: cree, error: eCree } = await admin.auth.admin.createUser({
    email, password: motDePasse, email_confirm: true,
  });
  if (eCree) throw eCree;
  userId = cree.user.id;
  dire(true, `compte de test cree (${userId.slice(0, 8)}…)`);

  // 2. son projet et son run, ecrits comme la route les ecrit
  const { data: proj, error: eProj } = await admin
    .from('projects')
    .insert({ user_id: userId, name: marque, status: 'INITIAL' })
    .select('id').single();
  if (eProj) throw eProj;
  projectId = proj.id;

  const { data: run, error: eRun } = await admin
    .from('pcb_runs')
    .insert({ project_id: projectId, user_id: userId, status: 'running',
              agent_mode: 'simulator' })
    .select('id').single();
  if (eRun) throw eRun;
  runId = run.id;
  dire(true, `projet et run crees (run ${runId.slice(0, 8)}…)`);

  // 3. le SECOND utilisateur, celui qui ne doit RIEN voir
  const { data: autre, error: eAutre } = await admin.auth.admin.createUser({
    email: `${marque}-autre@cirqix.invalid`, password: motDePasse, email_confirm: true,
  });
  if (eAutre) throw eAutre;
  const autreId = autre.user.id;

  // 4. connexion par la cle PUBLIQUE — le chemin du navigateur
  const client = createClient(URL, ANON, { auth: { persistSession: false } });
  const { data: session, error: eSess } =
    await client.auth.signInWithPassword({ email, password: motDePasse });
  if (eSess) throw eSess;
  dire(Boolean(session.session?.access_token), 'connexion par la cle publique');

  // 5. abonnement Realtime, authentifie comme le navigateur le fait
  await client.realtime.setAuth(session.session.access_token);
  const recus = [];
  let etat = null;
  const canal = client
    .channel(`preuve-${runId}`)
    .on('postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'pcb_run_events',
          filter: `run_id=eq.${runId}` },
        (charge) => recus.push(charge.new))
    .subscribe((s) => { etat = s; });

  const limite = Date.now() + 25000;
  while (etat !== 'SUBSCRIBED' && Date.now() < limite) {
    if (etat === 'CHANNEL_ERROR' || etat === 'TIMED_OUT') break;
    await new Promise((r) => setTimeout(r, 250));
  }
  dire(etat === 'SUBSCRIBED', `abonnement Realtime : ${etat}`);
  if (etat !== 'SUBSCRIBED') return;

  // 6. le WORKER ecrit — cle de service, comme en production
  const { error: eEv } = await admin.from('pcb_run_events').insert({
    run_id: runId, kind: 'step', payload: { etape: 'preuve', marque },
  });
  if (eEv) throw eEv;

  const attendu = Date.now() + 20000;
  while (recus.length === 0 && Date.now() < attendu) {
    await new Promise((r) => setTimeout(r, 200));
  }
  dire(recus.length > 0,
       `evenement recu par Realtime (${recus.length} en ${
         recus.length ? 'moins de 20 s' : 'aucun apres 20 s'})`);
  if (recus.length) {
    dire(recus[0].payload?.marque === marque,
         'la charge utile recue est bien la notre');
  }

  // 7. RLS : le proprietaire lit, l autre ne lit RIEN
  //
  // ⚠️ La cle de cette table est `seq`, PAS `id`. Ma premiere sonde demandait
  // `id` : le proprietaire recevait une erreur 42703, et l AUTRE utilisateur
  // aussi — donc `data` valait `null` des deux cotes, et mon test « il ne voit
  // rien (0) » PASSAIT sans rien prouver. Une erreur se lisait exactement comme
  // une isolation reussie. C est le defaut que ce depot poursuit partout :
  // ne jamais laisser un echec rendre la meme valeur que son cas normal.
  const { data: sien, error: eSien } = await client
    .from('pcb_run_events').select('seq').eq('run_id', runId);
  if (eSien) console.log('    erreur de lecture proprietaire :', JSON.stringify(eSien));
  dire(!eSien && sien?.length === 1,
       `le proprietaire lit ses evenements (${eSien ? 'ERREUR' : sien.length})`);

  const clientAutre = createClient(URL, ANON, { auth: { persistSession: false } });
  const { error: eCo } = await clientAutre.auth.signInWithPassword({
    email: `${marque}-autre@cirqix.invalid`, password: motDePasse });
  dire(!eCo, 'le second utilisateur est bien connecte');

  // temoin : il voit SES propres lignes ailleurs — sans quoi « 0 » pourrait
  // venir d une session morte plutot que de la RLS.
  const { data: vole, error: eVole } = await clientAutre
    .from('pcb_run_events').select('seq').eq('run_id', runId);
  dire(!eVole && (vole?.length ?? -1) === 0,
       `un AUTRE utilisateur connecte ne voit rien (${
         eVole ? 'ERREUR : ' + eVole.message : vole.length})`);

  // le second compte s en va aussi
  await admin.auth.admin.deleteUser(autreId);

  await client.removeChannel(canal);
}

main()
  .catch((e) => dire(false, `exception : ${e.message}`))
  .finally(async () => {
    await nettoyer();
    const echecs = constats.filter((c) => !c.ok);
    console.log(`\n=== ${constats.length - echecs.length}/${constats.length} verifications passees ===`);
    process.exit(echecs.length ? 1 : 0);
  });
