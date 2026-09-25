---
name: cirqix-drc
description: This skill should be used when the user asks to "lancer le DRC", "vérifier les règles PCB", "corriger les violations DRC", "implémenter la boucle DRC", "afficher les erreurs DRC dans le viewer" or mentions DRC, violations, clearance, track width, règles PCB.
version: 0.1.0
---

# Cirqix — Agent DRC (Design Rule Check)

## Chaîne DRC réelle

`handleDrc` (`packages/agents/src/tools/handlers/drc.ts`) → `POST /drc/auto` (`services/kicad/routers/drc.py`) : pré-filtre kicad-tools, puis `kicad-cli pcb drc` qui fait foi, auto-correction au plus 3 fois dans le service. Verdict : `est_bloquante` (`services/kicad/tools/drc.py`). Fail-closed : service injoignable, `skipped` ou board absent → `status: 'error'`, jamais `DRC_CLEAN`. Aucun modèle dans cette étape.

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

## Violations et règles

Violations affichées par `apps/web/src/widgets/viewer/ui/DrcView.tsx`. Règles : profil fabricant kicad-tools (`services/kicad/tools/drc.py`) et `_REGLES_FINE_PITCH` (`services/kicad/routers/routing.py`) ; ne pas les recopier.
