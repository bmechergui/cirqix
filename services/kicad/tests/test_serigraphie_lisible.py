"""La sérigraphie ne doit ni chevaucher, ni être effacée pour faire taire le DRC.

⚠️ MESURE DU 2026-09-08, sur les captures de l'utilisateur : « 33R6 »,
« 100C2 », « LED D2 » superposés. `carte-07`, pourtant livrée à 100 % routé et
**zéro erreur DRC**, porte 118 violations :

    silk_over_copper : 82      le texte est posé sur du cuivre exposé
    silk_overlap     : 36      deux textes se recouvrent

Aucune n'est une erreur de fabrication. Mais c'est la première chose qu'un
relecteur voit, et c'est ce qui a fait dire « placement d'amateur ».

⚠️ DEUX CAUSES DISTINCTES, ET J'AI COMMENCÉ PAR LA PLUS PETITE.

    les TEXTES de référence          11 sur 11 dégagés par `degager_references`
    les CONTOURS des empreintes      l'essentiel du compte

Ma sonde géométrique annonçait « 0 chevauchement » sur `carte-08` quand le DRC
en comptait 112 : elle ne regardait que les textes. Le gros vient des contours
de sérigraphie qui traversent leurs propres pastilles — normal dans toute
bibliothèque KiCad, et cela se traite au TRACÉ (`subtractmaskfromsilk`), pas en
déplaçant des traits.

⚠️ CE QU'ON S'INTERDIT. Réduire la taille du texte est la première suggestion de
`kicad-tools` (`_suggest_silk_overlap`) et elle se retourne contre le but : une
référence illisible sur la carte fabriquée ne vaut pas mieux qu'une référence
superposée. Pousser la référence en `F.Fab` ferait disparaître la violation du
DRC en emportant l'information avec elle. **Faire taire une garde n'est pas la
satisfaire.**
"""
from __future__ import annotations

import inspect
import math
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from tools import serigraphie as S  # noqa: E402


class _Texte:
    def __init__(self, position, hauteur=1.0, text_type="reference",
                 layer="F.SilkS", hidden=False):
        self.position, self.font_height = position, hauteur
        self.text_type, self.layer, self.hidden = text_type, layer, hidden


class _Pad:
    def __init__(self, position, size):
        self.position, self.size = position, size


class _Fp:
    def __init__(self, reference, position, textes, pads=(), rotation=0.0, graphics=()):
        self.reference, self.position = reference, position
        self.texts, self.pads, self.rotation = textes, list(pads), rotation
        self.graphics = list(graphics)


class _Pcb:
    def __init__(self, footprints):
        self.footprints = footprints
        self.deplacements = {}

    def move_reference(self, reference, absolute=None, **_):
        for fp in self.footprints:
            if fp.reference == reference:
                for t in fp.texts:
                    if t.text_type == "reference":
                        t.position = absolute
                self.deplacements[reference] = absolute
                return True
        return False


def _deux_refs_superposees():
    """R1 et R2 posent leur référence exactement au même endroit."""
    return _Pcb([
        _Fp("R1", (10.0, 10.0), [_Texte((0.0, 0.0))]),
        _Fp("R2", (10.0, 10.0), [_Texte((0.0, 0.0))]),
    ])


class TestDetection:
    def test_deux_references_au_meme_endroit_sont_vues(self):
        assert S.compter_chevauchements(_deux_refs_superposees())[1] == 1

    def test_une_reference_sur_une_pastille_est_vue(self):
        pcb = _Pcb([_Fp("R1", (0.0, 0.0), [_Texte((0.0, 0.0))],
                        pads=[_Pad((0.0, 0.0), (2.0, 2.0))])])
        assert S.compter_chevauchements(pcb)[0] == 1

    def test_une_reference_MASQUEE_n_est_pas_comptee(self):
        pcb = _Pcb([_Fp("R1", (0.0, 0.0), [_Texte((0.0, 0.0), hidden=True)],
                        pads=[_Pad((0.0, 0.0), (2.0, 2.0))])])
        assert S.compter_chevauchements(pcb)[0] == 0

    def test_un_texte_sur_F_Fab_n_est_pas_de_la_serigraphie(self):
        """La couche de fabrication ne s'imprime pas."""
        pcb = _Pcb([_Fp("R1", (0.0, 0.0),
                        [_Texte((0.0, 0.0), layer="F.Fab")],
                        pads=[_Pad((0.0, 0.0), (2.0, 2.0))])])
        assert S.compter_chevauchements(pcb)[0] == 0

    def test_la_ROTATION_du_boitier_deplace_son_texte(self):
        """⚠️ L'oublier place correctement les boîtiers à 0° et décale tous les
        autres — un défaut qui ne se voit que sur les cartes denses."""
        droit = S._absolu(_Fp("R1", (0.0, 0.0), [], rotation=0.0), 0.0, -2.0)
        tourne = S._absolu(_Fp("R1", (0.0, 0.0), [], rotation=90.0), 0.0, -2.0)
        assert droit != tourne
        # ⚠️ Convention KiCad (y vers le bas, rotation antihoraire) : un texte
        # AU-DESSUS d un boitier a 0 degre passe A GAUCHE a 90 degres. Mesure
        # du 2026-09-12 : C60 a 90 degres, texte local (0, -1,43), vu par le
        # DRC a x - 1,43. Ce test exigeait +2,0 — il encodait le miroir.
        assert math.isclose(tourne[0], -2.0, abs_tol=1e-6)
        assert math.isclose(tourne[1], 0.0, abs_tol=1e-6)


class TestTexteAPlat:
    """KiCad dessine la reference A PLAT quel que soit l angle du boitier
    (mesure SVG du 2026-09-12) : la boite ne tourne pas avec lui."""

    def _c60(self):
        # 0603 tournee de 90 : pastilles en y (±0,775), reference a 1,43 mm
        # a gauche, texte horizontal de 3 caracteres — il touche la pastille.
        pads = [_Pad((-0.775, 0.0), (0.9, 1.0)), _Pad((0.775, 0.0), (0.9, 1.0))]
        return _Pcb([_Fp("C60", (148.5, 97.0), [_Texte((0.0, -1.43))],
                         pads=pads, rotation=90.0)])

    def test_la_boite_ne_tourne_pas_avec_le_boitier(self):
        b = S.boites_des_references(self._c60())["C60"]
        assert b[2] - b[0] > b[3] - b[1], "le texte est a plat, plus large que haut"

    def test_une_reference_sur_ses_propres_pastilles_est_vue(self):
        assert S.compter_chevauchements(self._c60())[0] == 1

    def test_et_degagee(self):
        pcb = self._c60()
        assert S.degager_references(pcb) == 1
        assert S.compter_chevauchements(pcb)[0] == 0

    def test_la_largeur_par_caractere_est_celle_mesuree(self):
        assert S._LARGEUR_PAR_CARACTERE >= 1.0


class _Trait:
    def __init__(self, start, end, layer="F.SilkS"):
        self.start, self.end, self.layer = start, end, layer
        self.points, self.stroke_width, self.graphic_type = [], 0.12, "line"


class TestContoursDeSerigraphie:
    """La reference d une LED posee sur le CONTOUR de la resistance voisine :
    16 des 24 chevauchements restants de carte-10 (2026-09-12)."""

    def _rangee(self):
        r = _Fp("R1", (0.0, 0.0), [_Texte((0.0, -3.0))],
                graphics=[_Trait((-0.8, -0.7), (0.8, -0.7)), _Trait((-0.8, 0.7), (0.8, 0.7))])
        d = _Fp("D1", (0.0, 4.0), [_Texte((0.0, -4.7))])  # texte a y=-0.7 : sur le trait de R1
        return _Pcb([r, d])

    def test_le_contour_est_un_obstacle(self):
        assert S._obstacles_serigraphie(self._rangee())

    def test_une_reference_sur_un_contour_voisin_est_vue_et_degagee(self):
        pcb = self._rangee()
        assert S.compter_chevauchements(pcb)[0] >= 1
        assert S.degager_references(pcb) >= 1
        assert S.compter_chevauchements(pcb)[0] == 0


class TestCablage:
    def test_auto_place_degage_la_serigraphie_en_dernier(self):
        src = (_SERVICE / "tools" / "placement.py").read_text(encoding="utf-8")
        i = src.index("_degager_la_serigraphie(out)")
        assert "aligner_sur_grille(" in src[:i], "la serigraphie vient APRES la grille"
        assert "degager_references" in src


class TestDegagement:
    def test_un_chevauchement_est_RESOLU(self):
        pcb = _deux_refs_superposees()
        assert S.compter_chevauchements(pcb)[1] == 1
        S.degager_references(pcb)
        assert S.compter_chevauchements(pcb)[1] == 0

    def test_une_reference_DEJA_BIEN_PLACEE_n_est_pas_touchee(self):
        """Un correctif qui « améliore » ce qui va déjà bien est une régression
        déguisée — même règle que le snap, pour la même raison."""
        pcb = _Pcb([_Fp("R1", (0.0, 0.0), [_Texte((0.0, -3.0))]),
                    _Fp("R2", (20.0, 20.0), [_Texte((0.0, -3.0))])])
        assert S.degager_references(pcb) == 0
        assert pcb.deplacements == {}

    def test_sans_place_libre_on_LAISSE_EN_PLACE(self):
        """Un texte déplacé au hasard chevauche autant et ne désigne plus son
        composant."""
        pads = [_Pad((x, y), (40.0, 40.0)) for x in (0.0,) for y in (0.0,)]
        pcb = _Pcb([_Fp("R1", (0.0, 0.0), [_Texte((0.0, 0.0))], pads=pads)])
        assert S.degager_references(pcb) == 0


def _code_seul(module) -> str:
    """Le CODE du module, sans ses commentaires ni ses docstrings.

    ⚠️ Une garde qui lit `inspect.getsource` brut trouve les phrases de la
    DOCUMENTATION. La mienne a echoue sur sa propre docstring — « on ne pousse
    pas la reference en F.Fab » contient litteralement `F.Fab`. C est le piege
    de l ancrage sur une phrase qu on vient d ecrire, deja inscrit dans ce depot
    le 2026-09-08 pour `test_references_stables.py`. On retire donc les deux.
    """
    import ast
    arbre = ast.parse(inspect.getsource(module))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
            if ast.get_docstring(noeud) is not None:
                noeud.body = noeud.body[1:] or [ast.Pass()]
    return ast.unparse(arbre)


class TestOnNeFaitPasTaireLaGarde:
    def test_on_ne_reduit_JAMAIS_la_taille_du_texte(self):
        code = _code_seul(S)
        for interdit in ("font_height =", "font_size =", "set_silkscreen_font"):
            assert interdit not in code, (
                "la taille du texte est modifiee : une reference illisible ne "
                "vaut pas mieux qu une reference superposee")

    def test_on_ne_pousse_JAMAIS_la_reference_en_F_Fab(self):
        code = _code_seul(S)
        assert "F.Fab" not in code and "layer=" not in code, (
            "la reference est deplacee vers une couche non imprimee — la "
            "violation disparait avec l information")


class TestCablageDeLExport:
    def test_l_export_retire_la_serigraphie_du_cuivre_expose(self):
        """⚠️ La cause principale se traite au TRACÉ, pas au placement.

        Nos boards portent `subtractmaskfromsilk no` : mesuré le 2026-09-09.
        """
        source = (_SERVICE / "tools" / "export.py").read_text(encoding="utf-8")
        code = "\n".join(l.split("#")[0] for l in source.splitlines())
        assert "SetSubtractMaskFromSilk(True)" in code, (
            "la serigraphie n est pas decoupee au trace des Gerbers")

    def test_une_indisponibilite_est_DITE(self):
        source = (_SERVICE / "tools" / "export.py").read_text(encoding="utf-8")
        i = source.index("SetSubtractMaskFromSilk")
        assert "logger.error" in source[i:i + 700], (
            "un reglage absent passerait en silence, et le defaut ne se "
            "verrait qu a la fabrication")
