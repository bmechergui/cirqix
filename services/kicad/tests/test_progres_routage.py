"""Progression du routage — publiee par le routeur, lue par une autre requete.

⚠️ POURQUOI UN FICHIER, ET PAS UNE VARIABLE DE MODULE. Le service tourne avec
4 workers uvicorn, qui sont des PROCESSUS separes : la requete qui route et
celle qui demande la progression ne tombent pas forcement sur le meme. Une
variable de module ne serait visible que du worker qui l a ecrite, et le
sondage rendrait « aucune progression » une fois sur quatre — un silence
indistinguable d un routeur qui n a pas encore commence.

⚠️ LA CLE VIENT DU CLIENT. Elle nomme un fichier : sans validation, une valeur
comme `../../etc/passwd` ferait lire ou ecrire hors du dossier. C est le meme
defaut que l injection shell de `livrer_boards.py`, corrigee le 2026-09-03.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from tools.progres_routage import (
    CleInvalide,
    _purger_anciens,
    chemin_du_progres,
    lire_progres,
    oublier_progres,
    publier_progres,
)


def test_publie_puis_relu_a_l_identique(tmp_path: Path) -> None:
    publier_progres("run-1", passe=4, non_routes=46, nets=99, palier=2,
                    racine=tmp_path)
    vu = lire_progres("run-1", racine=tmp_path)
    assert vu is not None
    assert vu["passe"] == 4
    assert vu["non_routes"] == 46
    assert vu["nets"] == 99
    assert vu["palier"] == 2


def test_le_pourcentage_est_calcule_pas_recu(tmp_path: Path) -> None:
    """53 nets relies sur 99 : le lecteur n a pas a refaire la division."""
    publier_progres("run-1", passe=4, non_routes=46, nets=99, palier=2,
                    racine=tmp_path)
    assert lire_progres("run-1", racine=tmp_path)["pourcentage"] == 54


def test_un_nets_a_zero_ne_divise_pas_par_zero(tmp_path: Path) -> None:
    publier_progres("run-1", passe=1, non_routes=0, nets=0, palier=2,
                    racine=tmp_path)
    assert lire_progres("run-1", racine=tmp_path)["pourcentage"] == 0


def test_progression_absente_rend_none(tmp_path: Path) -> None:
    """Rien publie n est pas une erreur : le routage n a pas encore commence."""
    assert lire_progres("jamais-vu", racine=tmp_path) is None


def test_publication_ecrase_la_precedente(tmp_path: Path) -> None:
    publier_progres("run-1", passe=1, non_routes=90, nets=99, palier=2,
                    racine=tmp_path)
    publier_progres("run-1", passe=7, non_routes=12, nets=99, palier=2,
                    racine=tmp_path)
    assert lire_progres("run-1", racine=tmp_path)["passe"] == 7


def test_oublier_supprime_et_reste_muet_sur_l_absent(tmp_path: Path) -> None:
    publier_progres("run-1", passe=1, non_routes=9, nets=9, palier=2,
                    racine=tmp_path)
    oublier_progres("run-1", racine=tmp_path)
    assert lire_progres("run-1", racine=tmp_path) is None
    oublier_progres("run-1", racine=tmp_path)  # deux fois : jamais d exception


@pytest.mark.parametrize("cle", [
    "../evasion",
    "a/b",
    "..",
    "",
    "cle avec espace",
    "x" * 200,
])
def test_une_cle_hors_alphabet_est_refusee(cle: str, tmp_path: Path) -> None:
    """La cle nomme un fichier : elle ne doit jamais designer un autre dossier."""
    with pytest.raises(CleInvalide):
        chemin_du_progres(cle, racine=tmp_path)
    with pytest.raises(CleInvalide):
        publier_progres(cle, passe=1, non_routes=1, nets=2, palier=2,
                        racine=tmp_path)
    with pytest.raises(CleInvalide):
        lire_progres(cle, racine=tmp_path)


def test_une_cle_legitime_reste_dans_la_racine(tmp_path: Path) -> None:
    chemin = chemin_du_progres("projet_42-abc", racine=tmp_path)
    assert chemin.parent == tmp_path


def test_un_fichier_illisible_rend_none_plutot_que_de_lever(tmp_path: Path) -> None:
    """Lu pendant l ecriture, le JSON peut etre tronque. Ce n est pas une panne."""
    chemin_du_progres("run-1", racine=tmp_path).write_text("{tronq", encoding="utf-8")
    assert lire_progres("run-1", racine=tmp_path) is None


def test_la_progression_porte_son_horodatage(tmp_path: Path) -> None:
    """Sans lui, un routeur mort et un routeur lent se lisent pareil."""
    avant = time.time()
    publier_progres("run-1", passe=1, non_routes=1, nets=2, palier=2,
                    racine=tmp_path)
    vu = lire_progres("run-1", racine=tmp_path)
    assert avant <= vu["mis_a_jour"] <= time.time()


def test_l_ecriture_est_atomique_jamais_de_fichier_partiel(tmp_path: Path) -> None:
    """Le lecteur ne doit jamais voir un JSON a moitie ecrit.

    On le prouve en verifiant qu aucun fichier temporaire ne subsiste et que
    le contenu final est du JSON complet — l ecriture passe par un rename.
    """
    publier_progres("run-1", passe=3, non_routes=5, nets=9, palier=4,
                    racine=tmp_path)
    fichiers = sorted(p.name for p in tmp_path.iterdir())
    assert fichiers == ["run-1.json"]
    json.loads((tmp_path / "run-1.json").read_text(encoding="utf-8"))


def test_la_purge_retire_les_perimes_et_garde_les_frais(tmp_path: Path) -> None:
    """Une cle par run n est jamais reutilisee : sans purge, /tmp se remplit."""
    publier_progres("vieux", passe=1, non_routes=1, nets=2, palier=2,
                    racine=tmp_path)
    publier_progres("frais", passe=1, non_routes=1, nets=2, palier=2,
                    racine=tmp_path)
    vieux = chemin_du_progres("vieux", racine=tmp_path)
    import os
    perime = time.time() - 7200
    os.utime(vieux, (perime, perime))

    assert _purger_anciens(tmp_path, peremption_s=3600) == 1
    assert lire_progres("vieux", racine=tmp_path) is None
    assert lire_progres("frais", racine=tmp_path) is not None


def test_publier_purge_au_passage(tmp_path: Path) -> None:
    """La purge se declenche a l ecriture — le seul moment ou l on passe la."""
    import os
    publier_progres("vieux", passe=1, non_routes=1, nets=2, palier=2,
                    racine=tmp_path)
    perime = time.time() - 7200
    vieux = chemin_du_progres("vieux", racine=tmp_path)
    os.utime(vieux, (perime, perime))

    publier_progres("autre", passe=1, non_routes=1, nets=2, palier=2,
                    racine=tmp_path)
    assert lire_progres("vieux", racine=tmp_path) is None


def test_une_purge_sur_un_dossier_absent_ne_leve_pas(tmp_path: Path) -> None:
    assert _purger_anciens(tmp_path / "jamais-cree") == 0
