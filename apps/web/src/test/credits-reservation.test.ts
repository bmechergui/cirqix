import { beforeEach, describe, expect, it, vi } from 'vitest';
import {
  InsufficientCreditsError,
  CreditReservationError,
  PipelineAlreadyRunningError,
  PIPELINE_RESERVATION_TTL_S,
  PIPELINE_COST,
  reservePipelineCredits,
  releasePipelineReservation,
} from '@/app/api/agent/lib/credits';

/**
 * Réservation de crédits pendant le pipeline (issue #117).
 *
 * Le solde était lu, jugé suffisant, puis débité 300 s plus tard : entre les
 * deux, rien ne l'engageait. Le quota par utilisateur (PR #120) a borné la
 * cadence d'allumage ; il ne réserve toujours rien. Ces tests portent sur la
 * couche TypeScript — la garantie elle-même est en base, sérialisée par un
 * `FOR UPDATE` sur la ligne `credits`, et vérifiée par packages/db/tests.
 */

const RESERVATION_ID = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const USER_ID = 'u1';
const PROJECT_ID = 'p1';

function makeSupabase(response: { data?: unknown; error?: unknown }) {
  const rpc = vi.fn().mockResolvedValue({ data: null, error: null, ...response });
  return { supabase: { rpc } as never, rpc };
}

beforeEach(() => vi.clearAllMocks());

describe('reservePipelineCredits', () => {
  it('réserve exactement le prix du pipeline, pour une durée qui couvre son exécution', async () => {
    const { supabase, rpc } = makeSupabase({ data: RESERVATION_ID });

    const id = await reservePipelineCredits(supabase, USER_ID, PROJECT_ID);

    expect(id).toBe(RESERVATION_ID);
    expect(rpc).toHaveBeenCalledWith('reserve_pipeline_credits', {
      p_user_id: USER_ID,
      p_project_id: PROJECT_ID,
      p_amount: PIPELINE_COST,
      p_ttl_seconds: PIPELINE_RESERVATION_TTL_S,
    });
  });

  it('couvre la durée du pipeline ASYNCHRONE, pas celle de la route', () => {
    // ⚠️ Ce test exigeait « > 300 s », la borne de la route SYNCHRONE, et
    // 360 s le satisfaisait. Le pipeline asynchrone dure 19 MINUTES mesurées
    // (run 4290007c) : la retenue expirait à la sixième, le crédit se libérait
    // pendant que le job tournait, et un second projet pouvait démarrer sur le
    // même solde. Le test passait au vert sur la mauvaise référence.
    const DUREE_PIPELINE_MESUREE_S = 19 * 60;
    expect(PIPELINE_RESERVATION_TTL_S).toBeGreaterThan(DUREE_PIPELINE_MESUREE_S);
  });

  it('ne dépasse pas le plafond accepté par la base', () => {
    // `reserve_pipeline_credits` refuse hors de 1..3600 (`invalid_ttl`) : une
    // valeur plus grande ferait échouer TOUTE réservation, donc tout pipeline.
    expect(PIPELINE_RESERVATION_TTL_S).toBeLessThanOrEqual(3600);
  });

  it('distingue le refus pour solde insuffisant de toute autre panne', async () => {
    // L'appelant doit répondre 402 ici, et 500 ailleurs : confondre les deux
    // annoncerait « crédits insuffisants » sur une panne de base.
    const { supabase } = makeSupabase({
      error: { code: '22023', message: 'insufficient_credits' },
    });

    await expect(reservePipelineCredits(supabase, USER_ID, PROJECT_ID)).rejects.toBeInstanceOf(
      InsufficientCreditsError,
    );
  });

  it('ne prend pas un projet volé pour un manque de crédits', async () => {
    // `invalid_project` porte le même SQLSTATE que `insufficient_credits` :
    // se fier au code seul répondrait 402 à une tentative d'utiliser le projet
    // d'autrui, en masquant l'anomalie derrière un message de facturation.
    const { supabase } = makeSupabase({
      error: { code: '22023', message: 'invalid_project: project does not belong to user' },
    });

    const failure = reservePipelineCredits(supabase, USER_ID, PROJECT_ID);

    await expect(failure).rejects.toBeInstanceOf(CreditReservationError);
    await expect(failure).rejects.not.toBeInstanceOf(InsufficientCreditsError);
  });

  it("distingue le run déjà en cours d'un manque de crédits", async () => {
    // Même SQLSTATE encore. Répondre 402 ici enverrait acheter des crédits
    // pour un refus qui n'a rien de financier — le solde est intact, c'est le
    // projet qui est occupé.
    const { supabase } = makeSupabase({
      error: { code: '22023', message: 'pipeline_already_running' },
    });

    const failure = reservePipelineCredits(supabase, USER_ID, PROJECT_ID);

    await expect(failure).rejects.toBeInstanceOf(PipelineAlreadyRunningError);
    await expect(failure).rejects.not.toBeInstanceOf(InsufficientCreditsError);
  });

  it('échoue si la RPC ne renvoie aucun identifiant', async () => {
    // Sans identifiant, il n'y a rien à libérer : le crédit resterait retenu
    // jusqu'à expiration alors que le pipeline n'a même pas démarré.
    const { supabase } = makeSupabase({ data: null });

    await expect(reservePipelineCredits(supabase, USER_ID, PROJECT_ID)).rejects.toBeInstanceOf(
      CreditReservationError,
    );
  });
});

describe('releasePipelineReservation', () => {
  it('libère la réservation par son identifiant', async () => {
    const { supabase, rpc } = makeSupabase({ data: true });

    await releasePipelineReservation(supabase, RESERVATION_ID);

    expect(rpc).toHaveBeenCalledWith('release_pipeline_reservation', {
      p_reservation_id: RESERVATION_ID,
    });
  });

  it("n'échoue jamais : elle est appelée depuis un finally", async () => {
    // Une exception ici masquerait l'erreur réelle du pipeline. Le TTL en base
    // reste le filet : une réservation non libérée expire d'elle-même.
    const { supabase } = makeSupabase({ error: { code: '08006', message: 'connection lost' } });

    await expect(releasePipelineReservation(supabase, RESERVATION_ID)).resolves.toBeUndefined();
  });
});
