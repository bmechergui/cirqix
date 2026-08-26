"""Ouvrir les regles de percage SEULEMENT quand un boitier fine-pitch l exige.

Mesure du 2026-08-26. Le via-in-pad — seule reparation possible pour les pattes
d un LQFP-48 que le plan n atteint pas — etait refuse par le DRC :

    exige : via >= 0,50 mm | percage >= 0,30 | anneau >= 0,10
    pose  : via    0,30 mm | percage    0,15 | anneau    0,075

⚠️ Ces contraintes ne viennent PAS du fichier de carte : il n en declare aucune.
Depuis KiCad 6, les regles vivent dans le fichier PROJET (`.kicad_pro`). Sans
lui, `kicad-cli` applique ses defauts — et nos boards n en ont jamais eu.

En fournissant un projet aux regles ouvertes, mesure sur le meme board :

    sans projet          -> 9 erreurs
    avec regles ouvertes -> 0 erreur

⚠️ On n ouvre PAS par defaut. Un percage de 0,15 mm est une option payante chez
JLCPCB (via bouche/recouvert), pas le procede standard. La condition est la
presence reelle d un boitier dense — le meme critere que le halo d escape et le
keepout de coulee, `>= 16 pads`, aligne sur `kicad_tools.optim.fom_features`.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _footprint(ref: str, n_pads: int) -> str:
    pads = "\n".join(
        f'\t\t(pad "{i}" smd rect (at {i * 0.5} 0) (size 0.3 1.48) '
        f'(layers "F.Cu") (net 3 "GND"))'
        for i in range(1, n_pads + 1)
    )
    return (
        f'\t(footprint "Package_QFP:LQFP-48" (layer "F.Cu")\n'
        f"\t\t(at 40 30)\n"
        f'\t\t(property "Reference" "{ref}")\n{pads}\n\t)'
    )


def _board(fps: str) -> bytes:
    return (
        "(kicad_pcb\n\t(version 20240108)\n"
        '\t(layers\n\t\t(0 "F.Cu" signal)\n\t\t(31 "B.Cu" signal)\n\t)\n'
        '\t(net 3 "GND")\n'
        '\t(gr_rect (start 0 0) (end 100 80) (layer "Edge.Cuts"))\n'
        f"{fps}\n)"
    ).encode("utf-8")


DENSE = _board(_footprint("U2", 24))
SIMPLE = _board(_footprint("R1", 2))


class TestConditionnement:
    def test_un_boitier_dense_ouvre_les_regles(self):
        p = routing_router._projet_kicad(DENSE)
        assert p is not None
        regles = p["board"]["design_settings"]["rules"]
        assert regles["min_via_diameter"] <= 0.3
        assert regles["min_through_hole_diameter"] <= 0.15

    def test_une_carte_sans_fine_pitch_garde_les_defauts(self):
        # Ne pas facturer un procede fin a une carte qui n en a pas besoin.
        assert routing_router._projet_kicad(SIMPLE) is None

    def test_le_projet_est_du_JSON_valide(self):
        import json

        p = routing_router._projet_kicad(DENSE)
        json.loads(json.dumps(p))  # leve si non serialisable
        assert p["meta"]["version"] >= 1


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_drc_ecrit_le_projet_a_cote_du_board(self):
        # Sans le fichier PROJET dans le meme dossier, kicad-cli applique ses
        # defauts et le verdict porte sur des regles que la carte ne suit pas.
        corps = self.SOURCE[self.SOURCE.index("def _rapport_drc(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert "_projet_kicad(" in corps
        assert "kicad_pro" in corps
