"""Le board doit porter les MÊMES références que le schéma.

⚠️ MESURE DU 2026-09-08. Deux exécutions de la même carte, même commande, même
schéma, ont produit des références DIFFÉRENTES :

    tirage A   C1, C2, C3, C4 … C8              (renumérotés)
    tirage B   C1, C2, C3, C10 … C13, C20       (ceux du schéma)

Un utilisateur qui cherche `C12` sur sa carte peut donc ne pas le trouver — et
pas de la même façon d'un run à l'autre. Le BOM hérite de ces noms.

CAUSE, et elle est dans NOTRE code, pas dans la bibliothèque :

    ref_prefix = comp.ref.rstrip("0123456789") or comp.ref
    c = CSComponent(symbol=..., ref=ref_prefix, ...)

On ne transmettait que le PRÉFIXE — « C » pour « C12 » — et `circuit_synth`
renumérotait ensuite dans son ordre de création. Vérifié dans le conteneur :
`CSComponent(ref="C12").ref == "C12"`. La bibliothèque acceptait la référence
complète depuis le début ; on la lui retirait.

POURQUOI ÇA VARIAIT D'UN RUN À L'AUTRE. La cascade de `generate_schematic` a
trois niveaux, et le premier — `circuit_synth` — est borné par un TIMEOUT de
20 s. Quand il tient, ses références renumérotées l'emportent ; quand il
dépasse, `kicad-tools` prend la main et préserve les références. Le résultat
dépendait donc d'une course. Le correctif rend les deux niveaux d'accord, ce
qui supprime la course au lieu de la gagner.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import schematic as S  # noqa: E402


def _code_seul(src: str) -> str:
    """Le source, commentaires et docstrings retires.

    ⚠️ Ma premiere version de ces gardes cherchait la chaine
    `rstrip("0123456789")` dans le source brut — et la trouvait dans le
    COMMENTAIRE qui explique le correctif. Le test echouait sur sa propre
    explication. C est l ancre ecrite a l instant, piege deja paye deux fois
    dans ce depot. On ne regarde donc que le code.
    """
    lignes = []
    for ligne in src.splitlines():
        nu = ligne.split("#", 1)[0]
        lignes.append(nu)
    return chr(10).join(lignes)


class TestReferencesTransmises:
    def test_la_reference_COMPLETE_est_transmise(self):
        """`C12` doit arriver tel quel, pas rogné en `C`."""
        src = _code_seul(inspect.getsource(S._generate_with_cs_lib))
        assert 'rstrip("0123456789")' not in src, (
            "le numero de la reference est encore retire avant transmission")

    def test_la_reference_du_schema_est_bien_celle_passee(self):
        """Garde POSITIVE : l absence du rognage ne prouve pas la presence du bon."""
        src = _code_seul(inspect.getsource(S._generate_with_cs_lib))
        assert "ref=comp.ref" in src.replace(" ", "")

    def test_aucun_prefixe_n_est_reconstruit_ailleurs(self):
        """La règle doit valoir dans TOUT le module, pas au seul site corrigé.

        Une règle appliquée à une fonction ne protège pas sa sœur — ce dépôt
        l'a payé plusieurs fois.
        """
        src = _code_seul((_SERVICE_ROOT / "tools" / "schematic.py").read_text(encoding="utf-8"))
        assert 'ref.rstrip("0123456789")' not in src

    def test_le_niveau_kicad_tools_preserve_aussi(self):
        """Les deux niveaux doivent s'accorder, sinon la course revient."""
        src = _code_seul(inspect.getsource(S._generate_with_kicad_tools))
        assert 'rstrip("0123456789")' not in src


class TestCourseEntreNiveaux:
    def test_le_timeout_existe_toujours(self):
        """On ne supprime PAS le timeout : il protège la requête.

        Le corriger n'est pas le but — le but est que les deux niveaux
        produisent les mêmes références, pour que l'issue de la course cesse
        d'être observable.
        """
        assert isinstance(S._CS_TIMEOUT_S, (int, float))
        assert S._CS_TIMEOUT_S > 0

    def test_la_cascade_garde_ses_trois_niveaux(self):
        src = inspect.getsource(S.generate_schematic)
        assert "circuit_synth" in src
        assert "_generate_with_kicad_tools" in src
        # Le dernier recours rend "" et laisse la main au générateur TypeScript.
        assert re.search(r'return\s+""', src)
