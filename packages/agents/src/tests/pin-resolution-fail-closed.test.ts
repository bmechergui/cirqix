import { describe, it, expect } from 'vitest';
import { runCircuitSynthEngine } from '../engines/schematic-engine';

/**
 * Une broche non résolue ne doit JAMAIS devenir la broche 1 (audit 2026-08-12).
 *
 * `footprintToLibId` envoie tous les boîtiers DIP/SOIC/TSSOP sur `Device:IC`,
 * un libId que `resolvePinIndex` ne connaît pas. Son repli était `return 0` :
 * TOUTE broche nommée d'un CI générique atterrissait donc sur le pad 1.
 *
 * Mesuré sur un LM358 câblé VCC / GND / OUT :
 *
 *     (pad "1" … (net 3 "OUT"))     ← un SEUL pad porte un net
 *
 * VCC et GND sont silencieusement perdus — chaque attribution écrasait la
 * précédente sur le même pad — et OUT se retrouve sur la mauvaise broche. Trois
 * erreurs électriques simultanées, sans aucun signal.
 *
 * Le choix ici est celui de toute la campagne : REFUSER plutôt que fabriquer.
 * Une connexion manquante se voit — le net perd ses pads, devient non routable,
 * et la garde d'entrée de `route_auto` refuse le board avec un message clair.
 * Une connexion FAUSSE ne se voit pas : elle produit un PCB fabricable et
 * erroné.
 */

const LM358 = {
  components: [
    { ref: 'U1', value: 'LM358', footprint: 'SOIC-8_3.9x4.9mm_P1.27mm' },
    { ref: 'R1', value: '10k', footprint: 'R_0402_1005Metric' },
    { ref: 'R2', value: '10k', footprint: 'R_0402_1005Metric' },
    { ref: 'R3', value: '10k', footprint: 'R_0402_1005Metric' },
  ],
  connections: [
    { name: 'VCC', pins: [{ ref: 'U1', pin: 'VCC' }, { ref: 'R1', pin: '1' }] },
    { name: 'GND', pins: [{ ref: 'U1', pin: 'GND' }, { ref: 'R2', pin: '1' }] },
    { name: 'OUT', pins: [{ ref: 'U1', pin: 'OUT' }, { ref: 'R3', pin: '1' }] },
  ],
} as never;

function padsOf(pcb: string, ref: string): string[] {
  const block = pcb.split('(footprint').find((b) => b.includes(`"${ref}"`)) ?? '';
  return block.split('\n').filter((l) => l.trim().startsWith('(pad '));
}

describe('résolution des broches — refuser plutôt que fabriquer', () => {
  it("n'entasse pas plusieurs nets sur la broche 1 d'un CI générique", async () => {
    const out = await runCircuitSynthEngine(LM358);
    const pcb = out.kicad_pcb_content ?? '';

    const pad1 = padsOf(pcb, 'U1').find((l) => l.includes('(pad "1"'));
    // Le pad 1 ne doit pas hériter d'un net qu'il n'a pas : VCC, GND et OUT
    // sont des broches distinctes d'un LM358, aucune n'est la broche 1.
    expect(pad1 ?? '').not.toContain('(net ');
  });

  it('ne fabrique aucune connexion pour une broche nommée non résolue', async () => {
    const out = await runCircuitSynthEngine(LM358);
    const pcb = out.kicad_pcb_content ?? '';

    // Aucun pad de U1 ne doit porter de net : le libId `Device:IC` ne sait pas
    // traduire VCC/GND/OUT en numéros de broche.
    expect(padsOf(pcb, 'U1').filter((l) => l.includes('(net '))).toHaveLength(0);
  });

  it('résout toujours correctement une broche NUMÉROTÉE', async () => {
    // La protection ne doit pas casser le cas nominal : un numéro explicite
    // reste parfaitement résoluble, sur un CI générique comme ailleurs.
    const numbered = {
      components: [
        { ref: 'U1', value: 'LM358', footprint: 'SOIC-8_3.9x4.9mm_P1.27mm' },
        { ref: 'R1', value: '10k', footprint: 'R_0402_1005Metric' },
      ],
      connections: [
        { name: 'SIG', pins: [{ ref: 'U1', pin: '3' }, { ref: 'R1', pin: '1' }] },
      ],
    } as never;

    const out = await runCircuitSynthEngine(numbered);
    const pcb = out.kicad_pcb_content ?? '';

    const pad3 = padsOf(pcb, 'U1').find((l) => l.includes('(pad "3"'));
    expect(pad3 ?? '').toContain('"SIG"');
  });

  it('résout toujours les broches nommées des libId CONNUS', async () => {
    // NE555 a sa table : ne pas la casser en durcissant le repli.
    const ne555 = {
      components: [
        { ref: 'U1', value: 'NE555', footprint: 'DIP-8_W7.62mm' },
        { ref: 'R1', value: '10k', footprint: 'R_0402_1005Metric' },
      ],
      connections: [
        { name: 'OUTPUT', pins: [{ ref: 'U1', pin: 'OUT' }, { ref: 'R1', pin: '1' }] },
      ],
    } as never;

    const out = await runCircuitSynthEngine(ne555);
    const pcb = out.kicad_pcb_content ?? '';

    expect(padsOf(pcb, 'U1').filter((l) => l.includes('"OUTPUT"'))).not.toHaveLength(0);
  });
});
