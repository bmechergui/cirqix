"""Graine EN ETOILE : chaque peripherique part du cote de la broche qu il relie.

⚠️ Mesures du 2026-09-21 sur le banc. Le placement tire au hasard (strategie
`hybrid`) rend, sur le MEME circuit, 351 a 681 croisements du chevelu
(carte-10, cinq placements) ; les connexions qui manquent ensuite sont les
signaux qui partent du microcontroleur. Des forces locales ne demelent jamais
un chevelu deja croise.

La graine est CALCULEE, pas tiree : boitier central au milieu, chaque
connecteur contre le bord du cote de ses broches, chaque peripherique sur le
rayon de sa broche, les suivants derriere celui qu ils prolongent.

    croisements   carte-08  406 -> 73     carte-09  483 -> 109    carte-10  564 -> 119
    routage GELE de la graine brute : 07, 08, 09, 10 a 100 %, 0 erreur, 0 manquante
    (placement actuel le meme jour : 2, 8, 11 manquantes ; carte-10 sur 6 couches
    contre 2 avec la graine)

Aucune carte nommee. Reglage de banc `graine_etoile`, DESARME par defaut.
"""
from __future__ import annotations

import math
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

from tools import graine_etoile as G  # noqa: E402


def _pad(net, x, y):
    return SimpleNamespace(net_name=net, position=(x, y), number="1")


def _fp(ref, pads, pos=(0.0, 0.0), demi=(0.8, 0.5), rot=0.0):
    g = SimpleNamespace(layer="F.CrtYd", start=(-demi[0], -demi[1]), end=(demi[0], demi[1]))
    return SimpleNamespace(reference=ref, pads=pads, position=pos, rotation=rot, graphics=[g])


def _mcu(ref="U1", pos=(0.0, 0.0), nets=("A", "B", "C", "D")):
    # 8 pastilles : une par cote porte un signal, les autres la masse.
    a, b, c, d = nets
    pads = [_pad(a, 4.0, 0.0), _pad(b, -4.0, 0.0), _pad(c, 0.0, 4.0), _pad(d, 0.0, -4.0),
            _pad("GND", 4.0, 1.0), _pad("GND", -4.0, 1.0), _pad("GND", 1.0, 4.0), _pad("GND", 1.0, -4.0)]
    return _fp(ref, pads, pos=pos, demi=(4.5, 4.5))


BORNES = (0.0, 60.0, 0.0, 60.0)


class TestUnCentre:
    def test_le_peripherique_part_du_cote_de_sa_broche(self):
        fps = [_mcu(), _fp("R1", [_pad("A", -0.5, 0), _pad("X", 0.5, 0)]),
               _fp("R2", [_pad("B", -0.5, 0), _pad("Y", 0.5, 0)])]
        pos, centres = G.calculer(fps, connecteurs=[], contour=BORNES)
        assert centres == ["U1"]
        cx, cy = pos["U1"]
        assert pos["R1"][0] > cx, "la broche A est a DROITE du boitier"
        assert pos["R2"][0] < cx, "la broche B est a GAUCHE"

    def test_le_suivant_se_range_derriere_celui_qu_il_prolonge(self):
        fps = [_mcu(), _fp("R1", [_pad("A", -0.5, 0), _pad("X", 0.5, 0)]),
               _fp("D1", [_pad("X", -0.5, 0), _pad("GND", 0.5, 0)])]
        pos, _ = G.calculer(fps, connecteurs=[], contour=BORNES)
        cx, cy = pos["U1"]
        r1 = math.hypot(pos["R1"][0] - cx, pos["R1"][1] - cy)
        d1 = math.hypot(pos["D1"][0] - cx, pos["D1"][1] - cy)
        assert d1 > r1 and pos["D1"][0] > cx

    def test_le_connecteur_va_au_bord_du_cote_de_ses_broches(self):
        fps = [_mcu(), _fp("J1", [_pad("C", 0, 0), _pad("GND", 0, 2.54)], pos=(5.0, 5.0), demi=(1.8, 3.0))]
        pos, _ = G.calculer(fps, connecteurs=["J1"], contour=BORNES)
        assert pos["J1"][1] > 45.0, "la broche C est en BAS (y descend) : bord bas"

    def test_rien_ne_se_recouvre(self):
        fps = [_mcu()] + [_fp(f"R{i}", [_pad("A", -0.5, 0), _pad(f"N{i}", 0.5, 0)]) for i in range(8)]
        pos, _ = G.calculer(fps, connecteurs=[], contour=BORNES)
        boites = [(pos[f.reference][0] - 0.8, pos[f.reference][1] - 0.5,
                   pos[f.reference][0] + 0.8, pos[f.reference][1] + 0.5) for f in fps[1:]]
        for i, a in enumerate(boites):
            for b in boites[i + 1:]:
                assert a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]


class TestCouloirDeSortie:
    """⚠️ Regression mesuree le 2026-09-21 : carte-03 (boitier central de 8 broches)
    sortait a 3 erreurs et 7 connexions manquantes, tous les tirages figes a 12 %
    ou moins, placement classe « condamne » par le routeur. La graine collait
    les peripheriques a 0,4 mm du boitier : aucune place pour SORTIR les pistes.
    Les cartes denses ne le montraient pas — le halo existant ecarte deja les
    voisins des boitiers de 16 broches et plus.

    Le couloir se DEDUIT des regles de trace : signaux a sortir par cote x pas
    de routage (piste 0,25 + degagement 0,2) + un degagement."""

    def test_le_couloir_croit_avec_les_signaux_a_sortir(self):
        petit = _mcu(nets=("A", "B", "C", "D"))
        gros = _mcu(nets=("A", "B", "C", "D"))
        gros.pads.extend(_pad(f"S{i}", 4.0, 0.1 * i) for i in range(32))
        assert G.couloir_mm(petit) == pytest.approx(1 * 0.45 + 0.2)
        assert G.couloir_mm(gros) == pytest.approx(9 * 0.45 + 0.2)

    def test_aucun_peripherique_dans_le_couloir_du_centre(self):
        u1 = _mcu()
        fps = [u1] + [_fp(f"R{i}", [_pad(n, -0.5, 0), _pad(f"N{i}", 0.5, 0)])
                      for i, n in enumerate(("A", "B", "C", "D"))]
        pos, _ = G.calculer(fps, connecteurs=[], contour=BORNES)
        cx, cy = pos["U1"]
        couloir = G.couloir_mm(u1)
        for i in range(4):
            x, y = pos[f"R{i}"]
            ecart = max(abs(x - cx) - 0.8, abs(y - cy) - 0.5) - 4.5
            assert ecart >= couloir - 1e-6, f"R{i} est a {ecart:.2f} mm du boitier"


class TestPetiteCarte:
    """⚠️ carte-03, 28 x 20 mm : le connecteur colle au bord FACE a ses broches
    mordait sur l emprise du centre — le collage n evitait que les autres
    connecteurs. Conflit que rien ne resolvait (le centre etait « le mobile »)."""

    def test_le_connecteur_evite_l_emprise_et_le_couloir_du_centre(self):
        u1 = _mcu()
        j1 = _fp("J1", [_pad("D", 0, 0), _pad("GND", 0, 2.54)], pos=(3.0, 3.0), demi=(1.8, 3.2))
        pos, _ = G.calculer([u1, j1], connecteurs=["J1"], contour=(0.0, 40.0, 0.0, 17.0))
        cx, cy = pos["U1"]
        x, y = pos.get("J1", j1.position)
        ecart_x = max(abs(x - cx) - 1.8 - 4.5, 0.0)
        ecart_y = max(abs(y - cy) - 3.2 - 4.5, 0.0)
        assert max(ecart_x, ecart_y) >= G.couloir_mm(u1) - 1e-6


class TestAucunEchecSilencieux:
    """Avis de GLM, 2026-09-21, et il a raison : quand aucune place libre n existe
    sur un rayon, le composant restait a sa position d origine SANS UN MOT —
    « un echec rend la meme valeur que son cas normal », la faute que ce depot
    traque partout. Le calcul rend desormais les refs qu il n a PAS su poser."""

    def test_les_composants_sans_place_sont_nommes(self):
        # Carte minuscule : le centre tient, les huit resistances non.
        fps = [_mcu()] + [_fp(f"R{i}", [_pad("A", -0.5, 0), _pad(f"N{i}", 0.5, 0)], pos=(99.0, 99.0))
                          for i in range(8)]
        pos, centres, sans_place = G.calculer(fps, connecteurs=[], contour=(0.0, 14.0, 0.0, 14.0),
                                              avec_echecs=True)
        assert centres == ["U1"]
        assert sans_place, "aucune place sur 14 x 14 : il faut le DIRE"
        assert all(r not in pos for r in sans_place)


class TestPlusieursCentres:
    def test_chaque_peripherique_rejoint_SON_boitier(self):
        u2 = _mcu("U2", nets=("P", "Q", "R", "LIEN"))
        u1 = _mcu("U1", nets=("A", "B", "C", "LIEN"))
        u1.pads.extend(_pad("GND", 2.0 + i * 0.1, 4.0) for i in range(4))      # U1 est le plus gros
        fps = [u1, u2, _fp("R1", [_pad("A", -0.5, 0), _pad("X", 0.5, 0)]),
               _fp("R9", [_pad("P", -0.5, 0), _pad("Z", 0.5, 0)])]
        pos, centres = G.calculer(fps, connecteurs=[], contour=(0.0, 90.0, 0.0, 90.0))
        assert centres == ["U1", "U2"]
        d = lambda a, b: math.hypot(pos[a][0] - pos[b][0], pos[a][1] - pos[b][1])  # noqa: E731
        assert d("R1", "U1") < d("R1", "U2")
        assert d("R9", "U2") < d("R9", "U1")


class TestSansCentre:
    def test_un_circuit_sans_boitier_de_huit_broches_n_est_pas_touche(self):
        fps = [_fp("R1", [_pad("A", -0.5, 0), _pad("B", 0.5, 0)]),
               _fp("R2", [_pad("B", -0.5, 0), _pad("GND", 0.5, 0)])]
        assert G.calculer(fps, connecteurs=[], contour=BORNES) == ({}, [])


class TestDesarmeEtCable:
    def test_desarme_par_defaut(self, monkeypatch):
        monkeypatch.setattr("tools.reglages_banc.reglage", lambda nom, defaut: defaut)
        assert G.armee() is False

    def test_cablage_avant_l_optimiseur_et_a_sa_place(self):
        source = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
        corps = source[source.index("def _auto_place_une_fois("):]
        graine = corps.index("graine_etoile.poser_sur(")
        assert graine < corps.index("result = workflow.run()")
        assert "if not centres_etoile:" in corps[graine:corps.index("result = workflow.run()")]


class TestLaChaineNeSeBatPasContreLEtoile:
    """⚠️ Mesure du 2026-09-21, carte-03 : graine juste (centre en (14 ; 10) dans
    28 x 20), puis « rangees de paires » reposait les couples R + LED le long
    d un bord — une mise en forme pensee pour le tirage au hasard, qui DEFAIT
    l etoile — et laissait un conflit contre le centre. Quatre tirages
    IDENTIQUES (la graine est calculee), quatre fois le meme conflit, bascule
    sur la couronne de secours : centre a moitie HORS de la carte, 3 erreurs et
    7 connexions manquantes au routage. « L ordre fait partie du correctif. »"""

    SOURCE = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_les_rangees_ne_defont_pas_l_etoile(self):
        corps = self.SOURCE[self.SOURCE.index("def _auto_place_une_fois("):]
        rangees = corps.index("from tools.placement_rangees import ranger_les_paires")
        assert "if not centres_etoile:" in corps[rangees - 400:rangees]

    def test_un_placement_calcule_n_est_pas_retire_a_l_identique(self):
        corps = self.SOURCE[self.SOURCE.index("def auto_place("):self.SOURCE.index("def _resserrer_le_contour(")]
        assert "graine=graine_encore_utile" in corps
        assert 'r.get("centres_etoile")' in corps

    def test_le_resultat_dit_s_il_vient_de_la_graine(self):
        corps = self.SOURCE[self.SOURCE.index("def _auto_place_une_fois("):]
        assert '"centres_etoile": centres_etoile' in corps


class TestLEtoileEstProtegeeApresCoup:
    """Avis convergents de Codex et de GLM (2026-09-21), confirmes par la mesure :
    la graine rend la MEME etoile a chaque appel, mais les finitions decident du
    resultat — croisements apres la chaine, deux passages du meme code a une
    correction pres : carte-09 234 -> 80, carte-08 158 -> 223 (et carte-08 passe
    de 0 a 3 connexions manquantes). « Les garde-fous surveillent les conflits
    DRC et le deplacement du CMA-ES, jamais la non-regression des croisements. »

    Une finition de CONFORT (raffinement, halo, grille) qui remonte les
    croisements d une etoile est annulee. Le rapprochement des decouplages et les
    filets DRC n y sont PAS soumis : regles electriques et de fabricabilite."""

    def test_une_etape_qui_remonte_les_croisements_est_annulee(self, tmp_path, monkeypatch):
        from tools import placement as P
        f = tmp_path / "b.kicad_pcb"; f.write_bytes(b"APRES")
        monkeypatch.setattr(P, "_croisements_du_placement", lambda _: 90.0)
        assert P._proteger_l_etoile(f, b"AVANT", 70.0, "halo") == 70.0
        assert f.read_bytes() == b"AVANT"

    def test_une_etape_qui_les_baisse_est_gardee(self, tmp_path, monkeypatch):
        from tools import placement as P
        f = tmp_path / "b.kicad_pcb"; f.write_bytes(b"APRES")
        monkeypatch.setattr(P, "_croisements_du_placement", lambda _: 60.0)
        assert P._proteger_l_etoile(f, b"AVANT", 70.0, "halo") == 60.0
        assert f.read_bytes() == b"APRES"

    def test_sans_mesure_on_ne_defait_rien(self, tmp_path, monkeypatch):
        from tools import placement as P
        f = tmp_path / "b.kicad_pcb"; f.write_bytes(b"APRES")
        monkeypatch.setattr(P, "_croisements_du_placement", lambda _: None)
        assert P._proteger_l_etoile(f, b"AVANT", 70.0, "halo") == 70.0
        assert f.read_bytes() == b"APRES"

    def test_les_finitions_qui_DEPLACENT_sont_gardees(self):
        source = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
        corps = source[source.index("def _auto_place_une_fois("):]
        for etape in ("raffinement CMA-ES", "halo d escape"):
            assert f'"{etape}")' in corps, etape

    def test_la_grille_en_est_EXEMPTE(self):
        """⚠️ Mesure du 2026-09-21 : le garde-fou annulait la grille de carte-08
        pour TROIS croisements (113 -> 116). `aligner_sur_grille` arrondit au
        demi-millimetre — il deplace de 0,25 mm au plus, ce qui ne peut pas
        re-tisser un chevelu : l ecart mesure est la sensibilite de la
        projection en etoile, pas un emmelement. Et c est l etape qui donne son
        alignement de carte professionnelle. Elle garde sa propre garde (les
        erreurs DRC). Exempter ici n est pas un seuil tolere : c est la nature
        du deplacement qui tranche."""
        source = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
        corps = source[source.index("def _auto_place_une_fois("):]
        assert '_proteger_l_etoile(out, avant_grille' not in corps


class TestLeGrosBoitierPeutEtreUnCentre:
    """Avis de Codex : `_auto_place_une_fois` range les boitiers DOMINANTS avec les
    connecteurs, et la graine exclut les connecteurs des centres — le meilleur
    centre d une carte (un module ESP32) desarmait donc l etoile."""

    def test_les_dominants_ne_sont_pas_passes_comme_connecteurs(self):
        source = (RACINE / "tools" / "placement.py").read_text(encoding="utf-8")
        corps = source[source.index("def _auto_place_une_fois("):]
        appel = corps[corps.index("graine_etoile.poser_sur("):][:160]
        assert "dominants" in appel


BANC = RACINE / "examples" / "carte-08-dense" / "expected" / "placement.kicad_pcb"


@pytest.mark.skipif(shutil.which("kicad-cli") is None,
                    reason="kicad-cli absent : se lance dans le conteneur")
class TestDansLaVraieChaine:
    """⚠️ Les gardes de CABLAGE ci-dessus lisent le SOURCE : elles attrapent un
    deplacement d appel, pas un `if` qui changerait le flot reel. Ici on fait
    tourner `_auto_place_une_fois` sur un vrai board, reglage arme — « une regle
    jamais executee est indistinguable d une regle absente »."""

    def _board(self, tmp_path):
        pytest.importorskip("kicad_tools")
        if not BANC.is_file():
            pytest.skip("board du banc absent")
        import base64
        return base64.b64encode(BANC.read_bytes()).decode()

    def test_la_graine_joue_et_les_rangees_sont_sautees(self, tmp_path, monkeypatch):
        from tools import placement as P
        b64 = self._board(tmp_path)
        monkeypatch.setattr("tools.reglages_banc.reglage",
                            lambda nom, defaut: True if nom == "graine_etoile" else defaut)
        appels = []
        import tools.placement_rangees as PR
        monkeypatch.setattr(PR, "ranger_les_paires",
                            lambda *a, **k: appels.append(a) or 0)
        r = P._auto_place_une_fois(b64, 57.8, 44.0)
        assert r["centres_etoile"], "la graine n a pas joue DANS la chaine"
        assert not appels, "les rangees ont tourne et defont l etoile"
        assert r["conflits_restants"] == 0
        assert r["croisements"] is not None

    def test_desarmee_la_chaine_est_celle_d_avant(self, tmp_path, monkeypatch):
        from tools import placement as P
        b64 = self._board(tmp_path)
        monkeypatch.setattr("tools.reglages_banc.reglage", lambda nom, defaut: defaut)
        r = P._auto_place_une_fois(b64, 57.8, 44.0)
        assert r["centres_etoile"] == []
