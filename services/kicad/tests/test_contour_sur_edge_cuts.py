"""Le contour de la carte doit être sur `Edge.Cuts`, pas sur un numéro périmé.

⚠️ MESURE DU 2026-09-09 sur `examples/carte-05-capteur-i2c`. Les quatre
segments du contour étaient écrits sur **`In21.Cu`** — une couche que le board,
qui n'en a que deux, ne déclare même pas.

    (gr_line (start 0 0)  (end 70 0)  (layer "In21.Cu"))
    (gr_line (start 0 50) (end 0 0)   (layer "In21.Cu"))

**La carte n'avait aucun contour.**

La cause tient en un nombre :

    KiCad ≤ 7    Edge.Cuts = 44
    KiCad 10     Edge.Cuts = 25   ·   44 = une couche interne

`tools/pcb.py` écrivait `edge_layer = 44  # Edge.Cuts`. Le commentaire disait
l'intention, le nombre disait autre chose, et `SetLayer(44)` est parfaitement
valide — il pose simplement le contour ailleurs. Rien ne pouvait le signaler.

Conséquences, toutes deux comptées comme des **erreurs de fabrication** :

    invalid_outline          1    il n'y a RIEN sur Edge.Cuts
    item_on_disabled_layer   4    les quatre segments, orphelins

⚠️ **ET LA CARTE SORTAIT « 100 % ROUTÉE » QUAND MÊME.** Le routeur travaille sur
les pastilles, pas sur la forme du board : l'absence de contour ne l'arrête pas.
C'est ce qui a masqué le défaut — encore une absence qui se lit comme un succès,
la même famille que le composant manquant et le net orphelin.

⚠️ C'est aussi le douzième piège de FORME de ce projet, et le second qui vient
d'un changement entre versions de KiCad, après `(net 3 "GND")` / `(net "GND")`.
Quand une valeur dépend de la version, on demande à la bibliothèque au lieu de
la coder.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))


def _code_seul(objet) -> str:
    """Le code, sans commentaires ni docstrings.

    ⚠️ Une garde qui lit le source brut trouve les phrases de la documentation —
    y compris celles qui citent la valeur interdite pour l'expliquer. Piège déjà
    payé deux fois dans ce dépôt.
    """
    import ast
    arbre = ast.parse(inspect.getsource(objet))
    for noeud in ast.walk(arbre):
        if isinstance(noeud, (ast.Module, ast.ClassDef, ast.FunctionDef,
                              ast.AsyncFunctionDef)):
            if ast.get_docstring(noeud) is not None:
                noeud.body = noeud.body[1:] or [ast.Pass()]
    return ast.unparse(arbre)


class TestLeNumeroNEstPlusCodeEnDur:
    def test_le_generateur_demande_la_couche_a_pcbnew(self):
        from tools import pcb as P
        code = _code_seul(P)
        assert 'getattr(pcbnew, "Edge_Cuts"' in code or \
               "getattr(pcbnew, 'Edge_Cuts'" in code, (
            "le numero de couche du contour n est pas demande a la bibliotheque")

    def test_le_numero_de_KiCad_7_a_DISPARU_du_code(self):
        """⚠️ 44 designe une couche INTERNE en KiCad 10 : le garder reviendrait
        a reintroduire le defaut sur la prochaine carte generee."""
        from tools import pcb as P
        code = _code_seul(P)
        assert not re.search(r"edge_layer\s*=\s*44\b", code), (
            "le numero perime de KiCad 7 est encore ecrit en dur")

    def test_le_repli_prend_la_valeur_de_KiCad_10(self):
        """Se tromper de couche coûte deux erreurs de fabrication ; un repli
        doit donc viser la version installée, pas l'ancienne."""
        from tools import pcb as P
        source = inspect.getsource(P)
        i = source.find('getattr(pcbnew, "Edge_Cuts"')
        assert i > 0
        suite = source[i:i + 900]
        assert "= 25" in suite, "le repli ne vise pas Edge.Cuts de KiCad 10"
        assert "logger.error" in suite, (
            "un repli silencieux laisserait croire le contour bien place")


class TestUnBoardLIVRE:
    """⚠️ Une fixture dit ce qu'on a imaginé ; un board dit ce qui est."""

    def _boards(self):
        for d in sorted((_SERVICE / "examples").glob("carte-*")):
            b = d / "expected" / "final.kicad_pcb"
            if b.is_file():
                yield d.name, b

    def test_chaque_board_livre_a_un_contour_sur_Edge_Cuts(self):
        sans = []
        for nom, b in self._boards():
            t = b.read_text(encoding="utf-8", errors="replace")
            # Un contour, c'est de la GEOMETRIE sur Edge.Cuts — pas seulement
            # la ligne qui declare la couche dans la table.
            geometrie = re.findall(
                r'\(gr_(?:line|rect|arc|poly|circle)\b[\s\S]{0,600}?'
                r'\(layer "Edge\.Cuts"\)', t)
            if not geometrie:
                sans.append(nom)
        assert not sans, "board(s) SANS CONTOUR : %s" % ", ".join(sans)

    def test_aucun_board_ne_pose_d_objet_sur_une_couche_non_declaree(self):
        fautifs = []
        for nom, b in self._boards():
            t = b.read_text(encoding="utf-8", errors="replace")
            declarees = set(re.findall(
                r'\(\d+ "([^"]+)" (?:signal|user|power|mixed|jumper)', t))
            citees = set(re.findall(r'\(layer "([^"]+)"\)', t))
            # `*.Cu` est un joker legitime (traversants), jamais une couche.
            orphelines = {c for c in citees - declarees if not c.startswith("*")}
            if orphelines:
                fautifs.append("%s -> %s" % (nom, ", ".join(sorted(orphelines))))
        assert not fautifs, "objets sur couche non declaree : %s" % " · ".join(fautifs)
