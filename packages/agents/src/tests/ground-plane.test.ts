import { describe, it, expect } from 'vitest';
import { addGroundPlane } from '../tools/pcb-helpers';

/**
 * Le plan de masse disparaissait silencieusement sur toute carte routée par
 * Freerouting.
 *
 * `addGroundPlane` cherchait le net par `\(net (\d+) "GND"\)` — la forme
 * NUMÉROTÉE. Or le board qui sort du routage Freerouting est passé par pcbnew
 * (round-trip Specctra), donc il est écrit au format KiCad 10 : `(net "GND")`,
 * sans numéro. Le `match` rendait `null`, la fonction retournait le contenu
 * inchangé, et personne n'était averti.
 *
 * Mesuré le 2026-08-21 sur les boards réels du board STM32 :
 *
 *     board placé (entrée) : (net N "GND") présent  -> plan ajouté
 *     sortie Freerouting   : ABSENT, seulement (net "GND")  -> RIEN
 *     sortie kicad-tools   : présent  -> plan ajouté
 *
 * ⚠️ L'ironie est dans le commentaire de la fonction : « Guarantees GND
 * connectivity even when Freerouting fails to route the GND net ». C'est
 * précisément sur la sortie de Freerouting qu'elle ne faisait rien.
 *
 * Le défaut ne se voyait pas avant le 2026-08-21 : Freerouting n'était jamais
 * atteint (sonde sur un préfixe d'URL inexistant). Réparer un chemin mort en
 * révèle les usagers.
 *
 * Même famille que l'aveuglement du compteur de nets côté Python, corrigé le
 * même jour : deux écritures pour la même information, une seule reconnue.
 */

const PCB_NUMEROTE = `(kicad_pcb
\t(version 20240108)
\t(net 0 "")
\t(net 1 "GND")
\t(net 2 "VCC")
)`;

const PCB_NOMME = `(kicad_pcb
\t(version 20260206)
\t(generator "pcbnew")
\t(generator_version "10.0")
\t(footprint "R_0805" (at 10 10)
\t\t(pad "1" smd rect (at 0 0) (size 1 1) (layers "F.Cu") (net "GND"))
\t)
)`;

describe('plan de masse', () => {
  it('ajoute la zone sur un board au format numéroté', () => {
    const out = addGroundPlane(PCB_NUMEROTE, 50, 40);
    expect(out).toContain('(zone');
    expect(out).toContain('(net_name "GND")');
    expect(out).toContain('(layer "B.Cu")');
  });

  it('ajoute la zone sur un board écrit par KiCad 10', () => {
    // LE défaut : cette forme ne matchait pas, et la fonction rendait le
    // contenu inchangé sans rien dire.
    const out = addGroundPlane(PCB_NOMME, 50, 40);
    expect(out).toContain('(zone');
    expect(out).toContain('(net_name "GND")');
  });

  it('couvre la surface demandée', () => {
    const out = addGroundPlane(PCB_NOMME, 60, 45);
    expect(out).toContain('(xy 60 0)');
    expect(out).toContain('(xy 60 45)');
  });

  it('ne touche pas un board sans net GND', () => {
    // Sans masse, il n'y a rien à relier : ne pas inventer une zone.
    const sansGnd = '(kicad_pcb\n\t(net 1 "VCC")\n)';
    expect(addGroundPlane(sansGnd, 50, 40)).toBe(sansGnd);
  });

  it('n ajoute pas un second plan si la carte en a déjà un', () => {
    // Le routeur peut avoir coulé lui-même les zones power (`kct route` le
    // fait). Empiler une seconde zone GND sur B.Cu créerait deux remplissages
    // concurrents sur la même couche.
    const avecZone = `${PCB_NOMME.slice(0, -1)}\t(zone (net_name "GND") (layer "B.Cu"))\n)`;
    expect(addGroundPlane(avecZone, 50, 40)).toBe(avecZone);
  });
});
