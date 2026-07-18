import { afterEach, describe, expect, it } from 'vitest';

import {
  KicadServiceAuthConfigError,
  buildKicadServiceHeaders,
} from '../engines/kicad-service-auth';

const managedEnv = [
  'KICAD_SERVICE_TOKEN',
  'ANTHROPIC_API_KEY',
] as const;
const originalEnv = Object.fromEntries(managedEnv.map((name) => [name, process.env[name]]));

afterEach(() => {
  for (const name of managedEnv) {
    const value = originalEnv[name];
    if (value === undefined) delete process.env[name];
    else process.env[name] = value;
  }
});

describe('buildKicadServiceHeaders', () => {
  it('fails closed when the service token is not configured', () => {
    delete process.env['KICAD_SERVICE_TOKEN'];

    expect(() => buildKicadServiceHeaders()).toThrow(KicadServiceAuthConfigError);
  });

  it('fails closed when the service token is blank', () => {
    process.env['KICAD_SERVICE_TOKEN'] = '   ';

    expect(() => buildKicadServiceHeaders()).toThrow('KICAD_SERVICE_TOKEN not configured');
  });

  it('fails closed when the service token is too short', () => {
    process.env['KICAD_SERVICE_TOKEN'] = 'short-token';

    expect(() => buildKicadServiceHeaders()).toThrow('shorter than 32 characters');
  });

  it('returns JSON and Bearer headers without exposing any other environment value', () => {
    process.env['KICAD_SERVICE_TOKEN'] = '  test-service-token-that-is-at-least-32-chars  ';
    process.env['ANTHROPIC_API_KEY'] = 'must-not-leak';

    expect(buildKicadServiceHeaders()).toEqual({
      'Content-Type': 'application/json',
      Authorization: 'Bearer test-service-token-that-is-at-least-32-chars',
    });
  });
});
