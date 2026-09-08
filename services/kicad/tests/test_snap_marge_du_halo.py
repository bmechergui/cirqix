"""Le halo protège le canal d'échappement — pas l'espace entre deux voisins.

⚠️ MESURE DU 2026-09-08, sur `examples/carte-04-mcu-minimal`. Le cluster POWER
est correctement détecté — ancre `U1`, plafond 3 mm, les cinq condensateurs de
découplage `C3`…`C7` — et pourtant les cinq restent au-delà :

    C3 3,4   C6 5,5   C7 6,1   C5 9,5   C4 11,4 mm d'écart libre

Rejoué sur le board livré, le snap ne déplace que 3 empreintes et n'amène aucun
membre au plafond. Sur une carte occupée à 30 %.

CAUSE. `marge` sert DEUX choses différentes dans `_cible_libre` :

  1. l'écart radial à l'ANCRE — c'est le halo d'escape, 5 mm sur un boîtier
     fine-pitch, et c'est son rôle : ne pas reboucher le canal de sortie ;
  2. le dégagement exigé de TOUS LES AUTRES composants, via
     `_libre(boite, obstacles, marge)` — et là, rien ne le justifie.

Entre deux condensateurs 0603, la marge normale est `_MARGE_MM` = 0,3 mm. En
imposant 5 mm, l'anneau proche de l'ancre devient inhabitable dès qu'un autre
membre du cluster s'y trouve — et ils y sont tous, par construction. La
recherche pousse alors vers l'extérieur, et rend 6,5 ou 8 mm là où 5 suffisait.

⚠️ CE N'EST PAS UN ARBITRAGE DE SEUIL. Le plafond POWER (3 mm) et le halo
(5 mm) restent inchangés : sur une ancre fine-pitch le plancher atteignable
reste le halo, et c'est assumé — la routabilité prime, un seul LQFP-48 portant
20 à 28 % des échecs de connexion. On corrige seulement une marge appliquée là
où elle n'a rien à protéger.

⚠️ Et ce n'est pas la contradiction arithmétique que j'avais crue d'abord —
celle-là a déjà été réfutée dans `test_snap_cherche_assez_loin.py` : le plafond
décide seulement s'il faut ESSAYER, le déplacement est accepté dès qu'il
AMÉLIORE.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from kicad_tools.schema.pcb import PCB  # noqa: E402

from test_placement_bypass_snap import (  # noqa: E402
    _BOARD_H_MM, _BOARD_W_MM, _cap_sexp, _ic_sexp,
)
from tools import placement_bypass as PB  # noqa: E402


def _board(tmp_path: Path) -> Path:
    """`U1` au centre, un voisin `C9` collé contre l'anneau, `C1` au loin.

    `C9` occupe l'anneau proche : avec 5 mm exigés de LUI aussi, plus rien
    n'est libre à 5 mm de l'ancre, et la recherche part au large.
    """
    pcb = PCB.create(width=_BOARD_W_MM, height=_BOARD_H_MM, layers=2)
    ox, oy = pcb.board_origin
    chemin = tmp_path / "halo.kicad_pcb"
    pcb.save(str(chemin))
    texte = chemin.read_text(encoding="utf-8")
    fin = texte.rstrip().rfind(")")
    inject = _ic_sexp("U1", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb1", ox + 20.0, oy + 20.0)
    inject += _cap_sexp("C1", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb2", ox + 45.0, oy + 20.0)
    inject += _cap_sexp("C9", "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbb3", ox + 27.0, oy + 20.0)
    chemin.write_text(texte[:fin] + inject + texte[fin:], encoding="utf-8")
    return chemin


def _cible(pcb, ref: str, marge_voisins):
    fp = next(f for f in pcb.footprints if f.reference == ref)
    ancre = next(f for f in pcb.footprints if f.reference == "U1")
    acx, acy, ahw, ahh = PB._centre_et_demi(ancre)
    mcx, mcy, _, _ = PB._centre_et_demi(fp)
    dx, dy = mcx - acx, mcy - acy
    d = (dx * dx + dy * dy) ** 0.5
    return PB._cible_libre(
        pcb, fp, (acx, acy), (ahw, ahh), (dx / d, dy / d),
        5.0, ref, ecart_actuel=20.0, marge_voisins=marge_voisins,
    )


class TestMargeDesVoisins:
    def test_la_marge_du_halo_ne_s_applique_PAS_aux_voisins(self, tmp_path):
        """La signature accepte une marge de voisinage distincte."""
        pcb = PCB.load(str(_board(tmp_path)))
        assert _cible(pcb, "C1", PB._MARGE_MM) is not None

    def test_exiger_le_halo_de_TOUS_repousse_la_cible(self, tmp_path):
        """Le comportement d'avant, conservé comme témoin.

        Avec 5 mm exigés du voisin `C9` aussi, la cible trouvée est plus loin
        de l'ancre — ou introuvable. C'est ce que la carte 04 subissait.
        """
        pcb = PCB.load(str(_board(tmp_path)))
        ancre = next(f for f in pcb.footprints if f.reference == "U1")
        acx, acy, _, _ = PB._centre_et_demi(ancre)

        proche = _cible(pcb, "C1", PB._MARGE_MM)
        large = _cible(pcb, "C1", 5.0)
        assert proche is not None

        def rayon(p):
            return ((p[0] - acx) ** 2 + (p[1] - acy) ** 2) ** 0.5

        # Le témoin doit être STRICTEMENT moins bon — sinon ce test ne mesure
        # rien et passerait même si le correctif était absent.
        assert large is None or rayon(large) > rayon(proche)

    def test_le_defaut_reste_l_ancien_comportement(self, tmp_path):
        """Sans l'argument, rien ne change pour les appelants existants."""
        pcb = PCB.load(str(_board(tmp_path)))
        fp = next(f for f in pcb.footprints if f.reference == "C1")
        ancre = next(f for f in pcb.footprints if f.reference == "U1")
        acx, acy, ahw, ahh = PB._centre_et_demi(ancre)
        mcx, mcy, _, _ = PB._centre_et_demi(fp)
        dx, dy = mcx - acx, mcy - acy
        d = (dx * dx + dy * dy) ** 0.5
        # MEME direction des deux cotes : sans cela on comparerait deux
        # recherches differentes, et le test ne dirait rien du defaut.
        sans = PB._cible_libre(pcb, fp, (acx, acy), (ahw, ahh), (dx / d, dy / d),
                               5.0, "C1", ecart_actuel=20.0)
        avec = _cible(pcb, "C1", 5.0)
        assert sans == avec


class TestCablage:
    def test_le_snap_passe_bien_la_marge_ordinaire_aux_voisins(self):
        """Une règle correcte jamais appelée est indistinguable d'une absente."""
        import inspect
        src = inspect.getsource(PB.snap_cluster_members)
        assert "marge_voisins=" in src, (
            "le snap impose encore la marge du halo a tous les voisins")
