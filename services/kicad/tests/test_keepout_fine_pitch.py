"""Le plan ne doit pas couvrir un boitier fine-pitch : il ne peut pas l atteindre.

Mesure du 2026-08-21, board STM32 (LQFP-48, pas de 0,5 mm) : apres routage par
Freerouting avec plans sur les deux faces, 2 a 3 connexions restent manquantes,
et ce sont TOUTES des broches GND du LQFP-48 :

    Zone [GND] on F.Cu  <->  Pad 8 [GND] of U2 on F.Cu
    Pad 8 [GND] of U2   <->  Pad 47 [GND] of U2
    ...

Entre deux pattes distantes de 0,5 mm il n y a place pour aucun cuivre de plan,
quel que soit l isolement (0,5 -> 6 manquantes ; 0,25 -> 3 ; 0,2 -> 3). Le
routeur, lui, tient pour deja connectees les pastilles qui tombent
GEOMETRIQUEMENT dans le polygone de la zone : ces broches ne sont donc reliees
ni par le plan, ni par une piste.

⚠️ Mesure du 2026-08-23 sur le DSN exporte, qui corrige la formulation
precedente (« le routeur cesse de router ce net ») : le net GND n est PAS
retire de la netlist. Ses 18 broches sont presentees au routeur AVEC comme
SANS coulee ; seul `(plane GND ...)` apparait ou disparait. Le routeur n est
pas prive du travail, il le croit deja fait.

La solution est un KEEPOUT de coulee autour des boitiers denses : le plan cesse
de pretendre les couvrir, et le routeur les route normalement jusqu au bord du
plan. C est le « petit routage de sortie de broche » demande par l utilisateur,
obtenu sans code de geometrie custom.

⚠️ Le keepout interdit la COULEE, pas les pistes ni les vias : le routeur garde
tout son espace de travail.

Le detecteur de boitiers denses est celui du placement (`_dense_part_refs`,
>= 16 pads, seuil aligne sur `kicad_tools.optim.fom_features`) : on ne
reinvente pas un critere qui existe.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _footprint(ref: str, x: float, y: float, n_pads: int) -> str:
    pads = "\n".join(
        f'\t\t(pad "{i}" smd rect (at {i * 0.5} 0) (size 0.3 1.2) '
        f'(layers "F.Cu") (net 3 "GND"))'
        for i in range(1, n_pads + 1)
    )
    return (
        f'\t(footprint "Package_QFP:LQFP-48" (layer "F.Cu")\n'
        f"\t\t(at {x} {y})\n"
        f'\t\t(property "Reference" "{ref}")\n'
        f"{pads}\n"
        f"\t)"
    )


def _board(footprints: str) -> bytes:
    return (
        "(kicad_pcb\n"
        "\t(version 20260206)\n"
        "\t(layers\n"
        '\t\t(0 "F.Cu" signal)\n'
        '\t\t(31 "B.Cu" signal)\n'
        '\t\t(44 "Edge.Cuts" user)\n'
        "\t)\n"
        '\t(net 3 "GND")\n'
        "\t(gr_rect\n\t\t(start 0 0)\n\t\t(end 100 80)\n"
        '\t\t(layer "Edge.Cuts")\n\t)\n'
        f"{footprints}\n"
        ")"
    ).encode("utf-8")


DENSE = _board(_footprint("U2", 40, 30, 24))
SIMPLE = _board(_footprint("R1", 10, 10, 2))


class TestDetectionDesBoitiersDenses:
    """⚠️ Ces tests passaient — et la fonction qu ils validaient placait les
    keepouts a 87 mm de leur boitier, HORS CARTE sur 7 boards sur 8.

    Ils exercaient `_dense_footprint_boxes`, qui lisait les positions via
    `kicad-tools`. Or `kicad-tools` les rend RELATIVES a l origine de la carte
    tandis que le format `.kicad_pcb` les ecrit ABSOLUES. Sur la fixture, dont
    l origine carte est (0,0), les deux referentiels coincident : le test ne
    pouvait pas voir l ecart. Sur un vrai board, mesure le 2026-09-01 :

        LQFP-64   kicad-tools ( 67.02,  59.24)   pcbnew (154.27, 118.29)

    Le defaut a ete trouve par l UTILISATEUR, a l oeil, sur une capture KiCad
    montrant trois rectangles flottant hors de la carte.

    « Une fixture dit ce qu on a imagine, un board dit ce qui est » — la regle
    du projet, payee une fois de plus. Les tests visent desormais
    `_boites_fine_pitch`, qui lit le fichier, et une garde de coordonnees
    ABSOLUES vit dans tests/test_keepout_au_bon_endroit.py.
    """

    def test_repere_un_boitier_a_beaucoup_de_broches(self):
        assert routing_router._boites_fine_pitch(DENSE), "LQFP-48 non detecte"

    def test_ignore_un_composant_a_deux_broches(self):
        assert routing_router._boites_fine_pitch(SIMPLE) == []

    def test_la_boite_englobe_les_broches_avec_une_marge(self):
        (x1, y1, x2, y2), = routing_router._boites_fine_pitch(DENSE)
        # Les pads vont de (40+0.5, 30) a (40+12, 30), plus la marge.
        assert x1 < 40.5 and x2 > 52.0
        assert y1 < 30.0 and y2 > 30.0


class TestKeepout:
    def test_le_plan_porte_un_keepout_sur_le_boitier_dense(self):
        out = routing_router._add_ground_planes(DENSE).decode("utf-8")
        assert "(keepout" in out
        assert "(copperpour not_allowed)" in out

    def test_le_keepout_laisse_passer_pistes_et_vias(self):
        # Interdire la COULEE, pas le routage : le routeur doit garder son
        # espace de travail, sinon on remplace un blocage par un autre.
        out = routing_router._add_ground_planes(DENSE).decode("utf-8")
        assert "(tracks allowed)" in out
        assert "(vias allowed)" in out

    def test_aucun_keepout_sans_boitier_dense(self):
        # Ne pas trouer un plan sans raison : chaque trou rallonge les retours.
        out = routing_router._add_ground_planes(SIMPLE).decode("utf-8")
        assert "(keepout" not in out

    def test_le_keepout_est_sur_la_face_composants(self):
        out = routing_router._add_ground_planes(DENSE).decode("utf-8")
        bloc = out[out.index("(keepout"):]
        assert re.search(r'\(layer "F\.Cu"\)', out[: out.index("(keepout")] + bloc[:200])
