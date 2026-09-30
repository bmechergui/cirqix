"""La preparation d'un tirage n'est calculee qu'une fois par board.

Mesure du 2026-09-29, carte-09 : 24 a 101 s de preparation par tirage (plan
coule et rempli, vias reserves, liaison GND verifiee par deux DRC), refaite a
chaque tirage d'un meme palier alors que le board place et le nombre de
couches ne changent pas. Toutes ces etapes sont deterministes : memes octets
en entree, meme resultat. On les memorise pendant UN appel, cle = empreinte
du board d'entree — jamais d'un appel a l'autre.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from routers import routing as R  # noqa: E402


def test_meme_board_meme_etape_calcule_une_fois():
    memo = R._MemoPreparation()
    appels = []
    calcul = lambda: appels.append(1) or b"PLAN"  # noqa: E731
    assert memo.obtenir("plan", b"BOARD", 2, calcul) == b"PLAN"
    assert memo.obtenir("plan", b"BOARD", 2, calcul) == b"PLAN"
    assert len(appels) == 1 and memo.reutilises == 1


def test_autre_board_ou_autre_palier_recalcule():
    memo = R._MemoPreparation()
    appels = []
    calcul = lambda: appels.append(1) or b"X"  # noqa: E731
    memo.obtenir("plan", b"A", 2, calcul)
    memo.obtenir("plan", b"B", 2, calcul)
    memo.obtenir("plan", b"A", 4, calcul)
    memo.obtenir("liaison", b"A", 2, calcul)
    assert len(appels) == 4 and memo.reutilises == 0


def test_une_liste_rendue_est_une_copie():
    memo = R._MemoPreparation()
    premiere = memo.obtenir("vias", b"A", (), lambda: [{"x": 1}])
    premiere.append({"x": 2})
    premiere[0]["x"] = 99
    assert memo.obtenir("vias", b"A", (), lambda: None) == [{"x": 1}]


def test_route_auto_memorise_les_etapes_couteuses_par_appel():
    src = inspect.getsource(R.route_auto)
    assert "memo_prep = _MemoPreparation()" in src, "un memo PAR APPEL"
    import re
    for etape in ("plan", "vias_plan", "vias_signaux", "vias_gnd", "liaison"):
        assert re.search(r'memo_prep\.obtenir\(\s*"%s"' % etape, src), etape
    assert "_MemoPreparation()" not in inspect.getsource(R).split("def route_auto")[0] \
        .split("class _MemoPreparation")[0], "jamais un memo de module"
