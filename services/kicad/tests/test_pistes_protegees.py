"""A l escalade, on PROTEGE les pistes deja routees au lieu de tout refaire.

⚠️ Demande de l utilisateur, et mon objection etait FAUSSE. J avais oppose la
mesure du 2026-08-01 : « le routage incrementiel rend le meme resultat pour
3x le temps ». Cette mesure porte sur `--preserve-existing` de `kct route`.
Or les journaux du 2026-08-31 sont sans appel :

    16 routages effectues :  16 x (freerouting-api)  ·  0 x (kicad-tools)

J ai donc oppose une mesure faite sur un moteur qui n est jamais emprunte.

⚠️ Sur le chemin Freerouting, la perte de cuivre a une cause PRECISE, verifiee
sur un vrai export : le DSN produit par pcbnew porte un bloc `(wiring)` VIDE,
meme quand le board est entierement route. L export ne transmet pas le cuivre —
le routeur ne le detruit pas, il ne le voit jamais.

    (wiring
      )

Le remede est donc d ECRIRE ce bloc nous-memes, exactement comme on le fait
deja pour les vias reserves (`_bloc_wiring`), avec `(type protect)` qui
interdit au routeur d y toucher.

⚠️ Unites verifiees sur l export reel : `(resolution um 10)`, couches `F.Cu` /
`B.Cu` sans guillemets, nets nommes en clair, coordonnees en micrometres avec
UNE decimale, et **Y NEGATIF** — Specctra oriente Y vers le haut, KiCad vers le
bas. C est la transformation deja validee en production par les vias reserves.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402


_BOARD = b"""(kicad_pcb (version 20240108)
  (net 0 "")
  (net 3 "GND")
  (net 7 "SIG1")
  (segment (start 10.0 20.0) (end 30.0 20.0) (width 0.25) (layer "F.Cu") (net 3))
  (segment (start 30.0 20.0) (end 30.0 40.0) (width 0.2) (layer "B.Cu") (net 7))
  (via (at 30.0 20.0) (size 0.6) (drill 0.3) (layers "F.Cu" "B.Cu") (net 7))
)"""


class TestPistes:
    def test_chaque_segment_devient_un_fil_protege(self):
        bloc = R._bloc_wiring_pistes(_BOARD)
        assert bloc.count("(wire") == 2
        assert bloc.count("(type protect)") == 2

    def test_les_coordonnees_sont_en_micrometres_et_Y_est_NEGATIF(self):
        """⚠️ Oublier le signe placerait chaque piste en miroir de sa position —
        un DSN syntaxiquement valide et geometriquement faux."""
        bloc = R._bloc_wiring_pistes(_BOARD)
        assert "10000.0 -20000.0 30000.0 -20000.0" in bloc

    def test_la_largeur_est_en_micrometres(self):
        bloc = R._bloc_wiring_pistes(_BOARD)
        assert "F.Cu 250.0" in bloc      # 0,25 mm
        assert "B.Cu 200.0" in bloc      # 0,20 mm

    def test_le_net_est_NOMME_pas_numerote(self):
        # Le DSN nomme les nets en clair ; un numero y serait un net inconnu,
        # et le routeur relierait des pistes a la mauvaise equipotentielle.
        bloc = R._bloc_wiring_pistes(_BOARD)
        assert "(net GND)" in bloc and "(net SIG1)" in bloc
        assert "(net 3)" not in bloc

    def test_un_board_sans_piste_rend_une_chaine_vide(self):
        assert R._bloc_wiring_pistes(b"(kicad_pcb)") == ""

    def test_un_segment_au_net_INCONNU_est_ECARTE(self):
        """⚠️ Ne jamais deviner un nom de net : une piste rattachee au mauvais
        net est un court-circuit, pas une approximation."""
        board = _BOARD.replace(b'(net 7 "SIG1")\n', b"")
        bloc = R._bloc_wiring_pistes(board)
        assert "SIG1" not in bloc
        assert bloc.count("(wire") == 1

    def test_le_net_ZERO_est_ecarte(self):
        # Net 0 = pas de net. Une piste sans net n a rien a proteger.
        board = _BOARD.replace(b"(net 3))", b"(net 0))")
        assert R._bloc_wiring_pistes(board).count("(wire") == 1


class TestInjection:
    DSN = "(pcb x\n  (wiring\n  )\n)"

    def test_les_pistes_entrent_dans_le_bloc_wiring(self):
        sortie = R._injecter_wiring(self.DSN, [], "GND", pistes=_BOARD)
        assert "(wire" in sortie and "(type protect)" in sortie

    def test_sans_pistes_le_DSN_est_INCHANGE(self):
        assert R._injecter_wiring(self.DSN, [], "GND", pistes=None) == self.DSN

    def test_vias_et_pistes_coexistent(self):
        # Les vias reserves ne doivent pas disparaitre quand on ajoute les
        # pistes : les deux vivent dans le meme bloc.
        vias = [{"via_x": 1_000_000, "via_y": 2_000_000, "net": "GND"}]
        sortie = R._injecter_wiring(self.DSN, vias, "GND", pistes=_BOARD)
        assert "(via" in sortie and "(wire" in sortie


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_meilleur_board_est_PROTEGE_a_l_escalade(self):
        # ⚠️ Une regle jamais appelee est indistinguable d une regle absente.
        assert "_PISTES_A_PROTEGER" in self.SOURCE
        i = self.SOURCE.index("essais = _paliers_avec_tirages(")
        assert "_PISTES_A_PROTEGER" in self.SOURCE[i:i + 6000]

    def test_on_ne_protege_QUE_si_un_meilleur_existe(self):
        i = self.SOURCE.index("essais = _paliers_avec_tirages(")
        corps = self.SOURCE[i:i + 6000]
        j = corps.index("_PISTES_A_PROTEGER =")
        assert "meilleur" in corps[max(0, j - 300):j + 60]


# ⚠️ LA FORME REELLE d un board sorti du routeur, mesuree le 2026-08-31 :
# multi-ligne, indentee par tabulations, et surtout **le net est NOMME, pas
# numerote**. C est le piege KiCad 10 deja documente dans CLAUDE.md —
# `(net 3 "GND")` chez kicad-tools et KiCad <= 9, `(net "GND")` chez pcbnew 10
# — celui qui avait produit le faux diagnostic « Freerouting perd la netlist ».
#
# La premiere version de ce generateur n acceptait que la forme numerotee et
# rendait ZERO fil sur un vrai board : « pistes a proteger : 0 fils ». Les
# douze tests unitaires passaient tous. Seule l execution sur un BOARD REEL l a
# montre — la lecon deja inscrite : une fixture dit ce qu on a imagine, un
# board dit ce qui est.
_BOARD_KICAD10 = b"""(kicad_pcb (version 20240108)
	(segment
		(start 161.4229 149.9686)
		(end 161.9375 149.454)
		(width 0.2)
		(layer "F.Cu")
		(net "LED5")
		(uuid "178649ae-ab84-4a56-8883-21ce23119f97")
	)
)"""


class TestFormeReelle:
    def test_le_net_NOMME_de_kicad_10_est_reconnu(self):
        bloc = R._bloc_wiring_pistes(_BOARD_KICAD10)
        assert bloc.count("(wire") == 1
        assert "(net LED5)" in bloc

    def test_la_forme_multiligne_indentee_est_reconnue(self):
        # Un attribut par ligne, tabulations : c est ainsi que KiCad ecrit.
        assert "161422.9 -149968.6" in R._bloc_wiring_pistes(_BOARD_KICAD10)

    def test_le_uuid_qui_suit_le_net_ne_gene_pas(self):
        assert R._bloc_wiring_pistes(_BOARD_KICAD10).count("(type protect)") == 1


class TestJournal:
    """⚠️ Un message qui n a pas compte peut mentir.

    Le 2026-08-31 au matin, ce mecanisme injectait ZERO fil — le net nomme de
    KiCad 10 — tout en affichant « les pistes du meilleur board sont
    PROTEGEES ». Le message etait rassurant et faux. C est la faute traquee
    toute la session : ne jamais annoncer un travail sans l avoir mesure.
    """

    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_le_nombre_de_fils_est_COMPTE_avant_d_etre_annonce(self):
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        # ⚠️ S ancrer sur le MESSAGE, pas sur la forme de l affectation :
        # celle-ci est passee de `= board` a `= [board]` le 2026-08-31 et la
        # garde s est mise a lever `ValueError` au lieu de mesurer.
        i = corps.index("AUCUNE piste")
        bloc = corps[max(0, i - 1200):i]
        assert "_bloc_wiring_pistes(" in bloc, (
            "on annonce la protection sans avoir compte les fils")

    def test_zero_fil_est_un_AVERTISSEMENT_pas_une_bonne_nouvelle(self):
        corps = self.SOURCE[self.SOURCE.index("def route_auto("):]
        i = corps.index("AUCUNE piste")
        assert "logger.warning" in corps[max(0, i - 400):i]
