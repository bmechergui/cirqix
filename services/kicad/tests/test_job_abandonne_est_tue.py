"""Un job Freerouting abandonne est un job TUE — la JVM est relancee.

Mesure du 2026-09-10 : huit jobs abandonnes lances a une minute d intervalle,
999 passes chacun, tous vivants en meme temps dans la JVM ; le meme placement
route a 100 % en 61 s quand la JVM est seule.
"""
from __future__ import annotations

import inspect
import re
import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402


class TestTuerLaJvm:
    def test_tue_puis_attend_le_retour_de_l_api(self, monkeypatch):
        appels = []
        monkeypatch.setattr(R.subprocess, "run", lambda cmd, **k: appels.append(cmd) or None)
        monkeypatch.setattr(R.time, "sleep", lambda s: None)
        reponses = iter([None, None, "http://127.0.0.1:37864"])
        monkeypatch.setattr(R, "_find_freerouting_api", lambda: next(reponses))
        assert R._tuer_la_jvm(attente_s=60.0) is True
        assert appels and appels[0][:2] == ["pkill", "-f"]
        motif = re.compile(appels[0][2])
        # Vise la JVM API, epargne la boucle qui la relance et les jobs CLI.
        assert motif.search("/usr/bin/java -jar /opt/freerouting/freerouting.jar --api_server.enabled=true --user_data_path=/tmp/freerouting")
        assert not motif.search("sh -c while true; do java -jar /opt/freerouting/freerouting.jar --api_server.enabled=true; done")
        assert not motif.search("/usr/bin/java -jar /opt/freerouting/freerouting.jar -de /tmp/x.dsn -do /tmp/x.ses")

    def test_le_reglage_peut_le_desarmer(self, monkeypatch):
        from tools import reglages_banc
        appels = []
        monkeypatch.setattr(R.subprocess, "run", lambda cmd, **k: appels.append(cmd) or None)
        original = reglages_banc.reglage
        try:
            reglages_banc.reglage = lambda nom, defaut=None: False if nom == "tuer_jvm_sur_abandon" else defaut
            assert R._tuer_la_jvm() is False
        finally:
            reglages_banc.reglage = original
        assert appels == []

    def test_une_jvm_qui_ne_revient_pas_rend_faux_sans_lever(self, monkeypatch):
        monkeypatch.setattr(R.subprocess, "run", lambda cmd, **k: None)
        monkeypatch.setattr(R.time, "sleep", lambda s: None)
        horloge = iter(range(0, 10_000, 5))
        monkeypatch.setattr(R.time, "time", lambda: float(next(horloge)))
        monkeypatch.setattr(R, "_find_freerouting_api", lambda: None)
        assert R._tuer_la_jvm(attente_s=20.0) is False


class TestCablage:
    def test_l_abandon_tue_la_jvm_avant_de_lever(self):
        code = "\n".join(l.split("#")[0]
                         for l in inspect.getsource(R._route_with_freerouting_api).splitlines())
        i_tue = code.find("_tuer_la_jvm()")
        i_leve = code.find("raise RoutageFige(")
        assert i_tue != -1 and i_leve != -1 and i_tue < i_leve

    def test_l_entrypoint_relance_la_jvm_en_boucle(self):
        texte = (_SERVICE / "docker-entrypoint.sh").read_text(encoding="utf-8")
        code = "\n".join(l.split("#")[0] for l in texte.splitlines())
        i_boucle = code.find("while true; do")
        i_java = code.find("java -jar /opt/freerouting")
        assert i_boucle != -1 and i_java != -1 and i_boucle < i_java, (
            "sans boucle, tuer la JVM laisse le service sans routeur")
        assert re.search(r"while true; do\s*: > /tmp/freerouting/freerouting.log", code), (
            "le journal doit repartir vide a chaque relance")

    def test_la_boucle_survit_a_une_jvm_tuee_sous_set_e(self):
        """21:50 le 2026-09-10 : java tue rend 143, `set -e` a tue la boucle
        avec lui, et le service a route trois heures par le CLI."""
        texte = (_SERVICE / "docker-entrypoint.sh").read_text(encoding="utf-8")
        code = "\n".join(l.split("#")[0] for l in texte.splitlines())
        assert re.search(r"^\s*set -e", code, re.M), "le test suppose set -e ; s il disparait, revoir la garde"
        bloc = code[code.find("while true; do"):code.find("done")]
        assert re.search(r"--user_data_path=/tmp/freerouting\s*\|\|\s*true", bloc), (
            "sans `|| true`, une JVM tuee (143) arrete la boucle de relance")
