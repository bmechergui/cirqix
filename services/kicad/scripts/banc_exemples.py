"""Passe chaque exemple dans la chaine complete et resume les resultats.

    python3 scripts/banc_exemples.py

⚠️ Le nombre de COUCHES n est jamais impose : `route_auto` escalade seul
(2 -> 4 -> 6 ...) tant que le routage n aboutit pas. Le banc verifie donc aussi
que l escalade se declenche quand la densite l exige, et pas avant.

Le verdict qui compte est celui du DRC, pas le pourcentage : une carte peut etre
annoncee routee et porter des connexions manquantes. On imprime les deux.
"""
from __future__ import annotations

import base64
import logging
import json
import sys
import time
from pathlib import Path

_RACINE = next(
    (p for p in [Path(__file__).resolve().parents[1], Path("/app"), Path.cwd()]
     if (p / "routers").is_dir()),
    Path(__file__).resolve().parents[1],
)
sys.path.insert(0, str(_RACINE))

_EXEMPLES = _RACINE / "examples"


# ⚠️ Sans cette configuration, les `logger.info` du service ne s ecrivent
# NULLE PART. Le banc devenait alors aveugle a ses propres decisions, et j en
# ai tire DEUX conclusions fausses le 2026-08-27 : « la detection de boitier
# dominant ne se declenche jamais » (elle tournait) et « le placement
# deterministe n a pas ete essaye » (impossible a dire). On ne corrige pas ce
# qu on ne voit pas.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def _passer(circuit: dict, sortie: Path, tirages: int = 1) -> dict:
    """Enchaine la chaine `tirages` fois et garde le MEILLEUR board.

    ⚠️ Le placement est STOCHASTIQUE — `OptimizationWorkflow` n a pas de seed
    fixe. Mesure du 2026-08-27 : l ESP32 rend 3 erreurs a un tirage et 10 au
    suivant, sans qu une ligne de code ait change.

    Un banc a tirage unique mesure donc le HASARD, pas la chaine. Et il la
    sous-represente : la production re-tire quand le DRC echoue et garde le
    meilleur (`shouldRetryForDrc` / `keepBestDrc` dans l orchestrateur).

    On classe par (erreurs, connexions manquantes) : une erreur de
    fabricabilite fait refuser la carte, une connexion manquante se voit au
    DRC. La premiere prime.
    """
    meilleur = None
    for n in range(max(1, tirages)):
        r = _un_tirage(circuit, sortie)
        if "erreur" in r:
            return r
        cle = (r["erreurs"], r["manquantes"])
        if meilleur is None or cle < (meilleur["erreurs"], meilleur["manquantes"]):
            meilleur = r
            meilleur["tirage_retenu"] = n + 1
        if cle == (0, 0):
            break  # rien de mieux a esperer
    meilleur["tirages"] = max(1, tirages)
    return meilleur


def _un_tirage(circuit: dict, sortie: Path) -> dict:
    from routers.schematic import SchematicRequest
    from routers.schematic import generate as generer_schema
    from routers.erc import ERCRequest, run_erc
    from routers.pcb import PcbRequest
    from routers.pcb import generate as generer_pcb
    from routers.placement import AutoPlacementRequest, place_auto
    from routers.routing import RouteAutoRequest, route_auto
    from routers import routing as R

    liaisons = circuit.get("nets") or []
    charge = {
        "components": circuit["components"],
        "nets": [n["name"] for n in liaisons],
        "connections": liaisons,
        "board_width_mm": circuit.get("board_width_mm", 50.0),
        "board_height_mm": circuit.get("board_height_mm", 50.0),
    }
    t0 = time.time()
    sch = generer_schema(SchematicRequest(**charge))
    if not sch.success:
        return {"etape": "schema", "erreur": sch.error}
    kicad_sch = sch.kicad_sch_content.encode()

    erc = run_erc(ERCRequest(kicad_sch_b64=_b64(kicad_sch)))
    if erc.kicad_sch_b64:
        kicad_sch = base64.b64decode(erc.kicad_sch_b64)

    pcb = generer_pcb(PcbRequest(kicad_sch_b64=_b64(kicad_sch), **charge))
    if not pcb.success:
        return {"etape": "pcb", "erreur": pcb.error}
    board = pcb.kicad_pcb_content.encode()

    board = base64.b64decode(place_auto(
        AutoPlacementRequest(kicad_pcb_b64=_b64(board))).kicad_pcb_b64)

    # ⚠️ `layers` est le PLAFOND, pas le palier vise : le service part
    # toujours de 2 et s arrete au premier palier qui route a 100 %. Passer 2
    # ici donnait une echelle a UN barreau et interdisait toute escalade —
    # c est ce qui bloquait l ESP32 a 25 % de routage.
    route = route_auto(RouteAutoRequest(kicad_pcb_b64=_b64(board), layers=8, timeout_s=1800))
    board = base64.b64decode(route.kicad_pcb_b64)

    sortie.mkdir(parents=True, exist_ok=True)
    (sortie / "final.kicad_pcb").write_bytes(board)

    rapport = R._rapport_drc(board)
    violations = rapport.get("violations", []) or []
    txt = board.decode("utf-8", "replace")
    import re
    from collections import Counter
    par_net = Counter()
    for s in re.findall(r"\(segment.*?\n\t*\)", txt, re.DOTALL):
        m = re.search(r'\(net (?:\d+ )?"([^"]*)"\)', s)
        par_net[m.group(1) if m else "?"] += 1
    return {
        "erc_violations": len(erc.violations),
        "routed_percent": route.routed_percent,
        "moteur": route.engine,
        "couches": route.layers,
        "manquantes": len(rapport.get("unconnected_items", []) or []),
        "erreurs": sum(1 for v in violations if v.get("severity") == "error"),
        "avertissements": sum(1 for v in violations if v.get("severity") == "warning"),
        "segments": sum(par_net.values()),
        "segments_gnd": par_net.get("GND", 0),
        "zones": txt.count("(zone"),
        "remplies": txt.count("filled_polygon"),
        "duree_s": round(time.time() - t0, 1),
    }


def main(argv: list[str]) -> int:
    # ⚠️ `examples/` n est PAS monte dans le conteneur : il est cuit dans
    # l image. On accepte donc une racine d exemples explicite, sinon le banc
    # ne verrait que les cas de l image.
    global _EXEMPLES
    if argv[1:] and Path(argv[1]).is_dir():
        _EXEMPLES = Path(argv.pop(1))
    tirages = 1
    for arg in list(argv[1:]):
        if arg.startswith("--tirages="):
            tirages = int(arg.split("=", 1)[1])
            argv.remove(arg)
    cas = argv[1:] or [d.name for d in sorted((_EXEMPLES).iterdir())
                       if (d / "input" / "circuit.json").is_file()]
    print(f"{'cas':<18}{'comp':>5}{'couches':>8}{'%':>5}{'manq':>6}"
          f"{'err':>5}{'warn':>6}{'seg':>6}{'GND':>5}{'duree':>8}")
    resultats = {}
    for nom in cas:
        f = _EXEMPLES / nom / "input" / "circuit.json"
        if not f.is_file():
            # ⚠️ Ne PAS sauter en silence. Le 2026-08-27, trois lancements de
            # suite n ont produit que la ligne d en-tete : la racine d exemples
            # etait la mauvaise, aucun cas ne correspondait, et le banc sortait
            # en rc=0 comme s il avait travaille. J ai conclu deux fois que le
            # processus « mourait ».
            print("cas introuvable : %s" % f, file=sys.stderr)
            continue
        circuit = json.loads(f.read_text(encoding="utf-8"))
        try:
            r = _passer(circuit, _EXEMPLES / nom / "output", tirages)
        except Exception as exc:
            r = {"etape": "exception", "erreur": str(exc)[:90]}
        resultats[nom] = r
        if "erreur" in r:
            print(f"{nom:<18} ECHEC [{r.get('etape')}] {r['erreur'][:60]}", flush=True)
            continue
        print(f"{nom:<18}{len(circuit['components']):>5}{r['couches']:>8}"
              f"{r['routed_percent']:>5}{r['manquantes']:>6}{r['erreurs']:>5}"
              f"{r['avertissements']:>6}{r['segments']:>6}{r['segments_gnd']:>5}"
              f"{r['duree_s']:>7}s", flush=True)
    (_EXEMPLES / "banc.json").write_text(
        json.dumps(resultats, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
