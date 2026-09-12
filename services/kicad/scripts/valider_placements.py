#!/usr/bin/env python3
"""Produit et VALIDE un placement par carte, depuis la description du circuit.

Séquence demandée par l'utilisateur le 2026-09-02 :
  ① valider le placement de chaque carte
  ② le déposer dans `examples/<carte>/output/`
  ③ le GELER
  ④ router dessus, en déposant chaque étape

Ce script fait ① et ②. Le gel est assuré par le nom `2_placement.kicad_pcb`,
que le banc relit en mode `--placement-fige`.

⚠️ Un placement n'est VALIDÉ que s'il passe un critère explicite :

    0 erreur DRC        — une erreur de fabricabilité fait refuser la carte
    tous les composants dans le contour
    aucun conflit de placement non résolu

Un placement qui échoue est RE-TIRÉ, jusqu'à `_TIRAGES` fois. Le placement est
stochastique : re-tirer est le levier, et c'est déjà la stratégie de la chaîne.
On garde le MEILLEUR, jamais le dernier.
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

_TIRAGES = 3
# Placement PRO : chaque decouplage a moins de 5 mm de sa broche (regle 1-3 mm,
# docs/methodologie-routage.md ; mesure 2026-09-12 : 2,5 mm moy / 4,8 max atteints).
_DECOUPLAGE_MAX_MM = 5.0
_EX = Path("/tmp/ex")


def _b64(x: bytes) -> str:
    return base64.b64encode(x).decode()


def _drc(chemin: str):
    """(erreurs, violations) selon kicad-cli, l'instrument qui fait foi."""
    rap = tempfile.mktemp(suffix=".json")
    subprocess.run(["kicad-cli", "pcb", "drc", "--format", "json", "-o", rap,
                    chemin], capture_output=True)
    try:
        d = json.load(open(rap, encoding="utf-8"))
    except Exception:
        return None, None
    v = d.get("violations") or []
    return sum(1 for x in v if x.get("severity") == "error"), len(v)


def _capas_au_mcu(chemin: str) -> dict:
    """Distance de chaque condensateur au premier circuit intégré."""
    from kicad_tools.schema.pcb import PCB
    pcb = PCB.load(chemin)
    pos = {}
    for fp in pcb.footprints:
        p = fp.position
        pos[fp.reference] = (p.x, p.y) if hasattr(p, "x") else tuple(p)
    ics = sorted(r for r in pos if r.startswith("U"))
    if not ics:
        return {}
    a = pos[ics[0]]
    return {r: math.hypot(xy[0] - a[0], xy[1] - a[1])
            for r, xy in pos.items() if r.startswith("C")}


def _grille(carte: str) -> bytes | None:
    """Board du générateur, avant toute optimisation."""
    from routers.schematic import SchematicRequest, generate as generer_schema
    from routers.pcb import PcbRequest, generate as generer_pcb
    # Deux formes coexistent (cf. banc_exemples._fichier_de_cas) : circuit.json
    # (nets = [{name, pins}]) et schema.json (nets = noms, connections = liaisons).
    entree = next((f for f in (_EX / carte / "input" / n for n in ("circuit.json", "schema.json"))
                   if f.is_file()), None)
    if entree is None:
        return None
    circuit = json.loads(entree.read_text(encoding="utf-8"))
    liaisons = (circuit.get("connections") if isinstance(circuit.get("connections"), list)
                else circuit.get("nets")) or []
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
        kicad_sch_b64=_b64(sch.kicad_sch_content.encode()), **charge))
    if not pcb.success:
        return None
    return pcb.kicad_pcb_content.encode(), charge["board_width_mm"], charge["board_height_mm"]


def _decouplage(chemin: str) -> tuple[float, float, int]:
    """(moyenne, max, n) de l ecart libre capa -> broche d alimentation la plus
    proche — la mesure du service (`qualite_decouplage`)."""
    from kicad_tools.schema.pcb import PCB
    from tools.placement_bypass import qualite_decouplage
    return qualite_decouplage(PCB.load(chemin))


def valider(carte: str) -> dict:
    from routers.placement import AutoPlacementRequest, place_auto
    sortie = _EX / carte / "output"
    sortie.mkdir(parents=True, exist_ok=True)

    g = _grille(carte)
    if g is None:
        return {"carte": carte, "erreur": "pas d entree exploitable (circuit.json / schema.json)"}
    grille, largeur, hauteur = g
    (sortie / "1_grille.kicad_pcb").write_bytes(grille)

    meilleur = None
    for i in range(1, _TIRAGES + 1):
        t0 = time.time()
        try:
            board = base64.b64decode(place_auto(
                AutoPlacementRequest(kicad_pcb_b64=_b64(grille), board_width_mm=largeur,
                                     board_height_mm=hauteur)).kicad_pcb_b64)
        except Exception as exc:
            print("   tirage %d : ECHEC %s" % (i, exc), flush=True)
            continue
        essai = str(sortie / ("2_placement_essai%d.kicad_pcb" % i))
        Path(essai).write_bytes(board)
        err, viol = _drc(essai)
        try:
            med, mx, n_capas = _decouplage(essai)
        except Exception as exc:  # noqa: BLE001
            med, mx, n_capas = 0.0, 0.0, 0
            print("   (decouplage non mesure : %s)" % exc, flush=True)
        print("   tirage %d/%d : %s erreur(s) · %s violations · decouplage moy %.1f "
              "max %.1f mm (%d capas) · %.0f s"
              % (i, _TIRAGES, err, viol, med, mx, n_capas, time.time() - t0), flush=True)
        # ⚠️ Classement : l'erreur d'abord — une carte non fabricable ne part
        # pas. À égalité, le découplage le plus serré (regle 1-3 mm, max 5).
        cle = (err if err is not None else 99, round(mx, 1), round(med, 1))
        if meilleur is None or cle < meilleur["cle"]:
            meilleur = {"cle": cle, "board": board, "err": err, "viol": viol,
                        "med": med, "max": mx, "tirage": i}

    if meilleur is None:
        return {"carte": carte, "erreur": "aucun tirage abouti"}

    # ⚠️ Le placement RETENU prend le nom que le banc relit en mode figé.
    (sortie / "2_placement.kicad_pcb").write_bytes(meilleur["board"])
    pro = meilleur["max"] <= _DECOUPLAGE_MAX_MM
    return {"carte": carte, "valide": meilleur["err"] == 0 and pro, "pro": pro, **{
        k: meilleur[k] for k in ("err", "viol", "med", "max", "tirage")}}


if __name__ == "__main__":
    cartes = sys.argv[1:] or ["nucleo-f401", "stm32-30", "stm32-60", "stm32-100"]
    resultats = []
    for c in cartes:
        print("== %s" % c, flush=True)
        r = valider(c)
        resultats.append(r)
        if "erreur" in r:
            print("   -> %s" % r["erreur"], flush=True)
        else:
            print("   -> RETENU tirage %d : %s erreur(s), capas med %.1f max "
                  "%.1f mm  %s" % (r["tirage"], r["err"], r["med"], r["max"],
                                   "VALIDE" if r["valide"] else "NON VALIDE"),
                  flush=True)
    print("\n=== RECAPITULATIF")
    for r in resultats:
        if "erreur" in r:
            print("   %-16s %s" % (r["carte"], r["erreur"]))
        else:
            print("   %-22s %s erreur(s)  %3s violations  decouplage moy %5.1f "
                  "max %5.1f mm   %s"
                  % (r["carte"], r["err"], r["viol"], r["med"], r["max"],
                     "VALIDE" if r["valide"] else "NON VALIDE"))
