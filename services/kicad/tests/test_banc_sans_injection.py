"""Le banc ne doit JAMAIS interpoler un nom nu dans une commande `sh -c`.

⚠️ Le nom de la carte et le nom du conteneur viennent de la ligne de commande,
et la chaine construite est executee en root dans WSL, puis suivie d un
`chmod -R 777` en root dans le conteneur. Le meme defaut avait deja ete trouve
et corrige dans `livrer_boards.py`, du meme dossier : un correctif applique a
une fonction ne protege pas sa soeur.

⚠️ La garde ne s ancre PAS sur le nom d une fonction : deux gardes de ce depot
se sont mises a ne plus rien mesurer le jour ou leur appelant a ete renomme.
Elle s ancre sur ce qui ne bouge pas — le refus, et la presence de guillemets.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import banc_driver_llm as banc  # noqa: E402


@pytest.mark.parametrize("hostile", [
    "carte'; rm -rf / #",
    "carte$(id)",
    "carte`whoami`",
    "../../evade",
    "carte;reboot",
    "carte carte",
    "",
])
def test_un_nom_hostile_est_refuse(hostile):
    with pytest.raises(SystemExit):
        banc._sur(hostile)


def test_les_noms_legitimes_du_banc_passent():
    for nom in ("carte-01-diviseur", "carte-10-maximale", "stm32-validation",
                "led-blinker-full-pipeline"):
        assert banc._sur(nom) == nom


def _sites_shell() -> str:
    """Le corps des fonctions qui batissent une commande shell."""
    return inspect.getsource(banc.executer) + inspect.getsource(banc._mesurer_board) \
        + inspect.getsource(banc._drc_du_board)


def test_aucune_interpolation_nue_dans_une_commande():
    """Cherche `% (conteneur`, `% (dist`, `% (chemin` sans guillemetage.

    C est la FORME du defaut, pas une ligne precise : elle survit a un
    deplacement de code, contrairement a une comparaison de texte exacte.
    """
    nue = re.compile(r"%\s*\(\s*(conteneur|dist|chemin|nom)\b")
    coupables = [l.strip() for l in _sites_shell().splitlines()
                 if nue.search(l) and "quote" not in l and not l.strip().startswith("#")]
    assert not coupables, "interpolation nue : %r" % coupables


def test_le_guillemetage_est_reellement_appele():
    """Une regle correcte jamais invoquee est indistinguable d une regle absente."""
    src = _sites_shell()
    assert "shlex.quote" in src or "q = shlex.quote" in src
    assert src.count("q(") + src.count("shlex.quote(") >= 6


def test_le_nom_est_filtre_avant_de_batir_le_chemin():
    """Le filtre doit s appliquer AVANT que le nom entre dans la commande."""
    src = inspect.getsource(banc.executer)
    assert "_sur(" in src
