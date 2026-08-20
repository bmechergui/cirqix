"""Une valeur de propriété numérique NUE fait rejeter le fichier ENTIER.

Le sérialiseur de `kicad_tools` ne quote un atome chaîne que s'il a été LU depuis
un token quoté (`_originally_quoted`) ou s'il ne ressemble pas à un nombre. Ce
drapeau vaut False pour tout atome construit programmatiquement — donc pour
chaque valeur de composant injectée depuis notre schéma JSON. Une valeur
purement numérique ressort alors nue :

    (property "Value" 330          <- S-expression invalide

KiCad 10.0.4 refuse le fichier entier. Côté PCB, le défaut est connu et gardé
depuis le 2026-07-27 (`tools/pcb.py::_quote_bare_property_values`,
« Failed to load board »). Côté SCHÉMA, le même défaut donnait
`kicad-cli sch erc` -> `rc=3: Failed to load schematic`, sans aucun garde.

Vérifié le 2026-08-20 sur deux fichiers ne différant QUE par cette ligne :
    (property "Value"  330   -> rc=3, « Failed to load schematic »
    (property "Value" "330"  -> rc=0, 5 violations trouvées

⚠️ Le message de kicad-cli est GÉNÉRIQUE : un fichier absent produit exactement
le même. Il ne suffit donc pas à diagnostiquer — c'est la comparaison A/B qui
prouve la cause.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools.sexp_quote import quote_bare_property_values  # noqa: E402


class TestRequotage:
    def test_requote_une_valeur_numerique_nue(self):
        texte, n = quote_bare_property_values('(property "Value" 330 (at 1 2 0))')
        assert n == 1
        assert '(property "Value" "330"' in texte

    def test_laisse_les_atomes_numeriques_legitimes(self):
        # `(at …)`, `(size …)`, `(version …)` sont de VRAIS nombres : les quoter
        # casserait le fichier aussi sûrement que de ne pas quoter les valeurs.
        source = '(at 12.7 -5.08 0)\n(size 1.5 1.5)\n(version 20260206)'
        texte, n = quote_bare_property_values(source)
        assert n == 0
        assert texte == source

    def test_ne_retouche_pas_une_valeur_deja_quotee(self):
        source = '(property "Value" "330" (at 1 2 0))'
        texte, n = quote_bare_property_values(source)
        assert n == 0
        assert texte == source

    def test_traite_les_valeurs_negatives_et_decimales(self):
        texte, n = quote_bare_property_values('(property "X" -4.7 (at 0 0 0))')
        assert n == 1
        assert '(property "X" "-4.7"' in texte


class TestCablage:
    """Le garde doit s'appliquer AVANT l'écriture du fichier lu par kicad-cli.

    Le poser après ne servirait à rien : c'est ce fichier-là que kicad-cli lit.
    """

    def test_le_routeur_erc_requote_avant_d_appeler_kicad_cli(self):
        source = (_SERVICE_ROOT / "routers" / "erc.py").read_text(encoding="utf-8")
        assert "quote_bare_property_values" in source
        position_requote = source.index("quote_bare_property_values(")
        position_ecriture = source.index("sch_path.write_text(")
        assert position_requote < position_ecriture, (
            "le requotage doit précéder l'écriture du fichier lu par kicad-cli"
        )

    def test_le_generateur_pcb_partage_la_meme_implementation(self):
        # Deux copies de la même règle finiraient par diverger : c'est
        # exactement ainsi que le schéma s'est retrouvé sans garde alors que le
        # PCB en avait un depuis un mois.
        source = (_SERVICE_ROOT / "tools" / "pcb.py").read_text(encoding="utf-8")
        assert "from tools.sexp_quote import" in source or (
            "sexp_quote" in source
        ), "tools/pcb.py doit consommer l'implémentation partagée"


_KICAD_CLI = shutil.which("kicad-cli")


@pytest.mark.skipif(_KICAD_CLI is None, reason="kicad-cli absent")
class TestKicadCliCharge:
    """Preuve comportementale : le requotage rend le fichier chargeable."""

    _MINIMAL = """(kicad_sch
\t(version 20231120)
\t(generator "test")
\t(uuid "11111111-1111-4111-8111-111111111111")
\t(paper "A4")
\t(lib_symbols)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 100 100 0)
\t\t(uuid "22222222-2222-4222-8222-222222222222")
\t\t(property "Reference" "R1" (at 100 96 0))
\t\t(property "Value" {value} (at 100 104 0))
\t)
\t(sheet_instances (path "/" (page "1")))
)
"""

    def _erc(self, tmp_path: Path, contenu: str, nom: str) -> int:
        chemin = tmp_path / f"{nom}.kicad_sch"
        chemin.write_text(contenu, encoding="utf-8")
        (tmp_path / f"{nom}.kicad_pro").write_text("{}", encoding="utf-8")
        return subprocess.run(
            [
                _KICAD_CLI, "sch", "erc", str(chemin),
                "--format", "json",
                "--output", str(tmp_path / f"{nom}.erc.json"),
                "--severity-all",
            ],
            capture_output=True, text=True, timeout=120, check=False,
        ).returncode

    def test_le_fichier_nu_est_refuse_et_le_requote_accepte(self, tmp_path):
        nu = self._MINIMAL.format(value="330")
        rc_nu = self._erc(tmp_path, nu, "nu")

        requote, n = quote_bare_property_values(nu)
        assert n >= 1, "le garde doit avoir requoté au moins une valeur"
        rc_requote = self._erc(tmp_path, requote, "requote")

        assert rc_nu != 0, "kicad-cli devrait refuser une valeur numérique nue"
        assert rc_requote == 0, "kicad-cli devrait accepter le fichier requoté"
