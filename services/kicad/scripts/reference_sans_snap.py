#!/usr/bin/env python3
"""Point de référence : le placement AVANT le snap, mesuré sur le code du jour.

Demandé par l'utilisateur le 2026-09-02 : conserver, dans `examples/` et dans
Git, la version d'avant le snap, pour que la comparaison reste rejouable.

⚠️ CE QUE CE SCRIPT MESURE, EXACTEMENT. Il n'exécute pas le code du
2026-08-09 : il exécute le code d'AUJOURD'HUI avec le snap **neutralisé**.
C'est délibéré, et c'est plus honnête pour la comparaison.

Le vrai commit d'avant le snap est `0d5dbf7^` (le snap est né le 2026-08-29).
Y revenir annulerait aussi trois semaines d'autres correctifs — le keepout à la
source, le clamp du courtyard, le repli déterministe… La différence mesurée ne
serait alors plus imputable au snap, mais à un mélange indémêlable.

En neutralisant le seul snap, l'écart mesuré EST l'effet du snap.

Chaque board produit porte la version du code qui l'a fait, écrite dans un
fichier `VERSION.txt` à côté : sans elle, un board d'examples n'est qu'une
image sans date, impossible à rejouer ou à réfuter.
"""
from __future__ import annotations

import base64
import json
import math
import statistics as st
import subprocess
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, "/app")
sys.path.insert(0, "/opt/kicad-tools/src")

_EX = Path("/tmp/ex")


def _version_du_code() -> str:
    """SHA + date du dépôt, ou une mention explicite si indisponible."""
    try:
        sha = subprocess.run(["git", "-C", "/app", "rev-parse", "--short", "HEAD"],
                             capture_output=True, text=True, timeout=10)
        if sha.returncode == 0 and sha.stdout.strip():
            return sha.stdout.strip()
    except Exception:
        pass
    return "inconnue (depot non accessible depuis le conteneur)"


def _drc(chemin: str):
    rap = tempfile.mktemp(suffix=".json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", rap,
                    chemin], capture_output=True)
    try:
        d = json.load(open(rap, encoding="utf-8"))
    except Exception:
        return None, None
    v = d.get("violations") or []
    return sum(1 for x in v if x.get("severity") == "error"), len(v)


def _capas(chemin: str) -> list:
    """Distance de chaque condensateur au circuit intégré LE PLUS PROCHE."""
    from kicad_tools.schema.pcb import PCB
    pcb = PCB.load(chemin)
    pos = {}
    for fp in pcb.footprints:
        p = fp.position
        pos[fp.reference] = (p.x, p.y) if hasattr(p, "x") else tuple(p)
    ics = sorted(r for r in pos if r.startswith("U"))
    caps = sorted(r for r in pos if r.startswith("C"))
    if not ics or not caps:
        return []
    return [min(math.hypot(pos[c][0] - pos[u][0], pos[c][1] - pos[u][1])
                for u in ics) for c in caps]


def _grille(carte: str):
    from routers.schematic import SchematicRequest, generate as generer_schema
    from routers.pcb import PcbRequest, generate as generer_pcb
    entree = _EX / carte / "input" / "circuit.json"
    if not entree.is_file():
        return None
    circuit = json.loads(entree.read_text(encoding="utf-8"))
    liaisons = circuit.get("nets") or []
    charge = {
        "components": circuit["components"],
        "nets": [n["name"] for n in liaisons],
        "connections": liaisons,
        "board_width_mm": circuit.get("board_width_mm", 50.0),
        "board_height_mm": circuit.get("board_height_mm", 50.0),
    }
    sch = generer_schema(SchematicRequest(**charge))
    if not sch.success:
        return None
    pcb = generer_pcb(PcbRequest(
        kicad_sch_b64=base64.b64encode(sch.kicad_sch_content.encode()).decode(),
        **charge))
    return pcb.kicad_pcb_content.encode() if pcb.success else None


def placer(grille: bytes, avec_snap: bool) -> bytes:
    """Place la grille, snap ACTIF ou NEUTRALISÉ."""
    from routers.placement import AutoPlacementRequest, place_auto
    from tools import placement as P
    original = P.snap_cluster_members
    if not avec_snap:
        P.snap_cluster_members = lambda *a, **k: 0
    try:
        return base64.b64decode(place_auto(AutoPlacementRequest(
            kicad_pcb_b64=base64.b64encode(grille).decode())).kicad_pcb_b64)
    finally:
        P.snap_cluster_members = original


def mesurer(carte: str) -> dict:
    sortie = _EX / carte / "output"
    sortie.mkdir(parents=True, exist_ok=True)
    grille = _grille(carte)
    if grille is None:
        return {"carte": carte, "erreur": "pas de circuit.json exploitable"}

    resultats = {}
    for nom, avec in (("sans_snap", False), ("avec_snap", True)):
        t0 = time.time()
        try:
            board = placer(grille, avec)
        except Exception as exc:
            resultats[nom] = {"erreur": str(exc)}
            continue
        p = sortie / ("2_placement_%s.kicad_pcb" % nom)
        p.write_bytes(board)
        d = _capas(str(p))
        err, viol = _drc(str(p))
        resultats[nom] = {
            "mediane": round(st.median(d), 1) if d else None,
            "max": round(max(d), 1) if d else None,
            "erreurs": err, "violations": viol,
            "duree_s": round(time.time() - t0, 1),
        }
    return {"carte": carte, **resultats}


if __name__ == "__main__":
    version = _version_du_code()
    cartes = sys.argv[1:] or ["nucleo-f401", "stm32-30", "stm32-60"]
    print("version du code : %s" % version, flush=True)
    tout = []
    for c in cartes:
        print("== %s" % c, flush=True)
        r = mesurer(c)
        tout.append(r)
        for nom in ("sans_snap", "avec_snap"):
            d = r.get(nom) or {}
            if "erreur" in d:
                print("   %-10s ECHEC %s" % (nom, d["erreur"]), flush=True)
            else:
                print("   %-10s mediane %5s mm · max %5s mm · %s erreur(s) · "
                      "%s violations · %s s"
                      % (nom, d["mediane"], d["max"], d["erreurs"],
                         d["violations"], d["duree_s"]), flush=True)
    print("\n=== RECAPITULATIF (version %s)" % version, flush=True)
    print("%-14s %-22s %-22s" % ("carte", "SANS snap", "AVEC snap"), flush=True)
    for r in tout:
        s, a = r.get("sans_snap") or {}, r.get("avec_snap") or {}
        print("%-14s med %-5s max %-5s err %-3s   med %-5s max %-5s err %-3s"
              % (r["carte"], s.get("mediane"), s.get("max"), s.get("erreurs"),
                 a.get("mediane"), a.get("max"), a.get("erreurs")), flush=True)
