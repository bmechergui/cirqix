"""`via_count` et `track_length_mm` étaient des zéros fabriqués.

Aucun des quatre niveaux de `route_auto` ne les calculait : les réponses
sortaient avec les valeurs par DÉFAUT du modèle Pydantic (`0` et `0.0`). Le
client TypeScript les lit pourtant (`routing-service.ts`) et les transmet à
l'interface sous `viaCount` / `trackLengthMm`.

Résultat : un board réellement routé — 53 segments mesurés le 2026-08-20 sur
led-blinker — s'affichait avec « 0 via, 0 mm de piste ». Ce ne sont pas des
indicateurs manquants, ce sont des chiffres FAUX présentés comme réels, la même
famille de défauts que les succès fabriqués assainis en juillet-août.

⚠️ Un zéro est une valeur plausible (un board sans via en a zéro). C'est ce qui
rend le défaut invisible : rien ne distingue « mesuré à zéro » de « jamais
mesuré ». D'où la mesure réelle plutôt que l'omission.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as routing_router  # noqa: E402


def _board(segments: list[tuple[float, float, float, float]], vias: int = 0) -> bytes:
    lignes = ["(kicad_pcb", '\t(version 20260206)']
    for (x1, y1, x2, y2) in segments:
        lignes.append(
            f'\t(segment (start {x1} {y1}) (end {x2} {y2}) '
            f'(width 0.25) (layer "F.Cu") (net 1))'
        )
    for i in range(vias):
        lignes.append(f'\t(via (at {i} {i}) (size 0.6) (drill 0.3) (net 1))')
    lignes.append(")")
    return "\n".join(lignes).encode("utf-8")


class TestComptageDesVias:
    def test_compte_les_vias_reellement_presentes(self):
        assert routing_router._count_vias(_board([], vias=7)) == 7

    def test_un_board_sans_via_en_compte_zero(self):
        assert routing_router._count_vias(_board([(0, 0, 1, 0)])) == 0


class TestLongueurDesPistes:
    def test_additionne_la_longueur_des_segments(self):
        # (0,0)->(3,4) = 5 mm ; (0,0)->(0,10) = 10 mm.
        board = _board([(0, 0, 3, 4), (0, 0, 0, 10)])
        assert routing_router._track_length_mm(board) == 15.0

    def test_un_board_sans_piste_mesure_zero(self):
        assert routing_router._track_length_mm(_board([])) == 0.0

    def test_gere_les_coordonnees_negatives(self):
        assert routing_router._track_length_mm(_board([(-3, 0, 0, -4)])) == 5.0


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_chaque_reponse_livrant_un_board_porte_les_mesures(self):
        # Une `RouteAutoResponse` avec un board mais sans mesures rendrait le
        # zéro par défaut — c'est-à-dire un chiffre faux.
        code = self.SOURCE
        blocs = code.count("kicad_pcb_b64=base64.b64encode(new_pcb)")
        mesures = code.count("via_count=_count_vias(")
        assert mesures == blocs, (
            f"{blocs} réponses livrent un board, {mesures} portent les mesures"
        )
        assert code.count("track_length_mm=_track_length_mm(") == blocs
