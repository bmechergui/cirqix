/**
 * Un run qui ÉCHOUE doit rendre le crédit qu'il retenait.
 *
 * ⚠️ CONSTAT DU 2026-09-05, relevé par Grok en consultation. Le commentaire de
 * `run-job.ts` affirmait qu'un run réconcilié en `failed` « libère aussi sa
 * réservation ». C'est FAUX : `finish()` ne fait qu'un `UPDATE pcb_runs`, et
 * aucun déclencheur en base ne relie les deux tables. Seuls la route (avant
 * l'enfilement) et `finalize_pipeline_success` (au succès) posent
 * `released_at`.
 *
 * Conséquence : sur un run échoué, le crédit reste retenu jusqu'à l'expiration.
 * C'est supportable à 6 minutes ; ça ne l'est plus dès qu'on aligne la durée de
 * retenue sur celle du pipeline réel — sinon un seul échec gèle le solde une
 * heure.
 *
 * ⚠️ NEVER faire confiance à une docstring qui promet le comportement d'une
 * autre fonction : ce dépôt l'a déjà payé avec `_poser_via_dans_pastille`, dont
 * le commentaire affirmait suivre les règles du fanout après qu'elles eurent
 * changé.
 *
 * Le lien nécessaire existait déjà : `pcb_runs.reservation_id` (migration 019)
 * est renseigné à la création du run par `run-repository.ts`.
 */
import { describe, expect, it, vi } from 'vitest';

import { RESERVATION_TTL_S, extendReservationForRun, releaseReservationForRun } from '../reservations.js';

function fauxSupabase(options: {
  reservationId?: string | null;
  erreurLecture?: unknown;
  erreurRpc?: unknown;
} = {}) {
  const rpc = vi.fn().mockResolvedValue({ error: options.erreurRpc ?? null });
  const maybeSingle = vi.fn().mockResolvedValue({
    data: 'reservationId' in options ? { reservation_id: options.reservationId } : { reservation_id: 'res-1' },
    error: options.erreurLecture ?? null,
  });
  const supabase = {
    rpc,
    from: vi.fn(() => ({
      select: vi.fn(() => ({ eq: vi.fn(() => ({ maybeSingle })) })),
    })),
  };
  return { supabase: supabase as never, rpc, maybeSingle };
}

describe('libération de la retenue à la clôture d un run', () => {
  it('libère la retenue du run', async () => {
    const { supabase, rpc } = fauxSupabase({ reservationId: 'res-42' });

    await releaseReservationForRun(supabase, 'run-1');

    expect(rpc).toHaveBeenCalledWith('release_pipeline_reservation', {
      p_reservation_id: 'res-42',
    });
  });

  it('ne fait rien quand le run n a pas de retenue', async () => {
    // Le mode simulateur ne facture pas : il n a jamais retenu de crédit.
    const { supabase, rpc } = fauxSupabase({ reservationId: null });

    await releaseReservationForRun(supabase, 'run-1');

    expect(rpc).not.toHaveBeenCalled();
  });

  it('n interrompt pas la clôture quand la libération échoue', async () => {
    // ⚠️ La clôture du run est ce qui compte : un crédit retenu se libère de
    // toute façon à l expiration, tandis qu un run laissé `running` serait
    // réconcilié à tort et bloquerait le projet.
    const { supabase } = fauxSupabase({ erreurRpc: { message: 'indisponible' } });

    await expect(releaseReservationForRun(supabase, 'run-1')).resolves.toBeUndefined();
  });

  it('n interrompt pas la clôture quand le run est introuvable', async () => {
    const { supabase, rpc } = fauxSupabase({ erreurLecture: { message: 'timeout' } });

    await expect(releaseReservationForRun(supabase, 'run-1')).resolves.toBeUndefined();
    expect(rpc).not.toHaveBeenCalled();
  });
});


describe('prolongation de la retenue au battement de coeur', () => {
  it('repousse l echeance du run vivant', async () => {
    // ⚠️ `pcb_runs.heartbeat_at` etait ecrit toutes les 30 s et AUCUN code ne
    // le lisait — le reconciliateur que deux commentaires annoncaient n a
    // jamais existe. On s en sert enfin pour ce qu il prouve : le run vit.
    const { supabase, rpc } = fauxSupabase({ reservationId: 'res-7' });

    await extendReservationForRun(supabase, 'run-1');

    expect(rpc).toHaveBeenCalledWith('extend_pipeline_reservation', {
      p_reservation_id: 'res-7',
      p_ttl_seconds: RESERVATION_TTL_S,
    });
  });

  it('ne prolonge rien quand le run ne retient pas de credit', async () => {
    const { supabase, rpc } = fauxSupabase({ reservationId: null });
    await extendReservationForRun(supabase, 'run-1');
    expect(rpc).not.toHaveBeenCalled();
  });

  it('survit a une base qui refuse la prolongation', async () => {
    // ⚠️ La migration 021 peut ne pas etre appliquee : la fonction n existe
    // alors pas. Le comportement retombe sur l echeance fixe, il ne casse pas
    // le battement de coeur — seule preuve qu un run de 20 min vit encore.
    const { supabase } = fauxSupabase({
      erreurRpc: { message: 'function extend_pipeline_reservation does not exist' },
    });
    await expect(extendReservationForRun(supabase, 'run-1')).resolves.toBeUndefined();
  });

  it('demande une duree que la base accepte', () => {
    // `extend_pipeline_reservation` refuse hors de 1..3600 (`invalid_ttl`).
    expect(RESERVATION_TTL_S).toBeGreaterThan(0);
    expect(RESERVATION_TTL_S).toBeLessThanOrEqual(3600);
  });
});


describe('le cablage : les regles sont-elles APPELEES ?', () => {
  it('le battement de coeur prolonge, la cloture libere', async () => {
    // ⚠️ Une regle correcte que personne n invoque est indistinguable d une
    // regle absente. C est ce qui a masque pendant des semaines que le
    // Geometre CMA-ES ne tournait jamais en production.
    const source = await import('node:fs/promises').then((fs) =>
      fs.readFile(new URL('../adapters.ts', import.meta.url), 'utf-8'),
    );
    const heartbeat = source.slice(source.indexOf('async heartbeat'));
    expect(heartbeat.slice(0, heartbeat.indexOf('async isCancelled')))
      .toContain('extendReservationForRun');

    const finish = source.slice(source.indexOf('async finish'));
    expect(finish.slice(0, finish.indexOf('async isCancelled')))
      .toContain('releaseReservationForRun');
  });
});
