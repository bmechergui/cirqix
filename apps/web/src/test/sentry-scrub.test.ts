import { describe, it, expect } from 'vitest';
import {
  scrubEvent,
  scrubValue,
  REDACTED,
  MAX_STRING_LENGTH,
} from '@/shared/lib/sentry-scrub';

/**
 * Ce qui ne doit JAMAIS partir chez un tiers.
 *
 * Sentry reçoit ce qu'on lui donne. Le pipeline Cirqix manipule la propriété
 * intellectuelle du client — le prompt décrit souvent le produit lui-même, le
 * schéma et le board SONT le produit. Une erreur de routage ne doit pas
 * l'exfiltrer.
 *
 * Le risque particulier de cette classe de défaut : elle ne casse rien. Tout
 * continue de fonctionner pendant que les circuits partent. Rien ne le
 * signalerait — d'où ces tests.
 */

describe('scrubValue — expurgation par nom de champ', () => {
  it.each([
    'prompt',
    'kicad_sch_content',
    'kicad_pcb_content',
    'gerber_zip_b64',
    'bom_csv',
    'schema',
    'simulation_data',
  ])('expurge %s', (key) => {
    const out = scrubValue({ [key]: 'contenu confidentiel' }) as Record<string, unknown>;

    expect(out[key]).toBe(REDACTED);
  });

  it.each(['authorization', 'cookie', 'anthropic_api_key', 'user_sig'])(
    'expurge le secret %s',
    (key) => {
      const out = scrubValue({ [key]: 'valeur' }) as Record<string, unknown>;

      expect(out[key]).toBe(REDACTED);
    },
  );

  it('est insensible à la casse du nom de champ', () => {
    const out = scrubValue({ Authorization: 'Bearer x', PROMPT: 'secret' }) as Record<
      string,
      unknown
    >;

    expect(out['Authorization']).toBe(REDACTED);
    expect(out['PROMPT']).toBe(REDACTED);
  });

  it('atteint les champs imbriqués', () => {
    const out = scrubValue({
      contexts: { pipeline: { step: 'routing', kicad_pcb_content: '(kicad_pcb …)' } },
    }) as Record<string, Record<string, Record<string, unknown>>>;

    expect(out['contexts']!['pipeline']!['kicad_pcb_content']).toBe(REDACTED);
    expect(out['contexts']!['pipeline']!['step']).toBe('routing');
  });

  it('traverse les tableaux', () => {
    const out = scrubValue([{ prompt: 'x' }, { step: 'drc' }]) as Array<Record<string, unknown>>;

    expect(out[0]!['prompt']).toBe(REDACTED);
    expect(out[1]!['step']).toBe('drc');
  });
});

describe('scrubValue — seconde barrière, par taille', () => {
  it("tronque une chaîne longue même si son nom est inconnu", () => {
    // LA barrière qui compte sur la durée : la liste de noms est aveugle à ce
    // qui n'existe pas encore. Un champ ajouté dans six mois passerait — sa
    // taille, non.
    const blob = 'A'.repeat(50_000);

    const out = scrubValue({ champ_invente_plus_tard: blob }) as Record<string, string>;

    expect(out['champ_invente_plus_tard']!.length).toBeLessThan(700);
    expect(out['champ_invente_plus_tard']).toContain('tronqué');
    expect(out['champ_invente_plus_tard']).toContain('50000');
  });

  it('laisse intact un message d’erreur normal', () => {
    const msg = 'ECONNREFUSED: le service KiCad est injoignable sur le port 8000';

    const out = scrubValue({ message: msg }) as Record<string, string>;

    expect(out['message']).toBe(msg);
  });

  it('ne tronque pas juste sous le seuil', () => {
    const juste = 'B'.repeat(MAX_STRING_LENGTH);

    const out = scrubValue({ m: juste }) as Record<string, string>;

    expect(out['m']).toBe(juste);
  });

  it('résiste à une structure profonde sans exploser', () => {
    let deep: Record<string, unknown> = { prompt: 'secret' };
    for (let i = 0; i < 50; i++) deep = { nested: deep };

    expect(() => scrubValue(deep)).not.toThrow();
  });
});

describe('scrubValue — immuabilité', () => {
  it("ne modifie jamais l'objet source", () => {
    // L'application continue d'utiliser cet objet après l'envoi : le muter
    // corromprait son état pour une raison sans rapport.
    const source = { prompt: 'un régulateur 3V3', step: 'schema' };

    scrubValue(source);

    expect(source.prompt).toBe('un régulateur 3V3');
  });
});

describe('scrubEvent — dernière barrière avant l’envoi', () => {
  it('supprime en bloc les en-têtes et cookies de requête', () => {
    // Ils ne portent rien qu'une alerte exige, et tout ce qu'un jeton
    // d'authentification ne doit pas quitter.
    const event = {
      request: {
        url: 'https://cirqix.ai/api/agent',
        headers: { authorization: 'Bearer secret', 'user-agent': 'x' },
        cookies: 'sb-access-token=…',
        data: { projectId: 'p1' },
      },
    };

    const out = scrubEvent(event);

    expect(out.request).not.toHaveProperty('headers');
    expect(out.request).not.toHaveProperty('cookies');
    expect((out.request as Record<string, unknown>)['url']).toBe('https://cirqix.ai/api/agent');
  });

  it('conserve ce qui rend une alerte exploitable', () => {
    const event = {
      extra: {
        projectId: '11111111-1111-4111-8111-111111111111',
        userId: 'u-42',
        step: 'ROUTING',
        sqlstate: '22023',
        prompt: 'mon circuit secret',
      },
    };

    const out = scrubEvent(event);
    const extra = out.extra as Record<string, unknown>;

    expect(extra['projectId']).toBe('11111111-1111-4111-8111-111111111111');
    expect(extra['step']).toBe('ROUTING');
    expect(extra['sqlstate']).toBe('22023');
    expect(extra['prompt']).toBe(REDACTED);
  });

  it("n'échoue pas sur un événement sans requête ni extra", () => {
    expect(() => scrubEvent({})).not.toThrow();
  });
});
