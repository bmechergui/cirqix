"""Un redemarrage ANNONCE n est pas un redemarrage FAIT.

⚠️ Defaut mesure le 2026-08-30, huitieme de la meme famille. Le banc redemarre
la JVM Freerouting avant chaque carte, parce qu elle se degrade (400 Mo nominal
-> 2,4 Go apres quelques heures, et une passe qui prenait 0,15 s en prend
plusieurs minutes). Le redemarrage n a JAMAIS eu lieu :

    pkill: killing pid 56869 failed: Operation not permitted

Le banc tourne en `cirqix`, la JVM tournait en `root`. `subprocess.run(...,
check=False, capture_output=True)` avale l erreur, et le
`print("(JVM Freerouting redemarree)")` qui suit s executait quand meme. A
chaque carte le banc AJOUTAIT une JVM au lieu de la remplacer.

Etat trouve dans le conteneur apres sept cartes :

    PID 56869  root  550 % CPU  2,4 Go RES  3 h 49   <- l orpheline
    conteneur : 12 coeurs, 7,8 Go, swap 2048/2048 SATURE, 41 zombies

Le banc de reference a donc mesure exactement la degradation qu il etait ecrit
pour supprimer. On ne peut rien conclure d une carte mesuree dans ces
conditions — ni un succes, ni un echec.

⚠️ Le silence etait DELIBERE (« le banc doit tourner meme sans droits ») et
c est lui qui a cache le defaut pendant toute une journee de mesures. Une JVM
survivante doit etre BRUYANTE : mieux vaut un banc qui s arrete qu un banc qui
mesure la JVM d hier.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT / "scripts"))

import banc_exemples as B  # noqa: E402


_PS = """    PID COMMAND
      1 /opt/venv/bin/uvicorn main:app
  56869 java -jar /opt/freerouting/freerouting.jar --api_server.enabled=true
  41974 [java] <defunct>
  71480 java -jar /opt/freerouting/freerouting.jar --api_server.enabled=true
"""


class TestRecensement:
    def test_les_jvm_vivantes_sont_recensees(self, monkeypatch):
        monkeypatch.setattr(B, "_ps_brut", lambda: _PS)
        assert B._jvm_freerouting_survivantes() == ["56869", "71480"]

    def test_un_zombie_n_est_pas_une_jvm_vivante(self, monkeypatch):
        # ⚠️ 41 zombies dans le conteneur au moment du constat. Un `<defunct>`
        # ne consomme ni CPU ni RAM : le compter ferait echouer le banc pour
        # rien, exactement l inverse du but.
        monkeypatch.setattr(B, "_ps_brut", lambda: "  41974 [java] <defunct>\n")
        assert B._jvm_freerouting_survivantes() == []

    def test_aucune_jvm_rend_une_liste_vide(self, monkeypatch):
        monkeypatch.setattr(B, "_ps_brut", lambda: "    PID COMMAND\n      1 bash\n")
        assert B._jvm_freerouting_survivantes() == []

    def test_ps_injoignable_ne_prononce_pas_la_mort(self, monkeypatch):
        """⚠️ Ne pas confondre « je n ai pas pu regarder » et « il n y a rien ».

        C est la meme erreur que le rapport DRC vide lu « 0 erreur » : une
        mesure impossible doit lever, jamais rendre un verdict favorable.
        """
        def _explose():
            raise OSError("ps introuvable")
        monkeypatch.setattr(B, "_ps_brut", _explose)
        with pytest.raises(OSError):
            B._jvm_freerouting_survivantes()


class TestRedemarrage:
    def test_une_jvm_survivante_fait_echouer_bruyamment(self, monkeypatch):
        monkeypatch.setattr(B.shutil, "which", lambda _: "/usr/bin/java")
        monkeypatch.setattr(B.subprocess, "run", lambda *a, **k: None)
        monkeypatch.setattr(B.time, "sleep", lambda _: None)
        monkeypatch.setattr(B, "_jvm_freerouting_survivantes", lambda: ["56869"])
        lance = []
        monkeypatch.setattr(B.subprocess, "Popen",
                            lambda *a, **k: lance.append(a) or None)

        with pytest.raises(RuntimeError) as exc:
            B._redemarrer_freerouting()

        assert "56869" in str(exc.value)
        # ⚠️ Surtout ne PAS demarrer une deuxieme JVM a cote de la survivante :
        # c est ce cumul qui a sature le conteneur.
        assert lance == []

    def test_sans_survivante_la_jvm_est_relancee(self, monkeypatch):
        monkeypatch.setattr(B.shutil, "which", lambda _: "/usr/bin/java")
        monkeypatch.setattr(B.subprocess, "run", lambda *a, **k: None)
        monkeypatch.setattr(B.time, "sleep", lambda _: None)
        monkeypatch.setattr(B, "_jvm_freerouting_survivantes", lambda: [])
        lance = []
        monkeypatch.setattr(B.subprocess, "Popen",
                            lambda *a, **k: lance.append(a[0]) or None)

        B._redemarrer_freerouting()

        assert lance and "freerouting.jar" in " ".join(lance[0])

    def test_sans_java_installe_il_n_y_a_rien_a_redemarrer(self, monkeypatch):
        # Legitime et silencieux : pas de JVM du tout, donc pas d usure.
        monkeypatch.setattr(B.shutil, "which", lambda _: None)
        monkeypatch.setattr(B.subprocess, "Popen",
                            lambda *a, **k: pytest.fail("rien a lancer"))
        B._redemarrer_freerouting()


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "scripts" / "banc_exemples.py").read_text(
        encoding="utf-8")

    def _corps(self) -> str:
        corps = self.SOURCE[self.SOURCE.index("def _redemarrer_freerouting"):]
        return corps[:corps.index("\ndef ", 1)]

    def test_le_constat_suit_le_pkill(self):
        corps = self._corps()
        assert corps.index("pkill") < corps.index("_jvm_freerouting_survivantes")

    def test_le_message_de_succes_ne_precede_pas_le_constat(self):
        """⚠️ Le defaut EXACT : le message s imprimait quoi qu il arrive."""
        corps = self._corps()
        assert corps.index("_jvm_freerouting_survivantes") < corps.index(
            "redemarree")

    def test_l_echec_n_est_plus_avale(self):
        """⚠️ On lit le CODE, pas la prose.

        Premiere version de cette garde : `"except Exception" not in source`.
        Elle echouait sur la docstring du correctif, qui explique justement
        pourquoi il n y a plus de rattrapage large. Une garde qui ne distingue
        pas le code de son commentaire mesure autre chose que ce qu elle croit.
        """
        import ast

        arbre = ast.parse(self.SOURCE)
        fonction = next(
            n for n in ast.walk(arbre)
            if isinstance(n, ast.FunctionDef)
            and n.name == "_redemarrer_freerouting")
        larges = [
            h for h in ast.walk(fonction)
            if isinstance(h, ast.ExceptHandler)
            and (h.type is None
                 or (isinstance(h.type, ast.Name)
                     and h.type.id in ("Exception", "BaseException")))]
        assert not larges, (
            "un except large ici redonne au banc le silence qui a cache le defaut")
