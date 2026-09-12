#!/usr/bin/env python3
"""Compare nos cartes à une carte dessinée par un HUMAIN.

## Pourquoi

Un banc qui ne compare que nos cartes entre elles mesure une DÉRIVE, jamais un
écart à l'état de l'art. Quand l'utilisateur juge le 2026-09-08 que « les cartes
ne sont pas pro d'un ingénieur senior », aucune de nos mesures internes ne peut
lui répondre : elles disent seulement que nos cartes se ressemblent.

La référence est `astra_piNas` — porteuse CM5 Lite, six couches, 176 empreintes,
routée à la main. Voir `examples/reference-astra-pinas/README.md`.

⚠️ Elle n'est PAS versionnée : le dépôt source ne porte aucune licence. Lancer
`examples/reference-astra-pinas/recuperer.sh` d'abord.

## Ce qui est mesuré, et pourquoi

`grille`     — part des empreintes dont la position est un multiple du pas.
               Ce n'est pas cosmétique : des rangées alignées donnent des pistes
               parallèles, donc un routage plus court. Et c'est ce qu'un œil
               humain voit AVANT tout raisonnement.

`paires`     — distance moyenne d'un net qui ne touche que DEUX boîtiers de peu
               de pastilles : une LED et sa résistance série, typiquement. C'est
               la paire la plus serrable qui existe sur une carte, donc le
               meilleur révélateur d'un placement.
               ⚠️ On écarte les concentrateurs : un MCU ne peut pas être
               adjacent à ses vingt voisins, et le compter fausserait tout.

`au dos`     — empreintes sur `B.Cu`. La référence en a 12, nous zéro sur nos
               dix-huit cartes. ⚠️ Ce n'est pas un défaut de placement mais une
               CAPACITÉ MANQUANTE : aucun réglage du placeur ne le corrigera.

`couches`    — cuivre déclaré. La référence en a six ; nos cartes deux.

⚠️ CE QUE CE SCRIPT NE DIT PAS. La référence est routée à la main par quelqu'un
qui connaît son circuit ; nous produisons en minutes sans intervention. Un écart
n'est pas un verdict — c'est un CAP.

Usage :
    python scripts/comparer_a_la_reference.py
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_SERVICE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_SERVICE))
sys.path.insert(0, str(_SERVICE / "kicad-tools" / "src"))

_PAS_MM = 0.5
_REFERENCE = (_SERVICE / "examples" / "reference-astra-pinas" / "input"
              / "astra_piNas.kicad_pcb")


def _decouplage_corps_a_corps(pcb) -> tuple[float, float, int]:
    """Ecart LIBRE entre le corps d un condensateur de decouplage et la broche
    d alimentation qu il decouple. Rend (moyenne, max, nombre).

    ⚠️ CORPS-A-CORPS, PAS ORIGINE-A-BROCHE. Mesure du 2026-09-10 sur carte-05 :
    origine->broche disait 4,6 mm de moyenne ; corps->broche dit 2,8 mm, cinq
    capas sur huit sous 2 mm. Une 0603 fait 1,6 mm : mesurer depuis son origine
    ajoute la moitie du boitier et fait echouer une carte conforme. C est le
    piege « origine vs corps » que CLAUDE.md documente pour le snap — il vaut
    aussi pour la mesure.

    La regle de l industrie (docs/methodologie-routage.md) : 1 a 3 mm.
    """
    import math
    from tools.placement_bypass import _pastille_partagee, _centre_et_demi, _portee
    # ⚠️ ON UTILISE LA DETECTION NATIVE, pas une devinette sur le prefixe « C ».
    # Deuxieme version fausse de cette metrique : la reference humaine sortait
    # a 26,6 mm — invraisemblable pour une carte pro — parce que je comptais
    # les 38 condensateurs de +3V3 comme des decouplages de CI, y compris ceux
    # qui filtrent un connecteur ou un LDO a l autre bout de la carte.
    # `detect_functional_clusters` sait lesquels decouplent QUEL CI : c est ce
    # que le snap utilise, donc c est ce que la mesure doit utiliser. Calibrer
    # sur la source que le code lit — pour la mesure aussi.
    from tools.placement_bypass import _clusters_natifs, _composants
    fps = {f.reference: f for f in pcb.footprints if f.reference}
    couples = []
    for c in _clusters_natifs(_composants(pcb)):
        if str(getattr(c, "cluster_type", "")).upper().endswith("POWER"):
            couples += [(m, c.anchor) for m in c.members]
    out = []
    for r, ancre in couples:
        f = fps.get(r); ci = fps.get(ancre)
        if f is None or ci is None:
            continue
        cis = [ci]
        # ⚠️ CONTRE LE CI LE PLUS PROCHE sur ce rail, pas le premier trouve.
        # Premiere version : `break` au premier CI partageant le rail. Sur la
        # reference humaine, +3V3 touche tous les CI — chaque capa etait mesuree
        # contre un CI au hasard, et la reference sortait a 43 mm de decouplage.
        # Une capa decouple le CI qu elle touche, pas un CI au bout du rail.
        meilleur = None
        for ci in cis:
            b = _pastille_partagee(ci, f)
            if b is None:
                continue
            cx, cy, hw, hh = _centre_et_demi(f)
            dx, dy = cx - b[0], cy - b[1]
            d = math.hypot(dx, dy) or 1e-9
            libre = max(0.0, d - _portee(hw, hh, dx / d, dy / d) - 0.35)
            if meilleur is None or libre < meilleur:
                meilleur = libre
        if meilleur is not None:
            out.append(meilleur)
    if not out:
        return (0.0, 0.0, 0)
    return (sum(out) / len(out), max(out), len(out))


def _sur_grille(v: float, pas: float) -> bool:
    return abs(v / pas - round(v / pas)) < 1e-6


def mesurer(chemin: Path) -> dict | None:
    from kicad_tools.schema.pcb import PCB
    from tools.placement_contraintes import paires_du_board

    try:
        pcb = PCB.load(str(chemin))
    except Exception as e:  # noqa: BLE001
        # ⚠️ On REND l'échec, on ne rend pas des zéros : un board illisible
        # compté « 0 composant au dos » se lirait comme un board conforme.
        return {"echec": str(e)[:80]}

    fps = [f for f in pcb.footprints if getattr(f, "reference", None)]
    if not fps:
        return {"echec": "aucune empreinte"}

    texte = chemin.read_text(encoding="utf-8", errors="replace")
    pos = {f.reference: f.position for f in fps}
    paires = paires_du_board(pcb)
    d = [math.dist(pos[a], pos[b]) for _, a, b in paires
         if a in pos and b in pos]

    dm, dx, dn = _decouplage_corps_a_corps(pcb)
    return {
        "decouplage_moy": dm, "decouplage_max": dx, "decouplage_n": dn,
        "empreintes": len(fps),
        "couches": len(re.findall(r'\((\d+) "(?:F|B|In\d+)\.Cu"', texte)),
        "au_dos": sum(1 for f in fps if getattr(f, "layer", "") == "B.Cu"),
        "sur_grille": sum(1 for f in fps
                          if _sur_grille(f.position[0], _PAS_MM)
                          and _sur_grille(f.position[1], _PAS_MM)),
        "paires": len(d),
        "paire_moyenne": (sum(d) / len(d)) if d else None,
        "paire_max": max(d) if d else None,
    }


def _ligne(titre: str, m: dict) -> str:
    if "echec" in m:
        return "%-24s ILLISIBLE — %s" % (titre, m["echec"])
    if m["paire_moyenne"] is None:
        paire = "aucune paire"
    else:
        paire = "%5.1f mm (max %5.1f)" % (m["paire_moyenne"], m["paire_max"])
    dec = ("decouplage %.1f mm (max %.1f, %d)" % (m["decouplage_moy"], m["decouplage_max"], m["decouplage_n"])
           if m["decouplage_n"] else "decouplage -")
    return ("%-22s %3d fp · grille %3.0f %% · paires %s · %s"
            % (titre, m["empreintes"], 100.0 * m["sur_grille"] / m["empreintes"], paire, dec))


def main(argv: list[str]) -> int:
    exemples = _SERVICE / "examples"

    if _REFERENCE.is_file():
        print(_ligne("REFERENCE humaine", mesurer(_REFERENCE)))
    else:
        # ⚠️ On le DIT au lieu de comparer nos cartes entre elles en silence :
        # c'est précisément le défaut que ce script existe pour corriger.
        print("REFERENCE ABSENTE — lancer "
              "examples/reference-astra-pinas/recuperer.sh")
    print("-" * 110)

    for dossier in sorted(exemples.glob("carte-*")):
        board = dossier / "expected" / "final.kicad_pcb"
        if board.is_file():
            print(_ligne(dossier.name, mesurer(board)))

    print()
    print("Une paire en serie = un net qui ne touche que deux boitiers de peu de")
    print("pastilles (LED + resistance). Les concentrateurs sont ecartes : un MCU")
    print("ne peut pas etre adjacent a ses vingt voisins.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
