"""`layers` recopiait la DEMANDE du client au lieu de décrire le board livré.

`RouteAutoResponse(layers=req.layers)` — cinq fois dans le fichier. Le champ ne
regardait jamais le board. Le client demande 4 couches, la réponse annonce 4, et
le board en a 2.

Ce n'est pas cosmétique : `handlers/routing.ts` le remonte à l'orchestrateur et
à l'utilisateur — « Routage kicad-tools 91% — 12 nets, 4 couches. » Mesuré le
2026-08-21 sur le board STM32 routé par Freerouting :

    couches déclarées dans le board : F.Cu, B.Cu        (2)
    pistes                          : 178 sur F.Cu, 23 sur B.Cu
    `layers` annoncé                : 4

Même famille que `via_count` : un chiffre qui décrit un board qui n'existe pas.

⚠️ Freerouting n'ajoute AUCUNE couche — il route dans l'empilage qu'il reçoit.
L'escalade de couches appartient à `kct route --auto-layers`. Un `layers` qui
recopie la demande masquait précisément cette différence.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(couches: list[str]) -> bytes:
    lignes = ["(kicad_pcb", '\t(version 20260206)', "\t(layers"]
    for i, nom in enumerate(couches):
        lignes.append(f'\t\t({i} "{nom}" signal)')
    lignes += [
        '\t\t(44 "Edge.Cuts" user)',
        '\t\t(37 "F.SilkS" user "F.Silkscreen")',
        "\t)",
        # Références de pistes : ne DOIVENT PAS être comptées comme des couches.
        '\t(segment (start 0 0) (end 1 1) (width 0.25) (layer "F.Cu") (net 1))',
        '\t(segment (start 0 0) (end 1 1) (width 0.25) (layer "F.Cu") (net 1))',
        ")",
    ]
    return "\n".join(lignes).encode("utf-8")


class TestComptageDesCouches:
    def test_compte_les_couches_cuivre_declarees(self):
        assert routing_router._count_copper_layers(_board(["F.Cu", "B.Cu"])) == 2

    def test_compte_les_couches_internes(self):
        board = _board(["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"])
        assert routing_router._count_copper_layers(board) == 4

    def test_ne_compte_pas_les_references_de_pistes(self):
        # Deux segments sur F.Cu ne font pas deux couches.
        assert routing_router._count_copper_layers(_board(["F.Cu", "B.Cu"])) == 2

    def test_ne_compte_pas_les_couches_non_cuivre(self):
        # Edge.Cuts et F.SilkS sont présentes dans chaque board de test.
        assert routing_router._count_copper_layers(_board(["F.Cu"])) == 1

    def test_un_board_sans_bloc_layers_ne_ment_pas(self):
        # Rien à mesurer : 0, pas une valeur plausible inventée.
        assert routing_router._count_copper_layers(b"(kicad_pcb)") == 0


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_aucune_reponse_livrant_un_board_ne_recopie_la_demande(self):
        code = "\n".join(
            ligne for ligne in self.SOURCE.splitlines()
            if not ligne.lstrip().startswith("#")
        )
        boards = code.count("kicad_pcb_b64=base64.b64encode(new_pcb)")
        mesures = code.count("layers=_count_copper_layers(new_pcb)")
        assert mesures == boards, (
            f"{boards} réponses livrent un board, {mesures} décrivent ses couches"
        )
