import { describe, expect, it, vi } from 'vitest';
import {
  completePipelineCreditReservation,
  PIPELINE_COST,
  releasePipelineCreditReservation,
  reservePipelineCredits,
} from './credits';

describe('pipeline credit ledger', () => {
  it('reserves the full pipeline cost without directly debiting the user', async () => {
    const rpc = vi.fn().mockResolvedValue({ error: null });

    await reservePipelineCredits({ rpc } as never, 'reservation-1', 'user-1', 'project-1');

    expect(rpc).toHaveBeenCalledWith('reserve_pipeline_credits', {
      p_reservation_id: 'reservation-1',
      p_user_id: 'user-1',
      p_project_id: 'project-1',
      p_amount: PIPELINE_COST,
    });
  });

  it('charges only after a successful pipeline reservation', async () => {
    const rpc = vi.fn().mockResolvedValue({ data: true, error: null });

    await completePipelineCreditReservation({ rpc } as never, 'reservation-1');

    expect(rpc).toHaveBeenCalledWith('complete_pipeline_credit_reservation', {
      p_reservation_id: 'reservation-1',
    });
  });

  it('releases a failed pipeline reservation idempotently', async () => {
    const rpc = vi.fn().mockResolvedValue({ error: null });

    await releasePipelineCreditReservation({ rpc } as never, 'reservation-1');

    expect(rpc).toHaveBeenCalledWith('release_pipeline_credit_reservation', {
      p_reservation_id: 'reservation-1',
    });
  });

  it('propagates a failed reservation release for reconciliation', async () => {
    const rpc = vi.fn().mockResolvedValue({ error: { message: 'database unavailable' } });

    await expect(releasePipelineCreditReservation({ rpc } as never, 'reservation-1'))
      .rejects.toThrow('release_pipeline_credit_reservation failed: database unavailable');
  });
});
