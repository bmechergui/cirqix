"""Le schéma généré est une feuille UNIQUE : ses labels de net doivent être
GLOBAUX, pas hiérarchiques.

circuit_synth pose des `hierarchical_label` dans la feuille racine. KiCad les
tolère pour la connectivité mais l ERC les REFUSE : « Hierarchical label 'DIS'
in root sheet cannot be connected to non-existent parent sheet », et chaque
broche qui n est reliée que par un tel label sort en `pin_not_connected`.

Mesuré le 2026-09-14 sur `driver-clignotant-ne555/expected/schema.kicad_sch`
avec `kicad-cli sch erc --severity-all` (KiCad 10.99) :

    labels hiérarchiques   14 erreurs   (13 pin_not_connected + 1 power_pin_not_driven)
    labels globaux          2 erreurs   (2 power_pin_not_driven — PWR_FLAG absents)

Rapport montré par l utilisateur le jour même : 20 erreurs de ce type sur une
carte NE555. La conversion est textuelle : les deux formes partagent la même
structure S-expression.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import schematic as S  # noqa: E402

_SCH = '''(kicad_sch (version 20250114) (generator "eeschema")
  (hierarchical_label "DIS" (shape input) (at 30.48 25.4 0)
    (effects (font (size 1.27 1.27)) (justify left))
    (uuid "a"))
  (hierarchical_label "THR" (shape output) (at 30.48 27.94 180)
    (effects (font (size 1.27 1.27)) (justify right))
    (uuid "b"))
  (label "LOCAL" (at 10 10 0) (effects (font (size 1.27 1.27))) (uuid "c"))
  (symbol (lib_id "Timer:NE555P") (at 40 30 0) (property "Value" "hierarchical_label") (uuid "d"))
)'''


class TestConversion:
    def test_les_labels_hierarchiques_deviennent_globaux(self):
        out = S.globaliser_les_labels_hierarchiques(_SCH)
        assert out.count("(global_label ") == 2
        assert "(hierarchical_label " not in out
        # Le nom, la forme, la position et les effets sont conservés tels quels.
        assert '(global_label "DIS" (shape input) (at 30.48 25.4 0)' in out
        assert '(global_label "THR" (shape output) (at 30.48 27.94 180)' in out

    def test_les_labels_locaux_et_le_reste_ne_bougent_pas(self):
        out = S.globaliser_les_labels_hierarchiques(_SCH)
        assert '(label "LOCAL" (at 10 10 0)' in out
        # Une valeur de propriété qui CONTIENT le mot n est pas un label.
        assert '(property "Value" "hierarchical_label")' in out

    def test_sans_label_hierarchique_le_texte_est_rendu_tel_quel(self):
        texte = "(kicad_sch (version 20250114))"
        assert S.globaliser_les_labels_hierarchiques(texte) is texte

    def test_une_entree_vide_ne_leve_pas(self):
        assert S.globaliser_les_labels_hierarchiques("") == ""


class TestCablage:
    def test_le_chemin_circuit_synth_convertit_avant_de_rendre(self):
        corps = inspect.getsource(S._generate_with_cs_lib)
        assert "globaliser_les_labels_hierarchiques(" in corps

    def test_le_schema_de_reference_ne555_ne_porte_aucun_label_hierarchique_apres_conversion(self):
        sch = _SERVICE_ROOT / "examples" / "driver-clignotant-ne555" / "expected" / "schema.kicad_sch"
        if not sch.is_file():
            return
        out = S.globaliser_les_labels_hierarchiques(sch.read_text(encoding="utf-8"))
        assert "(hierarchical_label " not in out
        assert out.count("(global_label ") == 13
