"""Le DSN envoyé à Freerouting ne porte jamais deux vias au même point.

Mesure du 2026-09-25, `carte-07`, tirage protégé à 4 couches (Freerouting CLI) :

    board protégé + liaison GND                 0 doublon     7 s    100 %
    + vias réservés                   4 vias au même point   220 s    100 %
    production (tout)                 4 vias au même point  > 240 s   aucune sortie

Trois sources écrivent des vias dans le bloc `(wiring)` : les vias RÉSERVÉS,
le meilleur board du palier précédent (tirage protégé) et la LIAISON GND posée
avant le routage. Elles visent souvent les mêmes pastilles GND. Freerouting
journalise « Multiple vias skipped », ralentit d'un facteur trente, et l'API
finit en HTTP 500.

Règle : une pastille, un seul propriétaire. Un via réservé à moins d'un écart
de trous d'un via déjà protégé est écarté (avec son tronçon) ; deux éléments
protégés identiques ne sont écrits qu'une fois.

Et une fuite d'état, introduite le 2026-09-24 par D-2026-09-24-g et relevée
par la revue du 2026-09-25 : en entrant dans un palier SANS protection voulue,
`_PISTES_A_PROTEGER` gardait la liaison GND du dernier tirage du palier
précédent — sur un autre empilage — et la nouvelle liaison s'y ajoutait.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402

_VIA = '    (via "Via[0-1]_600:300_um" %.1f %.1f (net GND) (type protect))'
_FIL = "    (wire (path F.Cu 250.0 %.1f %.1f %.1f %.1f) (net GND) (type protect))"


def _vias(texte: str) -> list:
    return [(float(x), float(y)) for x, y in
            re.findall(r'\(via\s+"[^"]*"\s+(-?[\d.]+)\s+(-?[\d.]+)', texte)]


class TestDedoublonnage:
    def test_un_via_reserve_sur_un_via_protege_est_ecarte_avec_son_troncon(self):
        reserves = "\n".join([_VIA % (1000.0, -2000.0), _FIL % (800.0, -2000.0, 1000.0, -2000.0)])
        proteges = _VIA % (1000.2, -2000.1)
        r, p, ecartes, doublons = R._dedoublonner_wiring(reserves, proteges)
        assert _vias(r) == [] and "(wire" not in r
        assert ecartes == 1 and doublons == 0
        assert p == proteges

    def test_un_via_reserve_trop_proche_est_ecarte(self):
        """Deux trous à 0,3 mm l'un de l'autre font un `hole_to_hole` : ce n'est
        pas le même point, mais c'est la même pastille."""
        r, _, ecartes, _ = R._dedoublonner_wiring(_VIA % (1000.0, 0.0), _VIA % (1300.0, 0.0))
        assert ecartes == 1 and _vias(r) == []

    def test_un_via_reserve_eloigne_est_garde(self):
        r, _, ecartes, _ = R._dedoublonner_wiring(_VIA % (1000.0, 0.0), _VIA % (3000.0, 0.0))
        assert ecartes == 0 and _vias(r) == [(1000.0, 0.0)]

    def test_deux_elements_proteges_identiques_ne_sont_ecrits_qu_une_fois(self):
        """Le meilleur board ET la liaison GND recalculée portent le même via."""
        proteges = "\n".join([_VIA % (500.0, -500.0), _FIL % (0.0, 0.0, 500.0, -500.0),
                              _VIA % (500.0, -500.0), _FIL % (0.0, 0.0, 500.0, -500.0),
                              _VIA % (500.02, -500.01)])
        _, p, _, doublons = R._dedoublonner_wiring("", proteges)
        assert len(_vias(p)) == 1 and p.count("(wire") == 1
        assert doublons == 3

    def test_rien_a_dedoublonner_rend_les_textes_intacts(self):
        r, p, e, d = R._dedoublonner_wiring(_VIA % (0.0, 0.0), _VIA % (5000.0, 0.0))
        assert (r, p, e, d) == (_VIA % (0.0, 0.0), _VIA % (5000.0, 0.0), 0, 0)


class TestCablage:
    def test_injecter_wiring_dedoublonne_avant_d_ecrire(self):
        code = inspect.getsource(R._injecter_wiring)
        i_ded = code.index("_dedoublonner_wiring(")
        i_join = code.index("bloc = chr(10).join(x for x in (bloc, fils) if x)")
        assert i_ded < i_join

    def test_entrer_dans_un_palier_sans_protection_voulue_efface_la_precedente(self):
        """La chaîne de décision au changement de palier se termine par un
        `else` qui remet la protection à zéro."""
        code = "\n".join(l.split("#")[0] for l in inspect.getsource(R.route_auto).splitlines())
        i = code.index("elif meilleur is not None and meilleur.kicad_pcb_b64 and _escalade_incrementale():")
        j = code.index("palier_courant, meilleur_du_palier = palier, 0", i)
        bloc = code[i:j]
        k = bloc.index("\n            else:")
        assert "_PISTES_A_PROTEGER = None" in bloc[k:k + 300]
        assert "_ZONES_LIBEREES = []" in bloc[k:k + 300]
