---
name: cirqix-pcb-agent
description: This skill should be used when the user asks to "implémenter la boucle agentique PCB", "orchestrer les agents Claude", "configurer le streaming SSE", "créer l'orchestrateur", "gérer les états du PCB" or mentions boucle agentique, orchestrateur, Sonnet/Haiku agents, SSE, Redis, machine d'états PCB.
version: 0.1.0
---

# Cirqix — Boucle Agentique PCB

## Machine d'états
```
INITIAL → SCHEMA_READY → PLACEMENT_READY → ROUTAGE_READY → DRC_CLEAN → BOM_READY → EXPORT_READY → COMMANDE_CONFIRMEE
                                                                ↑ correction auto max 3×
ERROR_BLOCKER (max 15 itérations)
```

## Règles impératives
- Max **15 itérations** globales — compter à chaque tour
- **JAMAIS** de commande JLCPCB sans "OUI JE CONFIRME" explicite
- Footprint manquant → appeler `call_agent_footprint` immédiatement, interrompre le flux
- Compression contexte : après 10 tours → Haiku résume les anciens messages (-60% coûts)
- Moteur : **Circuit-Synth** (Python → .kicad_sch + .kicad_pcb natifs) | fallback → KiCad + Freerouting
- Viewer : **KiCanvas** charge les fichiers KiCad depuis Supabase Storage (signed URL)

## Orchestrateur (Sonnet 4.6)

```typescript
// packages/agents/src/orchestrator.ts
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

export async function runPCBAgent(
  userMessage: string,
  projectId: string,
  userId: string,
  onStream: (chunk: string) => void
) {
  await checkCredits(userId, "schema");

  const state = await getProjectState(projectId) ?? {
    status: "INITIAL", iterationCount: 0, messages: [], pcbState: null,
  };

  state.messages.push({ role: "user", content: userMessage });

  while (state.iterationCount < 15) {
    if (state.iterationCount === 10) {
      state.messages = await compressContext(state.messages);
    }

    const response = await client.messages.create({
      model: "claude-sonnet-4-6",
      max_tokens: 4096,
      system: ORCHESTRATOR_SYSTEM_PROMPT, // voir docs/agentdescription.md §1
      tools: PCB_TOOLS,
      messages: state.messages,
      stream: true,
    });

    for await (const chunk of response) {
      if (chunk.type === "content_block_delta" && chunk.delta.type === "text_delta") {
        onStream(chunk.delta.text);
      }
    }

    const final = await response.finalMessage();
    state.messages.push({ role: "assistant", content: final.content });
    state.iterationCount++;

    if (final.stop_reason === "end_turn") break;
    if (final.stop_reason === "tool_use") {
      const toolResults = await executePCBTools(final.content, projectId, userId);
      state.messages.push({ role: "user", content: toolResults });
      state.status = extractStatus(toolResults);
    }

    await saveProjectState(projectId, state);
  }
}
```

## Compression contexte (Haiku)

```typescript
async function compressContext(messages: Anthropic.MessageParam[]) {
  const summary = await client.messages.create({
    model: "claude-haiku-4-5-20251001",
    max_tokens: 500,
    messages: [{
      role: "user",
      content: `Résume en 200 mots l'état PCB et décisions prises:\n${JSON.stringify(messages.slice(0, -5))}`
    }]
  });
  const text = (summary.content[0] as Anthropic.TextBlock).text;
  return [
    { role: "user" as const, content: `[RÉSUMÉ]\n${text}` },
    { role: "assistant" as const, content: "Compris, je continue." },
    ...messages.slice(-5)
  ];
}
```

## Endpoint SSE

```typescript
// apps/api/app/api/agent/run/route.ts
export async function POST(req: Request) {
  const { message, projectId } = await req.json();
  const user = await getUser(req);

  const stream = new ReadableStream({
    async start(controller) {
      await runPCBAgent(message, projectId, user.id, (chunk) => {
        controller.enqueue(`data: ${JSON.stringify({ text: chunk })}\n\n`);
      });
      controller.enqueue("data: [DONE]\n\n");
      controller.close();
    }
  });

  return new Response(stream, {
    headers: { "Content-Type": "text/event-stream", "Cache-Control": "no-cache" }
  });
}
```

## Redis — persistance état

```typescript
const KEY = (id: string) => `cirqix:project:${id}:state`;

export const saveProjectState = (id: string, state: PCBState) =>
  redis.setex(KEY(id), 86400, JSON.stringify(state)); // TTL 24h

export const getProjectState = async (id: string): Promise<PCBState | null> => {
  const raw = await redis.get(KEY(id));
  return raw ? JSON.parse(raw) : null;
};
```

## Coûts cibles

| Agent | Modèle | Coût/appel |
|-------|--------|-----------|
| Orchestrateur | Sonnet 4.6 | ~0.04€ |
| Schéma | Haiku 4.5 | ~0.005€ |
| Placement | Haiku 4.5 | ~0.007€ |
| Routage | Haiku 4.5 | ~0.004€ |
| DRC ×3 | Haiku 4.5 | ~0.006€ |
| Export | Haiku 4.5 | ~0.002€ |
| **Total** | | **~0.12€** |
