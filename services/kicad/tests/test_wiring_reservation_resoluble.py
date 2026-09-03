"""Un via reserve doit porter SON net, et ce net doit EXISTER dans le DSN.

⚠️ Trois defauts trouves le 2026-08-31, tous invisibles au journal, tous dans
la meme frontiere : ce qu on croit reserver et ce que le routeur recoit.

1. Les deux appelants de production aplatissaient `_VIAS_RESERVES` en couples
   `(x, y)` et passaient UN net unique — celui du plan. La branche de
   `_bloc_wiring` qui porte le net de chaque via existait, son commentaire
   avertissait meme que « les mettre tous sur GND creerait autant de
   courts-circuits », et AUCUN appelant de production ne l atteignait : seule
   une fixture de test y allait. Les vias d echappement des SIGNAUX etaient
   donc annonces comme GND.

2. `_confier_au_plan` retire du DSN le bloc `(net GND (pins ...))`, puis on
   ecrivait `(via ... (net GND) (type protect))` deux lignes plus bas. Toute la
   reservation etait annoncee sous un net ABSENT du fichier. Un `(wiring)` qui
   cite un net inconnu n est pas une reservation, c est au mieux du bruit.

3. `_PISTES_A_PROTEGER` recevait le meilleur board du palier precedent au
   changement de palier, puis se faisait ECRASER par le board neuf quinze
   lignes plus bas — apres que le journal eut annonce « N piste(s)
   PROTEGEES ». L escalade cumulative demandee par l utilisateur (« chaque
   escalade on garde le cuivre et les pistes ») ne gardait rien.

⚠️ Ces tests gardent le CABLAGE autant que le comportement : un bloc `(wiring)`
correct que personne n alimente est indistinguable d un bloc absent — c est
exactement ce qui a masque le defaut n°1 pendant toute sa vie.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from routers import routing as R  # noqa: E402

SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")


def _dsn(nets: tuple) -> str:
    """Un DSN minimal declarant `nets`, avec un bloc (wiring) vide."""
    blocs = "".join(
        '    (net %s (pins U1-%d))%s' % (n, i, chr(10))
        for i, n in enumerate(nets, start=1))
    return ("(pcb board" + chr(10) + "  (network" + chr(10) + blocs
            + "  )" + chr(10) + "  (wiring" + chr(10) + "  )" + chr(10) + ")")


def _board(code: int, nom: str, couche: str) -> bytes:
    """Un board minimal AU FORMAT REEL de KiCad.

    ⚠️ Ma premiere fixture ecrivait `(net 3 "SPI_CLK")` DANS le segment et
    enchainait les champs sans `(uuid ...)`. Un vrai board ne fait ni l un ni
    l autre : le segment porte `(net 3)` seul, et KiCad intercale `(uuid ...)`
    entre `(layer)` et `(net)`. C est precisement ce que la regex d origine ne
    supportait pas — une fixture complaisante l aurait laissee passer.
    """
    return (
        '(kicad_pcb' + chr(10)
        + '  (net %d "%s")' % (code, nom) + chr(10)
        + '  (segment' + chr(10)
        + '    (start 10.0 20.0)' + chr(10)
        + '    (end 30.0 40.0)' + chr(10)
        + '    (width 0.2)' + chr(10)
        + '    (layer "%s")' % couche + chr(10)
        + '    (uuid "0534a101-8ddc-4719-81f3-8dd4fd034ada")' + chr(10)
        + '    (net %d)' % code + chr(10)
        + '  )' + chr(10) + ')').encode("utf-8")


class TestSegmentAuFormatReel:
    """⚠️ DIXIEME PIEGE DE FORME : `(uuid ...)` entre `(layer)` et `(net)`.

    Mesure sur `examples/led-blinker-full-pipeline/output/6_routed.kicad_pcb` :
    231 segments, **0 reconnus** par l ancienne regex. La protection des pistes
    de l escalade n a donc jamais protege une seule piste.
    """

    def test_un_segment_reel_est_reconnu(self):
        assert R._bloc_wiring_pistes(_board(3, "GND", "F.Cu")).count("(wire") == 1

    def test_l_ordre_des_champs_n_est_PAS_suppose(self):
        bloc = ('(segment (net 7) (layer "B.Cu") (width 0.25) '
                '(end 5.0 6.0) (start 1.0 2.0))')
        champs = R._champs_de_segment(bloc)
        assert champs is not None
        assert champs[5] == "B.Cu" and champs[6] == "7"

    def test_un_segment_incomplet_est_ECARTE_pas_devine(self):
        assert R._champs_de_segment('(segment (start 1.0 2.0) (width 0.2))') is None


class TestEndpointHTTP:
    """⚠️ Le decorateur decorait la MAUVAISE fonction.

    En inserant `_armer_abandon` je l ai glisse ENTRE `@router.post` et
    `route_auto` : FastAPI exposait donc `_armer_abandon(actif: bool)` sur
    `/route/auto`, et `route_auto` n etait joignable par aucune requete. Le
    banc ne pouvait pas le voir — il importe `route_auto` directement en
    Python. La garde interroge la TABLE DE ROUTES, jamais la mise en page du
    fichier : c est la seule mesure qui repond a la vraie question.
    """

    def test_route_auto_est_bien_l_endpoint(self):
        cibles = {r.path: r.endpoint.__name__
                  for r in R.router.routes if hasattr(r, "endpoint")}
        assert cibles.get("/route/auto") == "route_auto"


class TestNetParVia:
    def test_chaque_via_porte_son_propre_net(self):
        vias = [{"via_x": 1000, "via_y": 2000, "net_nom": "GND"},
                {"via_x": 3000, "via_y": 4000, "net_nom": "SPI_CLK"}]
        bloc = R._bloc_wiring(vias, "GND")
        assert "(net GND)" in bloc
        assert "(net SPI_CLK)" in bloc

    def test_le_net_par_defaut_ne_sert_que_de_repli(self):
        bloc = R._bloc_wiring([{"via_x": 1, "via_y": 2}], "GND")
        assert "(net GND)" in bloc


class TestCablageDesAppelants:
    def test_aucun_appelant_n_aplatit_les_vias(self):
        # ⚠️ La garde porte sur la FORME de l aplatissement, pas sur un numero
        # de ligne : les deux sites vivent a 2700 lignes d ecart.
        assert 'for v in _VIAS_RESERVES' not in SOURCE, (
            "un appelant aplatit encore les vias en couples — le net de chaque "
            "via est perdu et tous repartent sous celui du plan")

    def test_les_deux_sites_passent_la_liste_telle_quelle(self):
        # Deux moteurs, deux sites : l API et le sous-processus. Corriger un
        # seul laisserait la moitie des routages sous l ancien defaut.
        assert SOURCE.count("_injecter_wiring(") >= 3  # def + 2 appels
        for bloc in SOURCE.split("_injecter_wiring(")[1:]:
            entete = bloc[:200]
            if entete.lstrip().startswith("dsn_text"):
                continue  # la definition
            assert "_VIAS_RESERVES," in entete or "_VIAS_RESERVES\n" in entete


class TestResolubilite:
    def test_les_nets_declares_sont_lus_dans_le_dsn(self):
        noms = R._nets_declares_dsn(_dsn(("GND", "SPI_CLK")))
        assert noms == {"GND", "SPI_CLK"}

    def test_un_via_sur_un_net_absent_n_est_PAS_injecte(self):
        # GND a ete confie au plan, donc retire du DSN : l annoncer dans le
        # (wiring) ne reserve rien et peut faire rejeter le fichier.
        dsn = _dsn(("SPI_CLK",))
        sortie = R._injecter_wiring(
            dsn, [{"via_x": 1000, "via_y": 2000, "net_nom": "GND"}], "GND")
        assert "(net GND)" not in sortie

    def test_un_via_sur_un_net_declare_est_injecte(self):
        dsn = _dsn(("SPI_CLK",))
        sortie = R._injecter_wiring(
            dsn, [{"via_x": 1000, "via_y": 2000, "net_nom": "SPI_CLK"}], "GND")
        assert "(net SPI_CLK)" in sortie
        assert "(type protect)" in sortie

    def test_tout_ecarter_rend_le_dsn_INCHANGE(self):
        # Mieux vaut un routage sans reservation qu un DSN mutile.
        dsn = _dsn(("SPI_CLK",))
        assert R._injecter_wiring(
            dsn, [{"via_x": 1, "via_y": 2, "net_nom": "GND"}], "GND") == dsn


class TestNomsGuillemetes:
    r"""⚠️ ONZIEME PIEGE DE FORME, releve sur un DSN reel du pipeline.

    Le nom d un net est NU la plupart du temps, mais GUILLEMETE des qu il
    contient une parenthese — ce qui est le cas de tous les nets auto-generes
    de KiCad :

        (net GPIO3        (pins R3-1 U1-12))
        (net "Net-(U2-2)" (pins U2-2 U2-2@1))

    Mesure sur ce DSN : 140 nets declares, dont une majorite de
    `Net-(Uxx-yy)`. Une capture `[^\s()]+` s arrete au `(` et rend `"Net-` :
    ces nets paraitraient non declares et leur protection serait ecartee a
    tort. Symetriquement, les ECRIRE nus casserait la structure du fichier.
    """

    def test_un_nom_guillemete_est_LU(self):
        dsn = ('(pcb b' + chr(10) + '  (network' + chr(10)
               + '    (net "Net-(U2-2)" (pins U2-2 U2-2@1))' + chr(10)
               + '    (net GPIO3 (pins R3-1))' + chr(10)
               + '  )' + chr(10) + '  (wiring' + chr(10) + '  )' + chr(10) + ')')
        assert R._nets_declares_dsn(dsn) == {"Net-(U2-2)", "GPIO3"}

    def test_un_nom_a_parenthese_est_REECRIT_guillemete(self):
        assert R._nom_pour_dsn("GPIO3") == "GPIO3"
        assert R._nom_pour_dsn("Net-(U2-2)") == '"Net-(U2-2)"'

    def test_un_via_sur_un_net_a_parenthese_traverse_le_filtre(self):
        dsn = ('(pcb b' + chr(10) + '  (network' + chr(10)
               + '    (net "Net-(U2-2)" (pins U2-2 U2-2@1))' + chr(10)
               + '  )' + chr(10) + '  (wiring' + chr(10) + '  )' + chr(10) + ')')
        sortie = R._injecter_wiring(
            dsn, [{"via_x": 1000, "via_y": 2000, "net_nom": "Net-(U2-2)"}], "GND")
        assert '(net "Net-(U2-2)")' in sortie


class TestProtectionCumulative:
    def test_plusieurs_boards_peuvent_etre_proteges(self):
        # Le meilleur board du palier precedent ET les liaisons GND posees
        # avant le routage : les deux, pas l un OU l autre.
        board = _board(3, "SPI_CLK", "F.Cu")
        autre = _board(4, "SDA", "B.Cu")
        bloc = R._bloc_wiring_pistes([board, autre])
        assert bloc.count("(wire") == 2
        assert "SPI_CLK" in bloc and "SDA" in bloc

    def test_un_seul_board_reste_accepte(self):
        assert R._bloc_wiring_pistes(_board(3, "SPI_CLK", "F.Cu")).count("(wire") == 1

    def test_l_etape_3_AJOUTE_au_lieu_d_ECRASER(self):
        # ⚠️ Le defaut n°3 : `_PISTES_A_PROTEGER = etendu` effacait le meilleur
        # board du palier precedent, apres que le journal l eut annonce protege.
        # ⚠️ Chercher l AFFECTATION, pas la chaine : le commentaire qui
        # explique le defaut la cite forcement.
        lignes = [l.strip() for l in SOURCE.split(chr(10))]
        assert "_PISTES_A_PROTEGER = etendu" not in lignes, (
            "l etape 3 ecrase encore la protection de l escalade")
        assert "_ajouter_aux_pistes_protegees(" in SOURCE
