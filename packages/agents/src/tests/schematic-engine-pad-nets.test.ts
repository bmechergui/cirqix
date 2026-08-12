import { describe, it, expect } from 'vitest';
import { runCircuitSynthEngine } from '../engines/schematic-engine';

/**
 * Les pads doivent porter leur net (audit du 2026-08-12).
 *
 * Le générateur TypeScript de repli déclarait les nets en tête de fichier et
 * dessinait les pistes, mais émettait les pads SANS `(net …)`. Or c'est
 * l'attribution des PADS qui fait la netlist : un net avec moins de deux pads
 * n'est pas un problème de routage.
 *
 * Conséquence en chaîne : le service comptait ZÉRO net routable, traitait ce
 * dénominateur nul comme 100 %, et un board sans la moindre connexion
 * électrique était annoncé « routé à 100 % ». Cela désarme d'un coup
 * `shouldRescueRouting` ET `shouldRetryPlacement`, laisse Sonnet enchaîner sur
 * le DRC — propre, puisqu'il n'y a aucune règle à violer sans netlist — puis
 * sur l'export. Un board vide, validé, commandable.
 */

const SCHEMA = {
  components: [
    { ref: 'R1', value: '10k', footprint: 'R_0402_1005Metric' },
    { ref: 'C1', value: '100n', footprint: 'C_0402_1005Metric' },
  ],
  connections: [
    { name: 'VCC', pins: [{ ref: 'R1', pin: '1' }, { ref: 'C1', pin: '1' }] },
    { name: 'GND', pins: [{ ref: 'R1', pin: '2' }, { ref: 'C1', pin: '2' }] },
  ],
} as never;

function padLines(pcb: string): string[] {
  return pcb.split('\n').filter((l) => l.trim().startsWith('(pad '));
}

describe('générateur de repli — attribution des nets aux pads', () => {
  it('émet des pads porteurs de (net …)', async () => {
    const out = await runCircuitSynthEngine(SCHEMA);
    const pcb = out.kicad_pcb_content ?? '';

    const pads = padLines(pcb);
    expect(pads.length).toBeGreaterThan(0);
    expect(pads.filter((l) => l.includes('(net '))).not.toHaveLength(0);
  });

  it('produit au moins un net RÉELLEMENT routable (≥2 pads)', async () => {
    // C'est le seul critère qui compte pour le routeur : un net déclaré mais
    // porté par zéro pad ne compte pas. `_count_routable_nets` exige au moins
    // 3 occurrences — 1 déclaration + 2 pads.
    const out = await runCircuitSynthEngine(SCHEMA);
    const pcb = out.kicad_pcb_content ?? '';

    const occurrences = new Map<string, number>();
    for (const m of pcb.matchAll(/\(net (\d+) "/g)) {
      occurrences.set(m[1]!, (occurrences.get(m[1]!) ?? 0) + 1);
    }
    const routable = [...occurrences.values()].filter((n) => n >= 3);

    expect(routable.length).toBeGreaterThan(0);
  });

  it("n'invente pas de net sur une broche non connectée", async () => {
    // Un pad sans net doit rester sans `(net …)`. Lui en attribuer un créerait
    // une connexion qui n'existe pas dans le schéma.
    const orphan = {
      components: [{ ref: 'J1', value: 'Conn', footprint: 'PinHeader_1x04' }],
      connections: [],
    } as never;

    const out = await runCircuitSynthEngine(orphan);
    const pcb = out.kicad_pcb_content ?? '';

    expect(padLines(pcb).filter((l) => l.includes('(net '))).toHaveLength(0);
  });
});
