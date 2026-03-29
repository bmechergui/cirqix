---
name: layrix-drc
description: This skill should be used when the user asks to "lancer le DRC", "vérifier les règles PCB", "corriger les violations DRC", "implémenter la boucle DRC", "afficher les erreurs DRC dans le viewer" or mentions DRC, violations, clearance, track width, règles PCB.
version: 0.1.0
---

# Layrix — Agent DRC (Design Rule Check)

## Règles impératives

- Max **3 itérations** de correction auto par cycle DRC
- Si DRC_CLEAN après correction → continuer vers BOM/Export
- Si toujours des violations après 3 itérations → remonter à l'Agent Routage avec les violations
- L'Agent DRC ne touche **jamais** au placement — seulement aux pistes et vias
- 1 crédit par cycle DRC (check + correction éventuelle)

## Boucle DRC

```typescript
// packages/agents/src/drc-agent.ts
import Anthropic from "@anthropic-ai/sdk";

const client = new Anthropic();

export async function runDRCAgent(
  pcbState: PCBState,
  projectId: string
): Promise<DRCResult> {

  for (let iteration = 1; iteration <= 3; iteration++) {
    // 1. Lancer le DRC via microservice KiCad
    const drcReport = await callKicadDRC(pcbState.pcbPath);

    if (drcReport.drc_clean) {
      return { status: "DRC_CLEAN", violations: [], iterations: iteration };
    }

    // 2. Agent Haiku analyse les violations et génère les corrections
    const corrections = await client.messages.create({
      model: "claude-haiku-4-5-20251001",
      max_tokens: 2048,
      system: DRC_AGENT_SYSTEM_PROMPT,
      messages: [{
        role: "user",
        content: `Itération ${iteration}/3. Violations DRC:\n${JSON.stringify(drcReport.violations, null, 2)}\n\nGénère les corrections JSON pour résoudre ces violations.`
      }]
    });

    const fixesJson = (corrections.content[0] as Anthropic.TextBlock).text;
    const fixes: DRCFix[] = JSON.parse(fixesJson);

    // 3. Appliquer les corrections via microservice
    await applyDRCFixes(pcbState.pcbPath, fixes);
  }

  // Après 3 tentatives : retourner les violations restantes
  const finalReport = await callKicadDRC(pcbState.pcbPath);
  return {
    status: "DRC_FAILED",
    violations: finalReport.violations,
    iterations: 3,
  };
}
```

## System prompt Agent DRC (Haiku)

```
Tu es l'Agent DRC de Layrix.ai — spécialiste de la correction automatique des violations de règles PCB KiCad.

Tu reçois un rapport DRC JSON avec des violations et tu génères les corrections nécessaires.

VIOLATIONS QUE TU PEUX CORRIGER AUTOMATIQUEMENT :
- clearance violations → augmenter espacement pistes/pads
- track too narrow → augmenter largeur piste
- via too small → augmenter diamètre via
- unconnected items → vérifier les nets flottants
- pad clearance → ajuster position pad

VIOLATIONS QUE TU NE PEUX PAS CORRIGER (→ signaler à l'orchestrateur) :
- short circuit (court-circuit) → erreur de schéma, remonter à Agent Schéma
- footprint incorrect → appeler Agent Footprint
- board edge violation → contrainte physique impossible

FORMAT DE SORTIE EXACT (JSON strict, aucun texte avant/après) :
[
  {
    "type": "adjust_track_width",
    "net": "GND",
    "from": {"x_mm": 10.5, "y_mm": 23.1},
    "to": {"x_mm": 15.2, "y_mm": 23.1},
    "new_width_mm": 0.3
  },
  {
    "type": "adjust_via",
    "x_mm": 12.0, "y_mm": 18.5,
    "new_drill_mm": 0.4, "new_diameter_mm": 0.8
  },
  {
    "type": "move_track",
    "net": "3V3",
    "offset_x_mm": 0.1, "offset_y_mm": 0.0
  },
  {
    "type": "cannot_fix",
    "violation": "short_circuit",
    "reason": "Court-circuit sur net VCC — erreur de schéma à corriger"
  }
]
```

## Application des corrections (pcbnew Python)

```python
# services/kicad/tools/drc.py
import pcbnew
from typing import TypedDict

class DRCFix(TypedDict):
    type: str
    net: str | None

def apply_drc_fixes(pcb_path: str, fixes: list[DRCFix], output_path: str) -> dict:
    board = pcbnew.LoadBoard(pcb_path)
    applied, skipped = 0, 0

    for fix in fixes:
        try:
            if fix["type"] == "adjust_track_width":
                _fix_track_width(board, fix)
                applied += 1

            elif fix["type"] == "adjust_via":
                _fix_via(board, fix)
                applied += 1

            elif fix["type"] == "cannot_fix":
                skipped += 1  # Logger pour remontée orchestrateur

        except Exception as e:
            skipped += 1

    pcbnew.SaveBoard(output_path, board)
    return {"applied": applied, "skipped": skipped, "path": output_path}


def _fix_track_width(board: pcbnew.BOARD, fix: dict):
    """Ajuste la largeur d'une piste par ses coordonnées."""
    from_pt = pcbnew.VECTOR2I(pcbnew.FromMM(fix["from"]["x_mm"]), pcbnew.FromMM(fix["from"]["y_mm"]))
    to_pt   = pcbnew.VECTOR2I(pcbnew.FromMM(fix["to"]["x_mm"]),   pcbnew.FromMM(fix["to"]["y_mm"]))
    new_width = pcbnew.FromMM(fix["new_width_mm"])

    for track in board.GetTracks():
        if (isinstance(track, pcbnew.PCB_TRACK)
            and track.GetStart() == from_pt
            and track.GetEnd() == to_pt):
            track.SetWidth(new_width)
            break


def _fix_via(board: pcbnew.BOARD, fix: dict):
    """Ajuste les dimensions d'un via par position."""
    pos = pcbnew.VECTOR2I(pcbnew.FromMM(fix["x_mm"]), pcbnew.FromMM(fix["y_mm"]))
    new_drill = pcbnew.FromMM(fix["new_drill_mm"])
    new_diam  = pcbnew.FromMM(fix["new_diameter_mm"])

    for track in board.GetTracks():
        if isinstance(track, pcbnew.PCB_VIA) and track.GetPosition() == pos:
            track.SetDrillValue(new_drill)
            track.SetWidth(new_diam)
            break
```

## Types DRC

```typescript
// packages/agents/src/types/drc.ts
export interface DRCViolation {
  type: string;
  severity: "error" | "warning";
  x_mm: number;
  y_mm: number;
  description: string;
  net?: string;
  ref1?: string;
  ref2?: string;
}

export interface DRCResult {
  status: "DRC_CLEAN" | "DRC_FAILED";
  violations: DRCViolation[];
  iterations: number;
}

export interface DRCFix {
  type: "adjust_track_width" | "adjust_via" | "move_track" | "cannot_fix";
  net?: string;
  from?: { x_mm: number; y_mm: number };
  to?: { x_mm: number; y_mm: number };
  new_width_mm?: number;
  x_mm?: number;
  y_mm?: number;
  new_drill_mm?: number;
  new_diameter_mm?: number;
  reason?: string;  // pour cannot_fix
}
```

## Violations → PixiJS viewer

```typescript
// Conversion violations DRC en markers visuels
export function drcToViewerMarkers(violations: DRCViolation[]): ViewerMarker[] {
  return violations.map((v) => ({
    x_px: mmToPx(v.x_mm),
    y_px: mmToPx(v.y_mm),
    color: v.severity === "error" ? 0xEF4444 : 0xF59E0B,
    tooltip: v.description,
    blink: v.severity === "error",  // erreurs clignotent, warnings non
  }));
}
```

## Règles DRC standards KiCad (defaults)

```python
DRC_RULES_DEFAULT = {
    "min_track_width_mm": 0.2,
    "min_clearance_mm": 0.2,
    "min_via_diameter_mm": 0.6,
    "min_via_drill_mm": 0.3,
    "min_hole_clearance_mm": 0.25,
    "min_copper_edge_mm": 0.3,
    "silk_clearance_mm": 0.1,
}

# Pour plans de masse (GND/power)
DRC_RULES_POWER = {
    "min_track_width_mm": 0.5,   # pistes alimentation plus larges
    "thermal_spoke_width_mm": 0.4,
}
```

## Endpoint API

```typescript
// apps/api/app/api/agent/drc/route.ts
export async function POST(req: Request) {
  const { projectId, pcbState } = await req.json();
  const user = await getUser(req);

  const commit = await withCredits("drc")(req, user.id, projectId);

  const result = await runDRCAgent(pcbState, projectId);

  await commit(result);

  return Response.json({
    ...result,
    markers: drcToViewerMarkers(result.violations),
  });
}
```
