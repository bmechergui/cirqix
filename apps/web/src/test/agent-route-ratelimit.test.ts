import { beforeEach, describe, expect, it, vi } from 'vitest';

/**
 * Rate limiting de POST /api/agent (issue #117).
 *
 * La route vérifie `hasEnoughPipelineCredits(balance)` PUIS lance un pipeline
 * qui peut durer 300 s, et le débit n'a lieu qu'à la fin, dans
 * `finalize_pipeline_success`. Entre les deux, rien n'est réservé : trois
 * requêtes lancées ensemble lisent le même solde, passent toutes le contrôle,
 * et consomment Sonnet, le service KiCad et Freerouting — pour un seul débit.
 *
 * Ce n'est pas un vol de crédits (le débit reste exact) mais un épuisement de
 * ressources déclenchable depuis un compte gratuit. Le quota par utilisateur
 * borne le débit d'allumage ; il ne remplace pas une réservation durable, et
 * l'issue reste ouverte pour ça.
 */

const supabaseMock = vi.hoisted(() => ({
  createRouteHandlerClient: vi.fn(),
  createAdminClient: vi.fn(() => ({})),
}));
vi.mock('@/shared/lib/supabase-server', () => supabaseMock);

const checkRateLimitMock = vi.hoisted(() => vi.fn());
vi.mock('@/shared/lib/ratelimit', () => ({ checkRateLimit: checkRateLimitMock }));

// Le pipeline lui-même n'est pas le sujet : on veut seulement savoir s'il est
// atteint ou non.
const runSimulatorAgentMock = vi.hoisted(() => vi.fn(async () => {}));
vi.mock('@/app/api/agent/lib/simulator', () => ({ runSimulatorAgent: runSimulatorAgentMock }));
vi.mock('@/app/api/agent/lib/orchestrator-bridge', () => ({ runRealOrchestrator: vi.fn() }));
vi.mock('@/app/api/agent/lib/local-pipeline', () => ({ runLocalPipeline: vi.fn() }));
vi.mock('@/app/api/agent/lib/agent-mode', () => ({
  resolveAgentMode: () => 'simulator',
  isOrchestratorAvailable: () => false,
}));

// `maxDuration` est un export de configuration reconnu par Next.js : on lit la
// vraie valeur de la route, pas une copie qui pourrait diverger.
import { POST, maxDuration } from '@/app/api/agent/route';
// Next.js valide les exports d'un `route.ts` et rejette ceux qu'il ne connaît
// pas : les constantes vivent dans lib/, pas dans le fichier de route.
import {
  AGENT_RATE_LIMIT,
  AGENT_RATE_WINDOW_S,
  worstCaseConcurrentPipelines,
} from '@/app/api/agent/lib/rate-limit';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';

/** Trace chaque table interrogée, pour prouver qu'un 429 n'atteint pas la base. */
function makeClient(userId: string | null) {
  const tables: string[] = [];
  const client = {
    auth: {
      getUser: async () => ({ data: { user: userId ? { id: userId } : null } }),
    },
    from: (table: string) => {
      tables.push(table);
      const row =
        table === 'projects'
          ? { id: PROJECT_ID, status: 'INITIAL', iteration_count: 0, pcb_state: null }
          : { balance: 100, plan: 'pro' };
      return {
        select: () => ({ eq: () => ({ single: async () => ({ data: row, error: null }) }) }),
      };
    },
  };
  return { client, tables };
}

function makeRequest(body: unknown = { projectId: PROJECT_ID, prompt: 'un régulateur 3V3' }) {
  return { json: async () => body } as never;
}

beforeEach(() => {
  vi.clearAllMocks();
  checkRateLimitMock.mockResolvedValue({ success: true, remaining: 2 });
});

describe('POST /api/agent — quota par utilisateur', () => {
  it('renvoie 429 sans interroger projets ni crédits quand le quota est dépassé', async () => {
    const { client, tables } = makeClient('u1');
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    checkRateLimitMock.mockResolvedValue({ success: false, remaining: 0 });

    const res = await POST(makeRequest());

    expect(res.status).toBe(429);
    expect(tables).toEqual([]);
    expect(runSimulatorAgentMock).not.toHaveBeenCalled();
  });

  it('indique au client quand réessayer', async () => {
    const { client } = makeClient('u1');
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);
    checkRateLimitMock.mockResolvedValue({ success: false, remaining: 0 });

    const res = await POST(makeRequest());

    expect(res.headers.get('Retry-After')).toBe(String(AGENT_RATE_WINDOW_S));
  });

  it("compte le quota par utilisateur, jamais par IP", async () => {
    // Une clé IP punirait tout un réseau d'entreprise pour un seul abus, et
    // laisserait passer un abus réparti sur plusieurs adresses.
    const { client } = makeClient('u1');
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);

    await POST(makeRequest());

    expect(checkRateLimitMock).toHaveBeenCalledWith(
      'agent:u1',
      AGENT_RATE_LIMIT,
      AGENT_RATE_WINDOW_S,
    );
  });

  it("ne consomme aucun quota pour une requête non authentifiée", async () => {
    // Le quota est nominatif : sans utilisateur, il n'y a pas de compteur à
    // débiter. L'appeler avant l'auth reviendrait à laisser un anonyme épuiser
    // le quota d'autrui — ou à créer une clé fourre-tout partagée.
    const { client } = makeClient(null);
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);

    const res = await POST(makeRequest());

    expect(res.status).toBe(401);
    expect(checkRateLimitMock).not.toHaveBeenCalled();
  });

  it('laisse passer le pipeline quand le quota le permet', async () => {
    const { client, tables } = makeClient('u1');
    supabaseMock.createRouteHandlerClient.mockResolvedValue(client);

    const res = await POST(makeRequest());

    expect(res.status).toBe(200);
    expect(tables).toContain('credits');
  });

  it('verrouille la borne de simultanéité réellement obtenue, pas celle affichée', () => {
    // Le quota affiche 3, mais `fixedWindow` remet son compteur à zéro chaque
    // minute : sur les 300 s que peut durer un pipeline, un compte traverse
    // 5 fenêtres et en allume 15. La borne réelle est 15, pas 3 — et c'est ce
    // chiffre qui est documenté dans lib/rate-limit.ts.
    //
    // Ce test tient la documentation attachée aux constantes : relever
    // AGENT_RATE_LIMIT, raccourcir la fenêtre ou allonger maxDuration change
    // la borne et fait échouer ici, ce qui force à rouvrir le commentaire
    // plutôt qu'à le laisser mentir.
    expect(maxDuration).toBe(300);
    expect(worstCaseConcurrentPipelines(maxDuration)).toBe(15);
  });
});
