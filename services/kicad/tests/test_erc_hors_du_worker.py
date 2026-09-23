"""L'ERC de kicad-tools s'exécute dans un PROCESSUS ENFANT, jamais dans le worker.

⚠️ Mesuré DEUX FOIS le 2026-09-23, sur deux cartes différentes du banc :

    carte-08   HTTP 500 sur /erc   schema de 190 ko
    carte-10   HTTP 500 sur /erc   schema de 141 ko, generation en 22,5 s

La trace est sans ambiguïté :

    Timeout (0:00:04.500000)!
      kicad_tools/sexp/parser.py:77  __init__
      kicad_tools/sexp/parser.py:1181 _parse_list
      ...
      kicad_tools/schematic/models/io_mixin.py:111  load
      tools/erc.py:188  run_kicad_tools_erc

`Schematic.load` est du Python PUR : il tient le GIL pendant toute l'analyse.
Or **uvicorn tue par SIGKILL tout worker qui ne répond pas à son ping en 5 s**
(`supervisors/multiprocess.py:170 process is hung, kill it`). Sur un gros
schéma, ou simplement sur une machine occupée, le parseur dépasse ce délai et
le routage entier est perdu : la carte sort sans board.

C'est la leçon du 2026-09-10, déjà payée avec le journal Freerouting relu en
entier (564 Mo, 6 à 9 s de GIL) et corrigée là par `LecteurIncremental`. La
SŒUR n'avait jamais été traitée : `CLAUDE.md` dit pourtant « NEVER tenir le GIL
plus de quelques secondes dans un worker uvicorn — un gros `read_text`,
`json.loads`, `re` sur des mégaoctets — ou le faire dans un processus enfant ».

RÈGLE : l'analyse du schéma se fait dans un enfant, comme `cmaes_runner`,
`drc_pcbnew_runner`, `placement_pcbnew_runner` et `routing_pcbnew_runner`.
"""
from __future__ import annotations

import inspect
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))


class TestLeRunnerExiste:
    def test_il_y_a_un_runner_erc(self):
        assert (RACINE / "tools" / "erc_runner.py").is_file(), (
            "l'analyse du schéma doit vivre dans un runner, comme les quatre "
            "autres opérations lourdes du service")

    def test_le_runner_a_un_point_d_entree(self):
        source = (RACINE / "tools" / "erc_runner.py").read_text(encoding="utf-8")
        assert "def main(" in source and "__main__" in source


class TestLAppelantNAnalysePlusLuiMeme:
    """Un correctif écrit mais jamais appelé est indistinguable d'un correctif
    absent — c'est ce qui a masqué des semaines que le Géomètre ne tournait pas."""

    def test_run_kicad_tools_erc_passe_par_un_enfant(self):
        from tools import erc as E
        code = inspect.getsource(E.run_kicad_tools_erc)
        nu = "\n".join(l for l in code.splitlines()
                       if not l.lstrip().startswith("#"))
        assert "subprocess" in nu, (
            "l'ERC doit lancer un processus enfant, pas analyser sur place")
        assert "Schematic.load" not in nu, (
            "`Schematic.load` tient le GIL : il ne doit plus apparaître dans "
            "le corps qui tourne DANS le worker uvicorn")

    def test_un_echec_de_l_enfant_ne_passe_pas_pour_un_schema_propre(self):
        # ⚠️ La faute que ce dépôt traque partout : un échec qui rend la même
        # valeur que le cas normal. « aucune violation » et « je n'ai pas pu
        # analyser » ne doivent pas se ressembler.
        from tools import erc as E
        code = inspect.getsource(E.run_kicad_tools_erc)
        assert "raise" in code, (
            "un enfant qui échoue doit LEVER, jamais rendre une liste vide de "
            "violations — sinon un schéma non analysé passe pour propre")


class TestLeContratEstPreserve:
    def test_il_rend_toujours_le_triplet(self):
        from tools import erc as E
        sig = inspect.signature(E.run_kicad_tools_erc)
        assert list(sig.parameters) == ["sch_content", "auto_fix"]


class TestLeBudgetDeKicadCli:
    """⚠️ Le budget était de 30 s À PLAT, et il a fait perdre `carte-10` le
    2026-09-23 : `subprocess.TimeoutExpired` remontait en HTTP 500, donc le
    routage entier. Un schéma du banc pèse 140 à 190 ko.

    C'est la famille « le plafond n'était pas UN endroit, mais QUATRE » : un
    budget plus serré que le travail rend inatteignable ce qui est plus lent
    que lui, et rien dans la réponse ne le trahit.
    """

    def _budget(self):
        from routers import erc as E
        return E._budget_erc_s

    def test_il_se_deduit_de_la_taille(self):
        budget = self._budget()
        petit = budget(10 * 1024)
        gros = budget(500 * 1024)
        assert gros > petit, "un gros schéma doit recevoir plus de temps"

    def test_il_ne_descend_jamais_sous_le_plancher(self):
        from routers import erc as E
        assert self._budget()(0) >= E._KICAD_CLI_TIMEOUT_PLANCHER_S
        assert E._KICAD_CLI_TIMEOUT_PLANCHER_S >= 120, (
            "le point d'échec mesuré est 30 s ; le plancher doit en être loin")

    def test_un_schema_du_banc_recoit_bien_plus_que_30_s(self):
        # 190 ko : la taille exacte du schéma de carte-08 qui a échoué.
        assert self._budget()(190 * 1024) > 120


class TestUneExpirationNeTuePasLeRun:
    """kicad-tools a DÉJÀ rendu un verdict réel : le perdre pour un
    dépassement de délai faisait sortir la carte SANS BOARD."""

    def test_l_expiration_est_rattrapee_et_DITE(self):
        import inspect
        from routers import erc as E
        code = inspect.getsource(E.run_erc)
        assert "subprocess.TimeoutExpired" in code, (
            "l'expiration de kicad-cli doit être rattrapée, pas propagée en 500")
        # ⚠️ ANCRE SUR LE BLOC, PAS SUR UNE DISTANCE. Cette garde cherchait
        # dans les 900 caractères suivants ; le commentaire qui explique
        # POURQUOI l'expiration doit être fail-closed l'a repoussé au-delà, et
        # la garde a crié alors que l'avertissement était bien là. C'est la
        # DEUXIÈME fois le même jour — l'autre était
        # `test_aucun_raccord_possible_se_DIT`. Une garde s'ancre sur ce qui
        # ne bouge pas : ici le `except` suivant, qui ferme le bloc.
        i = code.index("subprocess.TimeoutExpired")
        fin = code.index("except Exception", i)
        assert "logger.warning" in code[i:fin], (
            "un contrôle qui n'a pas tourné doit être DIT, jamais tu")


class TestUneExpirationNePASSEPasPourUnSchemaPROPRE:
    """⚠️ LE DÉFAUT LE PLUS GRAVE DE CETTE JOURNÉE, introduit par le correctif
    d'un autre défaut et trouvé par la revue avant fusion, jamais par un test.

    Le premier rattrapage de `TimeoutExpired` était un simple `break`. Si
    l'expiration tombe à la PREMIÈRE itération, `violations` vaut `[]`, donc
    la route répondait `erc_clean=True`, `skipped=False`,
    `engine="kicad-cli"` — la réponse EXACTE d'un schéma réellement contrôlé
    et propre.

    Et `skipped=False` court-circuite `runErcFallback()` côté TypeScript :
    `ERC_CLEAN` était persisté SANS AUCUN VERDICT, sur un statut qui
    participe au gate JLCPCB.

    C'est littéralement la faute que ce dépôt a corrigée cinq fois — un échec
    qui rend la même valeur que son cas normal — réintroduite en réparant
    autre chose.
    """

    def _bloc_expiration(self):
        source = (RACINE / "routers" / "erc.py").read_text(encoding="utf-8")
        debut = source.index("except subprocess.TimeoutExpired")
        fin = source.index("except Exception", debut)
        return source[debut:fin]

    def test_elle_ne_rend_jamais_erc_clean(self):
        bloc = self._bloc_expiration()
        assert "erc_clean=False" in bloc, (
            "une expiration ne doit JAMAIS rendre erc_clean=True : c'est la "
            "réponse d'un schéma contrôlé et propre")

    def test_elle_bascule_sur_le_repli(self):
        bloc = self._bloc_expiration()
        assert "skipped=True" in bloc, (
            "skipped=False court-circuite runErcFallback() : ERC_CLEAN serait "
            "persisté sans le moindre verdict")

    def test_elle_rend_le_verdict_REELLEMENT_obtenu(self):
        bloc = self._bloc_expiration()
        assert "kt_violations" in bloc, (
            "le commentaire promettait de garder le verdict de kicad-tools — "
            "il doit être RENDU, pas seulement promis")

    def test_elle_le_DIT(self):
        bloc = self._bloc_expiration()
        assert "warning=" in bloc and "logger.warning" in bloc, (
            "un contrôle d'autorité qui n'a pas tourné se DIT, dans le journal "
            "ET dans la réponse")
