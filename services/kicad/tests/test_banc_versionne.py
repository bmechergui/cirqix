"""Un résultat de banc doit porter la VERSION du code qui l'a produit.

Demandé par l'utilisateur le 2026-09-02, après une nuit où quatre correctifs de
placement se sont succédé en quelques heures — le rail `+3.3V`, la fenêtre de
recherche, le bord de carte, le filet du snap. Les tableaux de résultats
produits entre-temps sont aujourd'hui indistinguables les uns des autres :

    nucleo-f401   55   2   98   2   0   54   567   2   3312.6s

Cette ligne ne dit pas quel code l'a produite. Elle n'est donc ni rejouable, ni
réfutable, et on ne peut imputer aucun écart à aucun correctif.

⚠️ « inconnue » doit se lire comme tel. Un banc qui affiche une version FAUSSE
est pire qu'un banc qui n'en affiche aucune — on lui ferait confiance. C'est la
même règle que « mesuré à zéro » contre « jamais mesuré », déjà inscrite dans
ce dépôt.

⚠️ L'arbre de travail est signalé quand `tools/` ou `routers/` sont modifiés :
un SHA seul mentirait par omission si le code exécuté n'est pas celui du
commit.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

_SPEC = importlib.util.spec_from_file_location(
    "_banc", _SERVICE_ROOT / "scripts" / "banc_exemples.py")
_BANC = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_BANC)


class TestVersionLisible:
    def test_la_fonction_existe(self):
        assert hasattr(_BANC, "_version_du_code")

    def test_elle_rend_quelque_chose_de_NON_VIDE(self):
        v = _BANC._version_du_code()
        assert isinstance(v, str) and v.strip()

    def test_elle_rend_un_SHA_ou_dit_INCONNUE(self):
        # ⚠️ Jamais de valeur inventee ni de chaine vide.
        v = _BANC._version_du_code()
        sha = v.split()[0]
        assert v == "inconnue" or (
            len(sha) >= 7 and all(c in "0123456789abcdef" for c in sha)), v

    def test_elle_ne_leve_jamais(self, monkeypatch):
        # Un banc ne doit pas echouer parce que git est absent.
        def _explose(*a, **k):
            raise OSError("git introuvable")
        monkeypatch.setattr(_BANC.subprocess, "run", _explose)
        assert _BANC._version_du_code() == "inconnue"


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "scripts" / "banc_exemples.py").read_text(
        encoding="utf-8")

    def test_la_version_est_REELLEMENT_imprimee(self):
        # ⚠️ Une fonction correcte jamais appelee est indistinguable d une
        # fonction absente.
        i = self.SOURCE.index("version du code")
        assert "_version_du_code()" in self.SOURCE[i:i + 200]

    def test_elle_est_imprimee_AVANT_le_tableau(self):
        # Apres le tableau, elle passerait inapercue dans une sortie longue.
        v = self.SOURCE.index("version du code")
        t = self.SOURCE.index("{'cas':<18}")
        assert v < t

    def test_l_arbre_MODIFIE_est_signale(self):
        # Un SHA seul mentirait par omission si le code execute n est pas
        # celui du commit — et c est le cas courant pendant une session.
        assert "arbre MODIFIE" in self.SOURCE



class TestProfondeurDuChemin:
    """La version doit tenir meme dans une arborescence PEU PROFONDE.

    Mesure du 2026-09-03, CI « KiCad Docker Build » : `IndexError: 3`, trois
    fois. `_version_du_code` calculait `Path(__file__).resolve().parents[3]`
    DANS L EN-TETE DU `for`, donc HORS du `try` cense le proteger. Dans
    l image le fichier est a `/app/scripts/`, qui n a que trois ancetres.

    La machine de developpement ne pouvait pas le voir : le depot y est assez
    profond. Seule la CI, qui execute dans l image, l a revele.

    Une garde placee dans un `try` ne protege que ce qui est A L INTERIEUR.
    """

    def test_elle_ne_leve_pas_quand_le_fichier_est_peu_profond(self, tmp_path,
                                                               monkeypatch):
        # On simule `/app/scripts/banc_exemples.py` : trois ancetres, pas plus.
        faux = tmp_path / "scripts" / "banc_exemples.py"
        faux.parent.mkdir(parents=True)
        faux.write_text("", encoding="utf-8")
        monkeypatch.setattr(_BANC, "__file__", str(faux))
        assert isinstance(_BANC._version_du_code(), str)

    def test_la_profondeur_est_LUE_avant_d_etre_indexee(self):
        # Garde structurelle : plus aucun `parents[N]` indexe a l aveugle.
        import inspect
        src = inspect.getsource(_BANC._version_du_code)
        code = chr(10).join(l for l in src.split(chr(10))
                            if not l.strip().startswith("#"))
        assert "parents[3]" not in code, code
