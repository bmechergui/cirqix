"""Un composant livré hors du contour Edge.Cuts doit être SIGNALÉ bruyamment.

Défaut trouvé le 2026-07-30 en rejouant la chaîne complète en Docker sur
`examples/stm32-validation` : le placement a livré **U1 à X = 183,37 mm sur une
carte allant de 100 à 160 mm**, soit 23 mm au-delà du bord droit. Le routeur ne
pouvant atteindre un composant hors carte, le net `+5V` (C1 ↔ U1) était
inroutable et le board plafonnait à 64 % au lieu de 100 %. Sur d'autres tirages,
`kct route` refuse carrément le board (« placement invalid »).

Deux garde-fous existaient, aucun ne couvrait ce cas :

- le pré-filtre en tête de ``auto_place`` ne déclenche ``place_unplaced`` qu'à
  ``x < -100`` ou ``y < -100``, la sentinelle « jamais placé » ;
- ``_clamp_fixed_refs_to_outline`` ne clampe que les connecteurs ancrés, et
  seulement AVANT l'optimisation.

Rien ne vérifiait le RÉSULTAT. Le placement étant stochastique (GA sans seed),
le défaut est intermittent — ce qui explique une part de la variance de routage
45-89 % observée sur ce board depuis juillet. Aggravant : ``PlacementFixer``
n'a **aucun** traitement de ``OFF_BOARD`` (zéro occurrence dans ``fixer.py``),
donc l'Inspecteur ne peut structurellement pas le résoudre.

## Pourquoi la réparation n'est pas implémentée

Trois tentatives, toutes rejetées **par la mesure** :

1. **Clamp maison** sur le rectangle du contour : empile tous les fautifs sur le
   même coin. ``test_placement.py`` l'a attrapé via les conflits ERROR créés.
2. **``place_unplaced``**, qui documente pourtant détecter les footprints
   « outside the board bounds » : a signalé 15 composants sur 17, en a reposé 8
   sur une grille locale en laissant les autres en coordonnées page, et a placé
   R2 à x = 61,1 mm sur une carte de 60 mm — le défaut même à corriger.
3. **Réparation ciblée + Inspecteur en boucle** : converge (14 → 5 → 3) mais
   n'atteint pas zéro, parce que ``PlacementFixer`` écarte les composants sans
   notion de contour et ressort ceux qu'on vient de rentrer.

Racine commune des échecs 1-3 : le repère ne peut pas être déterminé de façon
fiable. ``outline.vertices`` est en coordonnées page ; ``fp.position`` est
tantôt page tantôt board-local ; ``board_origin`` vaut tantôt ``(100,100)``
tantôt ``(0,0)``. Un décalage de 100 mm fait paraître tout le board dehors.

D'où le parti pris : **détecter via ``PlacementAnalyzer``**, qui sait, et
avertir — sans jamais déplacer. Un board dégradé par une réparation fondée sur
un repère deviné est pire qu'un board refusé bruyamment par le routeur.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "kicad-tools" / "src"))

from tools import placement  # noqa: E402


class _Conflit:
    def __init__(self, nom_type: str, c1: str, c2: str | None = None) -> None:
        self.type = type("T", (), {"name": nom_type})()
        self.component1 = c1
        self.component2 = c2
        self.severity = None


def test_detection_deleguee_a_l_analyseur(monkeypatch):
    """L'autorité est PlacementAnalyzer, pas un calcul de bornes maison."""
    monkeypatch.setattr(
        "kicad_tools.placement.analyzer.PlacementAnalyzer.find_conflicts",
        lambda self, path, rules: [_Conflit("OFF_BOARD", "U1"),
                                   _Conflit("PAD_CLEARANCE", "C1", "C2")],
    )

    assert placement._off_board_refs(Path("b.kicad_pcb")) == ["U1"]


def test_type_de_conflit_jamais_reference_par_son_membre():
    """``ConflictType.OFF_BOARD`` n'existe pas partout — ne jamais y référer.

    Mesuré le 2026-07-31 : la révision kicad-tools de l'image Docker n'expose
    que 5 types (PAD_CLEARANCE, COURTYARD_OVERLAP, HOLE_TO_HOLE, SILKSCREEN_PAD,
    EDGE_CLEARANCE). Référencer le membre absent levait une ``AttributeError``
    qui tuait le placement sans laisser de trace — stdout bufferisé perdu au
    kill, le log s'arrêtait net après l'étape 1. La comparaison porte donc sur
    ``type.name``.
    """
    source = Path(placement.__file__).read_text(encoding="utf-8")
    lignes_de_code = [
        ligne for ligne in source.splitlines()
        if "ConflictType.OFF_BOARD" in ligne
        and not ligne.lstrip().startswith("#")
        and "``" not in ligne
    ]

    assert lignes_de_code == [], (
        "référencer ce membre lève une AttributeError sur les révisions "
        "kicad-tools qui ne l'exposent pas, et tue le placement en silence"
    )


def test_comparaison_par_nom_accepte_un_type_hors_enum(monkeypatch):
    """Corollaire : un type qui n'est pas un membre de l'enum réel marche."""
    monkeypatch.setattr(
        "kicad_tools.placement.analyzer.PlacementAnalyzer.find_conflicts",
        lambda self, path, rules: [_Conflit("OFF_BOARD", "U1")],
    )

    assert placement._off_board_refs(Path("b.kicad_pcb")) == ["U1"]


def test_revision_sans_off_board_ne_signale_rien(monkeypatch):
    """Sur une révision qui ignore le type, on n'invente pas de verdict."""
    monkeypatch.setattr(
        "kicad_tools.placement.analyzer.PlacementAnalyzer.find_conflicts",
        lambda self, path, rules: [_Conflit("PAD_CLEARANCE", "C1", "C2")],
    )

    assert placement._off_board_refs(Path("b.kicad_pcb")) == []


def test_les_deux_composants_d_un_conflit_sont_remontes(monkeypatch):
    monkeypatch.setattr(
        "kicad_tools.placement.analyzer.PlacementAnalyzer.find_conflicts",
        lambda self, path, rules: [_Conflit("OFF_BOARD", "U1", "Y1"),
                                   _Conflit("OFF_BOARD", "U1")],
    )

    assert placement._off_board_refs(Path("b.kicad_pcb")) == ["U1", "Y1"]


def test_analyseur_indisponible_ne_fait_pas_echouer_le_placement(monkeypatch):
    """Un contrôle d'observabilité ne doit jamais casser une génération."""
    def boum(self, path, rules):
        raise RuntimeError("analyseur cassé")

    monkeypatch.setattr(
        "kicad_tools.placement.analyzer.PlacementAnalyzer.find_conflicts", boum)

    assert placement._off_board_refs(Path("b.kicad_pcb")) == []


def test_controle_final_journalise_chaque_fautif(monkeypatch, caplog):
    monkeypatch.setattr(placement, "_off_board_refs", lambda path: ["U1", "Y1"])

    with caplog.at_level("WARNING"):
        assert placement._outside_outline_refs(Path("b.kicad_pcb")) == 2

    assert "U1" in caplog.text and "Y1" in caplog.text
    assert "INROUTABLES" in caplog.text
