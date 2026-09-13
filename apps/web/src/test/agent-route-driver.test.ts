import { beforeEach, afterEach, describe, expect, it, vi } from 'vitest';

/**
 * `CIRQIX_AGENT_MODE=driver` (D-2026-09-13-b) : la route enfile un run de
 * provenance `driver`, SANS retenue de crédit, et refuse franchement sans
 * file. Ni simulateur, ni orchestrateur : le porteur du driver vit dans le
 * worker.
 */
const supabaseMock = vi.hoisted(() => ({
  createRouteHandlerClient: vi.fn(),
  createAdminClient: vi.fn(() => ({ rpc: vi.fn() })),
}));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);
vi.mock('@/shared/lib/ratelimit', () => ({
  checkRateLimit: vi.fn().mockResolvedValue({ success: true, remaining: 2 }),
}));
const reserveMock = vi.hoisted(() => vi.fn());
vi.mock('@/app/api/agent/lib/credits', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/app/api/agent/lib/credits')>();
  return { ...actual, reservePipelineCredits: reserveMock, releasePipelineReservation: vi.fn(async () => {}) };
});
const runSimulatorAgentMock = vi.hoisted(() => vi.fn(async () => {}));
const runRealOrchestratorMock = vi.hoisted(() => vi.fn(async () => {}));
vi.mock('@/app/api/agent/lib/simulator', () => ({ runSimulatorAgent: runSimulatorAgentMock }));
vi.mock('@/app/api/agent/lib/orchestrator-bridge', () => ({ runRealOrchestrator: runRealOrchestratorMock }));
vi.mock('@/app/api/agent/lib/local-pipeline', () => ({ runLocalPipeline: vi.fn() }));
const agentModeMock = vi.hoisted(() => ({ mode: 'driver', available: false }));
vi.mock('@/app/api/agent/lib/agent-mode', () => ({
  resolveAgentMode: () => agentModeMock.mode,
  isOrchestratorAvailable: () => agentModeMock.available,
}));
const runRepo = vi.hoisted(() => ({ createRun: vi.fn(), RunAlreadyActiveError: class extends Error {} }));
vi.mock('@/app/api/agent/lib/run-repository', () => runRepo);
const queueMock = vi.hoisted(() => ({ enqueuePipelineRun: vi.fn(async () => {}), close: vi.fn(async () => {}) }));
vi.mock('@cirqix/agents', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@cirqix/agents')>();
  return {
    ...actual,
    createPipelineQueue: () => ({ close: queueMock.close }),
    enqueuePipelineRun: queueMock.enqueuePipelineRun,
  };
});

import { POST } from '@/app/api/agent/route';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
function makeClient() {
  return {
    auth: { getUser: async () => ({ data: { user: { id: 'u1' } } }) },
    from: (table: string) => ({
      select: () => ({
        eq: () => ({
          single: async () => ({
            data: table === 'projects'
              ? { id: PROJECT_ID, status: 'INITIAL', iteration_count: 0, pcb_state: null }
              : { balance: 100, plan: 'pro' },
            error: null,
          }),
        }),
      }),
    }),
  };
}
const makeRequest = () => ({ json: async () => ({ projectId: PROJECT_ID, prompt: 'un thermometre I2C' }) }) as never;

beforeEach(() => {
  vi.clearAllMocks();
  agentModeMock.mode = 'driver';
  supabaseMock.createRouteHandlerClient.mockResolvedValue(makeClient());
  runRepo.createRun.mockResolvedValue('run-driver-1');
  process.env['CIRQIX_ASYNC_PIPELINE'] = '1';
  process.env['REDIS_URL'] = 'redis://127.0.0.1:6379';
});
afterEach(() => {
  delete process.env['CIRQIX_ASYNC_PIPELINE'];
  delete process.env['REDIS_URL'];
});

describe('POST /api/agent — mode driver', () => {
  it('enfile un run de provenance driver, sans retenue, et répond 202', async () => {
    const res = await POST(makeRequest());
    expect(res.status).toBe(202);
    const corps = (await res.json()) as { runId: string; agentMode: string };
    expect(corps.runId).toBe('run-driver-1');
    expect(corps.agentMode).toBe('driver');
    expect(runRepo.createRun).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ agentMode: 'driver', reservationId: null }));
    expect(queueMock.enqueuePipelineRun).toHaveBeenCalledWith(expect.anything(), expect.objectContaining({ runId: 'run-driver-1', prompt: 'un thermometre I2C' }));
    expect(reserveMock).not.toHaveBeenCalled();
    expect(runSimulatorAgentMock).not.toHaveBeenCalled();
    expect(runRealOrchestratorMock).not.toHaveBeenCalled();
  });

  it('sans file, répond 503 et ne lance ni simulateur ni orchestrateur', async () => {
    delete process.env['CIRQIX_ASYNC_PIPELINE'];
    const res = await POST(makeRequest());
    expect(res.status).toBe(503);
    expect(runRepo.createRun).not.toHaveBeenCalled();
    expect(runSimulatorAgentMock).not.toHaveBeenCalled();
    expect(runRealOrchestratorMock).not.toHaveBeenCalled();
  });

  it('un run déjà actif sur le projet répond 409', async () => {
    runRepo.createRun.mockRejectedValue(new runRepo.RunAlreadyActiveError('actif'));
    const res = await POST(makeRequest());
    expect(res.status).toBe(409);
  });
});
