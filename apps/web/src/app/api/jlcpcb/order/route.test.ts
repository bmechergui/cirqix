import { describe, expect, it } from 'vitest';
import { hasOfficialDrc } from './route';

describe('manufacturing gate', () => {
  it('rejects a status-only DRC claim', () => {
    expect(hasOfficialDrc({})).toBe(false);
    expect(hasOfficialDrc({ drc_clean: true, drc_validation: 'simulated' })).toBe(false);
    expect(hasOfficialDrc({ drc_clean: true, drc_skipped: true, drc_validation: 'kicad-cli' })).toBe(false);
  });

  it('accepts only official, non-skipped KiCad evidence', () => {
    expect(hasOfficialDrc({
      drc_clean: true,
      drc_skipped: false,
      drc_validation: 'kicad-cli',
    })).toBe(true);
  });
});
