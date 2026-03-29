---
name: layrix-kicad-service
description: This skill should be used when the user asks to "implémenter le microservice KiCad", "configurer FastAPI pcbnew", "lancer le routage Freerouting", "exporter les Gerbers", "dockeriser KiCad" or mentions pcbnew, Freerouting, placement, routage, DSN, SES, Gerbers, Docker KiCad.
version: 0.1.0
---

# Layrix — Microservice KiCad (services/kicad/)

## Structure

```
services/kicad/
├── main.py              ← FastAPI app + routes
├── tools/
│   ├── placement.py     ← pcbnew placement composants
│   ├── routing.py       ← Freerouting wrapper (.dsn → .ses)
│   ├── drc.py           ← DRC check + corrections
│   ├── export.py        ← Gerbers + BOM + STEP + drill
│   └── simulation.py    ← ngspice (plan Pro)
├── Dockerfile
├── requirements.txt
└── docker-compose.yml
```

## FastAPI app

```python
# services/kicad/main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from tools.placement import place_components
from tools.routing import route_with_freerouting
from tools.drc import run_drc, apply_drc_fixes
from tools.export import export_gerbers, export_step, export_bom

app = FastAPI(title="Layrix KiCad Service")

class PlacementRequest(BaseModel):
    pcb_path: str
    components: list[dict]  # [{ref, x_mm, y_mm, rotation, side}]
    output_path: str

class RoutingRequest(BaseModel):
    pcb_path: str
    output_path: str
    timeout: int = 300

class DRCRequest(BaseModel):
    pcb_path: str

class DRCFixRequest(BaseModel):
    pcb_path: str
    fixes: list[dict]
    output_path: str

class ExportRequest(BaseModel):
    pcb_path: str
    output_dir: str
    project_id: str

@app.get("/health")
def health(): return {"status": "ok"}

@app.post("/place")
def place(req: PlacementRequest):
    return place_components(req.pcb_path, req.components, req.output_path)

@app.post("/route")
def route(req: RoutingRequest):
    return route_with_freerouting(req.pcb_path, req.output_path, req.timeout)

@app.post("/drc")
def drc(req: DRCRequest):
    return run_drc(req.pcb_path)

@app.post("/drc/fix")
def drc_fix(req: DRCFixRequest):
    return apply_drc_fixes(req.pcb_path, req.fixes, req.output_path)

@app.post("/export/gerbers")
def gerbers(req: ExportRequest):
    return export_gerbers(req.pcb_path, req.output_dir)

@app.post("/export/step")
def step(req: ExportRequest):
    return export_step(req.pcb_path, req.output_dir)

@app.post("/export/bom")
def bom(req: ExportRequest):
    return export_bom(req.pcb_path, req.output_dir)
```

## Placement (pcbnew)

```python
# services/kicad/tools/placement.py
import pcbnew

def place_components(pcb_path: str, components: list[dict], output_path: str) -> dict:
    board = pcbnew.LoadBoard(pcb_path)

    for comp in components:
        fp = board.FindFootprintByReference(comp["ref"])
        if not fp:
            raise ValueError(f"Footprint {comp['ref']} introuvable")

        fp.SetPosition(pcbnew.VECTOR2I(
            pcbnew.FromMM(comp["x_mm"]),
            pcbnew.FromMM(comp["y_mm"])
        ))
        fp.SetOrientationDegrees(comp["rotation"])

        if comp.get("side") == "back":
            fp.Flip(fp.GetPosition(), False)

    pcbnew.SaveBoard(output_path, board)
    return {"status": "ok", "path": output_path, "placed": len(components)}
```

## Routage (Freerouting)

```python
# services/kicad/tools/routing.py
import subprocess, tempfile, pcbnew

def route_with_freerouting(pcb_path: str, output_path: str, timeout: int = 300) -> dict:
    """
    Pipeline : .kicad_pcb → .dsn → Freerouting (Java) → .ses → .kicad_pcb
    Timeouts : 90s (simple) | 300s (4 couches) | 600s (8 couches)
    """
    board = pcbnew.LoadBoard(pcb_path)

    with tempfile.TemporaryDirectory() as tmp:
        dsn = f"{tmp}/board.dsn"
        ses = f"{tmp}/board.ses"

        pcbnew.ExportSpecctraSession(board, dsn)

        result = subprocess.run(
            ["java", "-jar", "/opt/freerouting/freerouting.jar",
             "-de", dsn, "-do", ses, "-mp", "100"],
            capture_output=True, timeout=timeout, text=True
        )

        if result.returncode != 0:
            raise RuntimeError(f"Freerouting: {result.stderr}")

        pcbnew.ImportSpecctraSession(board, ses)
        pcbnew.SaveBoard(output_path, board)

    return {"status": "ok", "path": output_path}
```

## Export Gerbers

```python
# services/kicad/tools/export.py
import pcbnew, zipfile, os

GERBER_LAYERS = {
    "F.Cu": pcbnew.F_Cu, "B.Cu": pcbnew.B_Cu,
    "F.SilkS": pcbnew.F_SilkS, "B.SilkS": pcbnew.B_SilkS,
    "F.Mask": pcbnew.F_Mask, "B.Mask": pcbnew.B_Mask,
    "Edge.Cuts": pcbnew.Edge_Cuts,
}

def export_gerbers(pcb_path: str, output_dir: str) -> dict:
    board = pcbnew.LoadBoard(pcb_path)
    os.makedirs(output_dir, exist_ok=True)

    ctrl = pcbnew.PLOT_CONTROLLER(board)
    opts = ctrl.GetPlotOptions()
    opts.SetOutputDirectory(output_dir)
    opts.SetUseGerberProtelExtensions(True)

    for name, layer_id in GERBER_LAYERS.items():
        ctrl.SetLayer(layer_id)
        ctrl.OpenPlotfile(name, pcbnew.PLOT_FORMAT_GERBER, name)
        ctrl.PlotLayer()
    ctrl.ClosePlot()

    # Drill
    drill = pcbnew.EXCELLON_WRITER(board)
    drill.CreateDrillandMapFilesSet(output_dir, True, False)

    # ZIP
    zip_path = f"{output_dir}/gerbers.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        for f in os.listdir(output_dir):
            if not f.endswith(".zip"):
                zf.write(os.path.join(output_dir, f), f)

    return {"status": "ok", "zip_path": zip_path}
```

## Dockerfile

```dockerfile
FROM kicad/kicad:8.0-ubuntu

RUN apt-get update && apt-get install -y \
    python3-pip openjdk-17-jre curl && \
    pip3 install fastapi uvicorn pydantic

COPY . /app
WORKDIR /app

ADD https://github.com/freerouting/freerouting/releases/latest/download/freerouting.jar \
    /opt/freerouting/freerouting.jar

EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## BullMQ — isolation par job

```typescript
// apps/api/src/workers/kicad-worker.ts
import { Worker, Queue } from "bullmq";
import { redis } from "../lib/redis";

export const kicadQueue = new Queue("kicad-jobs", { connection: redis });

new Worker("kicad-jobs", async (job) => {
  const { type, payload } = job.data;

  const res = await fetch(`${process.env.KICAD_SERVICE_URL}/${type}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!res.ok) throw new Error(`KiCad error: ${await res.text()}`);
  return res.json();
}, { connection: redis, concurrency: 10 });

// Helper pour ajouter un job
export const addKicadJob = (type: string, payload: object) =>
  kicadQueue.add(type, { type, payload }, { attempts: 2, backoff: { type: "exponential", delay: 2000 } });
```

## Endpoints résumé

| Route | Méthode | Description |
|-------|---------|-------------|
| `/health` | GET | Health check |
| `/place` | POST | Placement composants pcbnew |
| `/route` | POST | Routage Freerouting |
| `/drc` | POST | DRC check → violations JSON |
| `/drc/fix` | POST | Application corrections DRC |
| `/export/gerbers` | POST | Gerbers + drill + ZIP |
| `/export/step` | POST | Modèle 3D STEP (plan Maker+) |
| `/export/bom` | POST | BOM CSV JLCPCB-ready |
| `/simulate` | POST | ngspice (plan Pro) |
