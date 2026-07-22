import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  cache: new Map(),
  runRealDrc: vi.fn(),
}));

const cache = mocks.cache as Map<string, {
  schema: { components: []; nets: [] };
  boardW: number;
  boardH: number;
  kicad_pcb_content?: string;
}>;
const runRealDrc = mocks.runRealDrc;

vi.mock('../tools/shared', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../tools/shared')>();
  return {
    ...actual,
    log: { warn: vi.fn() },
    pcbStateCache: mocks.cache,
  };
});

vi.mock('../engines/drc-service', () => ({
  DrcServiceUnavailableError: class DrcServiceUnavailableError extends Error {},
  runRealDrc: mocks.runRealDrc,
}));

vi.mock('../engines/export-service', () => ({
  ExportServiceUnavailableError: class ExportServiceUnavailableError extends Error {},
  runRealExport: vi.fn(),
}));

import { handleDrc } from '../tools/handlers/drc';
import { handleExport } from '../tools/handlers/export';
import { invalidateDrcCertification } from '../tools/shared';

describe('DRC certification gate', () => {
  beforeEach(() => {
    cache.clear();
    runRealDrc.mockReset();
  });

  it('does not certify a PCB when the service is unavailable', async () => {
    cache.set('project-1', {
      schema: { components: [], nets: [] },
      boardW: 10,
      boardH: 10,
      kicad_pcb_content: '(kicad_pcb)',
    });
    runRealDrc.mockRejectedValue(new Error('service unavailable'));

    const result = await handleDrc({}, 'project-1');

    expect(result).toMatchObject({
      pcb_status: 'ROUTING_DONE',
      drc_clean: false,
      drc_skipped: true,
    });
  });

  it('does not promote a skipped service response to DRC_CLEAN', async () => {
    cache.set('project-1', {
      schema: { components: [], nets: [] },
      boardW: 10,
      boardH: 10,
      kicad_pcb_content: '(kicad_pcb)',
    });
    runRealDrc.mockResolvedValue({
      drcClean: false,
      violations: [],
      fixedCount: 0,
      skipped: true,
      warning: 'kicad-cli unavailable',
    });

    const result = await handleDrc({}, 'project-1');

    expect(result.pcb_status).toBe('ROUTING_DONE');
    expect(result.drc_clean).toBe(false);
  });

  it('blocks export until official, non-skipped DRC evidence exists', async () => {
    cache.set('project-1', {
      schema: { components: [], nets: [] },
      boardW: 10,
      boardH: 10,
      kicad_pcb_content: '(kicad_pcb)',
    });

    const result = await handleExport('project-1');

    expect(result).toMatchObject({
      status: 'error',
      pcb_status: 'ROUTING_DONE',
      engine: 'drc-gate',
    });
  });

  it('invalidates a prior certificate when a PCB is changed', () => {
    const changed = invalidateDrcCertification({
      schema: { components: [], nets: [] },
      boardW: 10,
      boardH: 10,
      kicad_pcb_content: 'old-board',
      drc_clean: true,
      drc_skipped: false,
      drc_validation: 'kicad-cli',
    }, 'new-board');

    expect(changed).toMatchObject({
      kicad_pcb_content: 'new-board',
      drc_clean: false,
      drc_skipped: false,
      drc_validation: 'stale',
    });
  });
});
