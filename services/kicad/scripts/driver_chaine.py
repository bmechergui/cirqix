"""Rejoue la chaine KiCad complete SANS appeler d'API LLM.

Le pipeline de production demande un modele a deux endroits seulement : ecrire
le schema (Haiku) et decider de l'enchainement (Sonnet). Tout le reste — ERC,
generation du PCB, placement, routage, DRC, export — est deterministe et ne
depend d'aucun jeton.

Ce driver fournit donc le schema en dur et enchaine lui-meme, ce qui permet de
valider la chaine quand le solde Anthropic est epuise. C'est l'idee de
l'utilisateur, prise au mot : l'humain (ou l'assistant) joue le LLM.

    python3 scripts/driver_chaine.py [chemin/vers/circuit.json]

⚠️ Ce n'est PAS un test automatise et il n'a pas sa place dans `tests/` : il
appelle les vraies fonctions de production sur un vrai board, et sa duree se
compte en minutes. C'est un instrument de validation manuelle, au meme titre que
`driver_llm.py`.
"""
from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path

# Racine du service : le dossier qui contient `routers/`. On le cherche
# plutot que de le deduire de `__file__`, qui vaut /tmp quand le driver est
# injecte dans le conteneur.
_RACINE = next(
    (p for p in [Path(__file__).resolve().parents[1], Path("/app"), Path.cwd()]
     if (p / "routers").is_dir()),
    Path(__file__).resolve().parents[1],
)
sys.path.insert(0, str(_RACINE))

DEFAUT = _RACINE / "examples" / "led-blinker-full-pipeline" / "input" / "circuit.json"


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _etape(nom: str, debut: float) -> None:
    print(f"  {nom:<28} {time.time() - debut:6.1f} s", flush=True)


def main(argv: list[str]) -> int:
    source = Path(argv[1]) if len(argv) > 1 else DEFAUT
    circuit = json.loads(source.read_text(encoding="utf-8"))
    print(f"schema : {source.name} — {len(circuit.get('components', []))} composants, "
          f"{len(circuit.get('nets', []))} nets", flush=True)

    from routers.schematic import SchematicRequest
    from routers.schematic import generate as generer_schema
    from routers.erc import ERCRequest, run_erc
    from routers.pcb import PcbRequest
    from routers.pcb import generate as generer_pcb
    from routers.placement import AutoPlacementRequest, place_auto
    from routers.routing import RouteAutoRequest, route_auto
    from routers.drc import DRCAutoRequest, run_drc_auto

    # ⚠️ Le modele separe les NOMS de nets (`nets`) de leurs LIAISONS
    # (`connections`). Le fichier d exemple les melange dans un seul tableau.
    liaisons = circuit.get("nets") or []
    charge = {
        "components": circuit["components"],
        "nets": [n["name"] for n in liaisons],
        "connections": liaisons,
        "board_width_mm": circuit.get("board_width_mm", 50.0),
        "board_height_mm": circuit.get("board_height_mm", 50.0),
    }

    t = time.time()
    sch = generer_schema(SchematicRequest(**charge))
    if not sch.success or not sch.kicad_sch_content:
        print("  schema ECHOUE :", sch.error)
        return 1
    _etape("schema", t)
    kicad_sch = sch.kicad_sch_content.encode()

    t = time.time()
    erc = run_erc(ERCRequest(kicad_sch_b64=_b64(kicad_sch)))
    _etape(f"erc ({len(erc.violations)} violations)", t)
    if erc.kicad_sch_b64:
        kicad_sch = base64.b64decode(erc.kicad_sch_b64)

    t = time.time()
    pcb = generer_pcb(PcbRequest(kicad_sch_b64=_b64(kicad_sch), **charge))
    if not pcb.success or not pcb.kicad_pcb_content:
        print("  pcb ECHOUE :", pcb.error)
        return 1
    _etape("pcb", t)
    board = pcb.kicad_pcb_content.encode()

    t = time.time()
    place = place_auto(AutoPlacementRequest(kicad_pcb_b64=_b64(board)))
    _etape("placement", t)
    board = base64.b64decode(place.kicad_pcb_b64)

    t = time.time()
    route = route_auto(RouteAutoRequest(kicad_pcb_b64=_b64(board), layers=2, timeout_s=900))
    _etape(f"routage ({route.routed_percent} %, {route.engine})", t)
    board = base64.b64decode(route.kicad_pcb_b64)

    t = time.time()
    drc = run_drc_auto(DRCAutoRequest(kicad_pcb_b64=_b64(board)))
    _etape(f"drc ({len(drc.violations)} violations)", t)

    sortie = Path("/tmp/driver_chaine")
    sortie.mkdir(exist_ok=True)
    (sortie / "final.kicad_pcb").write_bytes(board)
    print(f"\nboard : {sortie / 'final.kicad_pcb'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
