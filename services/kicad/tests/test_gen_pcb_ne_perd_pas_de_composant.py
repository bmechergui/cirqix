"""Un composant perdu ne doit JAMAIS passer pour un board valide.

⚠️ MESURE DU 2026-09-08, sur `examples/carte-05-capteur-i2c`. Cette carte est
livrée « 100 % routée, 0 erreur » — et **son capteur n'y est pas**. Le BME280
`U3` est déclaré au schéma, connecté à `+3V3`, `GND`, `SCL` et `SDA`, et absent
du board. 26 composants déclarés, 25 posés.

Il l'était déjà dans le board versionné : ce n'est pas une régression, c'est un
défaut de fond que rien n'avait vu.

TRACE, étage par étage :

    schéma                       26 ✓
    netlist niveau 1             26 ✓   (U3 avec sa bonne empreinte)
    après place_all_components   25 ✗   ← perdu ici
    après écriture               25 ✗

La bibliothèque n'émet AUCUN message, même en journalisation DEBUG. Le symbole
`Sensor:BME280` et l'empreinte `LGA-8_2.5x2.5mm_P0.65mm` existent tous deux :
ce n'est pas un composant introuvable.

⚠️ POURQUOI LE DRC NE POUVAIT PAS LE VOIR. Un composant absent n'a aucune
connexion manquante — il n'a rien à relier. Le DRC juge ce qui EST sur la carte,
jamais ce qui devrait y être. C'est la même famille que le reste : l'absence se
lit comme un succès.

Le remède ne suppose rien de la cause : on COMPTE. Si le board produit porte
moins d'empreintes que le schéma n'a de composants, il est refusé — la cascade
essaie le niveau suivant, et si aucun n'y arrive, la génération échoue.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import pcb as P  # noqa: E402


_BOARD_3 = """(kicad_pcb
  (footprint "R_0603" (property "Reference" "R1"))
  (footprint "C_0603" (property "Reference" "C1"))
  (footprint "LGA-8"  (property "Reference" "U3"))
)"""

_BOARD_2 = """(kicad_pcb
  (footprint "R_0603" (property "Reference" "R1"))
  (footprint "C_0603" (property "Reference" "C1"))
)"""


class TestComptage:
    def test_compte_les_empreintes_reellement_posees(self):
        assert P._refs_du_board(_BOARD_3) == {"R1", "C1", "U3"}
        assert P._refs_du_board(_BOARD_2) == {"R1", "C1"}

    def test_un_board_vide_ne_compte_rien(self):
        assert P._refs_du_board("(kicad_pcb)") == set()

    def test_un_board_illisible_ne_compte_rien(self):
        """Et surtout : il ne rend pas un compte PLAUSIBLE."""
        assert P._refs_du_board("") == set()


class TestRefus:
    def test_un_composant_manquant_est_REFUSE(self):
        manquants = P._composants_perdus(_BOARD_2, ["R1", "C1", "U3"])
        assert manquants == ["U3"]

    def test_le_cas_de_la_carte_05(self):
        """26 declares, 25 posees — exactement le defaut mesure."""
        refs = ["C%d" % i for i in range(1, 25)] + ["U1", "U2"]
        board = "(kicad_pcb\n" + "\n".join(
            '  (footprint "x" (property "Reference" "%s"))' % r for r in refs) + "\n)"
        assert P._composants_perdus(board, refs + ["U3"]) == ["U3"]

    def test_un_board_complet_passe(self):
        assert P._composants_perdus(_BOARD_3, ["R1", "C1", "U3"]) == []

    def test_un_board_qui_en_a_PLUS_passe(self):
        """Le générateur ajoute parfois des éléments — ce n'est pas une perte.

        On refuse ce qui MANQUE, jamais ce qui s'ajoute : un pavé thermique ou
        un logo n'est pas un composant perdu.
        """
        assert P._composants_perdus(_BOARD_3, ["R1", "C1"]) == []


class TestCablage:
    def test_la_generation_appelle_bien_la_garde(self):
        """Une règle correcte jamais appelée est indistinguable d'une absente."""
        import inspect
        src = inspect.getsource(P.generate_pcb)
        assert "_composants_perdus" in src
