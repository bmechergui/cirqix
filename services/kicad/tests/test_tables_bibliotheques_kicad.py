"""L'image installe les tables de bibliotheques de KiCad — sinon l'ERC parle de l'environnement.

Mesure du 2026-09-15, run NE555 par la file (`ae2dc908`) : l'ERC d'autorite
rendait 31 violations, TOUTES des avertissements d'environnement —

    22  lib_symbol_issues      « The current configuration does not include
                                 the symbol library 'power' »
     9  footprint_link_issues  « … the footprint library 'Package_SO' »

Le repertoire de configuration de l'utilisateur `cirqix`
(`~/.config/kicad/10.0/`) ne portait ni `sym-lib-table` ni `fp-lib-table`,
alors que KiCad livre les deux dans `/usr/share/kicad/template/`.

Meme schema, meme conteneur :

    tables absentes     31 violations
    tables copiees       0 violation     (sans variable d'environnement)
    tables retirees     31 violations    (le temoin)

Effet de bord sur le DRC mesure sur carte-05, carte-08 et carte-10 livrees :
AUCUN — rapport identique, erreurs et connexions manquantes comprises.

Enjeu : 31 avertissements a chaque run tenaient le projet a `SCHEMA_DONE`
au lieu de `ERC_CLEAN`, et noyaient une vraie alerte dans du bruit.

⚠️ `$HOME` n'est pas un volume : une copie faite dans un conteneur en marche
part a la premiere recreation. La regle vit donc dans l'IMAGE.
"""
from __future__ import annotations

import re
from pathlib import Path

DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"
CONFIG = "/home/cirqix/.config/kicad/10.0"


def _instructions() -> list[str]:
    """Les instructions du Dockerfile, continuations jointes, SANS commentaires.

    Une garde qui cherche une chaine dans le fichier la trouverait dans le
    commentaire qui l'explique — piege deja paye deux fois dans ce depot.
    """
    lignes = [l for l in DOCKERFILE.read_text(encoding="utf-8").splitlines()
              if not l.lstrip().startswith("#")]
    texte = re.sub(r"\\\s*\n", " ", "\n".join(lignes))
    return [l.strip() for l in texte.splitlines() if l.strip()]


def _index(predicat) -> int:
    for i, instr in enumerate(_instructions()):
        if predicat(instr):
            return i
    return -1


def _run_des_tables() -> str:
    runs = [i for i in _instructions()
            if i.startswith("RUN") and "sym-lib-table" in i and "fp-lib-table" in i]
    assert runs, "aucune instruction RUN n'installe sym-lib-table ET fp-lib-table"
    return runs[0]


class TestTablesDansLImage:
    def test_les_deux_tables_sont_copiees_depuis_le_modele_de_kicad(self):
        run = _run_des_tables()
        assert "/usr/share/kicad/template/sym-lib-table" in run
        assert "/usr/share/kicad/template/fp-lib-table" in run
        assert CONFIG in run

    def test_la_copie_echoue_si_kicad_ne_livre_plus_les_modeles(self):
        # `cp` d'un fichier absent echoue deja ; mais un `|| true` ou un `;`
        # avant le cp la rendrait silencieuse. On l'interdit explicitement.
        run = _run_des_tables()
        assert "|| true" not in run
        assert not re.search(r";\s*cp\b", run), "le cp doit etre enchaine par &&"

    def test_les_tables_appartiennent_a_l_utilisateur_du_service(self):
        run = _run_des_tables()
        assert re.search(r"chown\s+-R\s+cirqix:cirqix\s+/home/cirqix/\.config", run)

    def test_installees_APRES_la_creation_de_l_utilisateur_et_AVANT_USER(self):
        cree = _index(lambda i: i.startswith("RUN") and "useradd" in i)
        tables = _index(lambda i: i.startswith("RUN") and "sym-lib-table" in i)
        bascule = _index(lambda i: i.startswith("USER cirqix"))
        assert -1 not in (cree, tables, bascule), (cree, tables, bascule)
        assert cree <= tables < bascule
