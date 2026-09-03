import { describe, it, expect } from 'vitest';
import {
  shouldRescueRouting,
  shouldRetryPlacement,
  shouldRetryForDrc,
} from '../orchestrator';

/**
 * L'annulation doit ARRÊTER le pipeline, pas seulement l'empêcher de finir.
 *
 * Sans plafond de durée, l'arrêt anticipé n'est plus une constante écrite
 * d'avance : c'est une décision de l'utilisateur. Or les trois mécanismes
 * déterministes de l'orchestrateur sont précisément ceux qui RELANCENT du
 * travail lourd quand le résultat n'est pas parfait :
 *
 *   - `shouldRescueRouting`  → lance le reasoner (appels LLM + service KiCad) ;
 *   - `shouldRetryPlacement` → re-tire un placement PUIS re-route
 *                              (≈ 17 min par tentative, mesuré) ;
 *   - `shouldRetryForDrc`    → idem, piloté par le DRC.
 *
 * Enchaîner l'un d'eux après une annulation reviendrait à ignorer la décision de
 * l'utilisateur et à continuer de consommer crédits et CPU — le contraire exact
 * de ce qu'il a demandé. Un utilisateur qui annule à 91 % ne veut pas qu'on
 * relance 17 minutes de travail « pour essayer d'atteindre 100 % ».
 *
 * Distinction importante, et c'est tout l'objet de ces tests : un routage
 * INTERROMPU n'est pas un routage INCOMPLET. Le second mérite un sauvetage, le
 * premier non.
 */

const incomplet = { routed_percent: 91 };

describe('routage incomplet — comportement inchangé', () => {
  it('déclenche le reasoner quand le routage a fini sans atteindre 100 %', () => {
    expect(shouldRescueRouting(incomplet)).toBe(true);
  });

  it('re-tire un placement tant que le budget de tentatives le permet', () => {
    expect(shouldRetryPlacement(incomplet, 1, 3)).toBe(true);
  });

  it('re-tire un placement quand le DRC refuse le board', () => {
    expect(shouldRetryForDrc({ drcViolations: [{}, {}] }, 1, 3)).toBe(true);
  });
});

describe('run annulé — plus aucun travail lourd ne démarre', () => {
  it('ne lance pas le reasoner', () => {
    expect(shouldRescueRouting(incomplet, { cancelled: true })).toBe(false);
  });

  it('ne re-tire pas de placement', () => {
    expect(shouldRetryPlacement(incomplet, 1, 3, { cancelled: true })).toBe(false);
  });

  it('ne re-tire pas de placement sur refus DRC', () => {
    expect(shouldRetryForDrc({ drcViolations: [{}, {}] }, 1, 3, { cancelled: true })).toBe(false);
  });
});

describe('l annulation ne masque pas les autres refus', () => {
  it('un routage à 100 % ne déclenche rien, annulé ou non', () => {
    expect(shouldRescueRouting({ routed_percent: 100 })).toBe(false);
    expect(shouldRescueRouting({ routed_percent: 100 }, { cancelled: true })).toBe(false);
  });

  it('un routage en erreur ne déclenche toujours rien — pas de routed_percent', () => {
    // Garde fail-fast existante : un service injoignable ne doit pas être
    // confondu avec un routage incomplet.
    expect(shouldRescueRouting({ status: 'error' })).toBe(false);
  });

  it('le budget de tentatives épuisé reste refusé', () => {
    expect(shouldRetryPlacement(incomplet, 3, 3)).toBe(false);
  });
});
