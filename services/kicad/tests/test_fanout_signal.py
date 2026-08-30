"""Fanout d echappement des pastilles SIGNAL d un boitier fine-pitch.

⚠️ Diagnostic convergent de TROIS sources independantes, 2026-08-30 :

  - le JOURNAL du routeur : sur trois jobs de `stm32-100`, UN SEUL composant
    porte 20 a 28 % des echecs de connexion, les 85 autres 2 % chacun. C est
    U1, le LQFP-48, et sa part egale sa part des connexions ;
  - GROK : « 36 signaux d un pas de 0,5 mm sont laisses a Freerouting sans
    echappement impose ; reparez ca avant de retoucher la surface » ;
  - OPENCODE : au pas de 0,5 mm avec des pastilles de 0,3, il reste 0,2 mm
    entre deux pastilles — avec le degagement JLCPCB, AUCUNE piste n y passe.

Et la mesure tranche contre l hypothese des couches : `stm32-100` rend 99 % a
2 couches et 87 % a 4. Ajouter du cuivre n aide pas — le goulot est LOCAL,
sous le boitier.

⚠️ La reservation existante ne sert QUE le plan de masse (`_vias_a_reserver`,
broches GND que le plan n atteint pas). Grok l a souligne : reserver des vias
pour le PLAN n est pas echapper les SIGNAUX, et cela peut meme occuper les
sites dont les signaux ont besoin.
"""
from __future__ import annotations

from routers.routing import (_bloc_wiring, _pads_signal_fine_pitch,
                             _PADS_FINE_PITCH)


def _board(n_signal: int, n_gnd: int = 4, n_orphelins: int = 0) -> bytes:
    """U1 fine-pitch, et un connecteur J1 qui FERME chaque net signal.

    ⚠️ Sans J1, chaque SIGn ne toucherait qu UN boitier : ce seraient des
    orphelins, et le code aurait raison de les ecarter. Ma premiere fixture
    faisait cette erreur et accusait le code.
    """
    u1, j1 = [], []
    k = 1
    for i in range(n_signal):
        u1.append('    (pad "%d" smd rect (at %d 0) (size 1 1) '
                  '(layers "F.Cu") (net %d "SIG%d"))' % (k, k, i + 1, i + 1))
        j1.append('    (pad "%d" thru_hole circle (at %d 0) (size 1 1) '
                  '(layers "F.Cu") (net %d "SIG%d"))' % (k, k, i + 1, i + 1))
        k += 1
    for _ in range(n_gnd):
        u1.append('    (pad "%d" smd rect (at %d 0) (size 1 1) '
                  '(layers "F.Cu") (net 99 "GND"))' % (k, k))
        j1.append('    (pad "%d" thru_hole circle (at %d 0) (size 1 1) '
                  '(layers "F.Cu") (net 99 "GND"))' % (k, k))
        k += 1
    for i in range(n_orphelins):
        u1.append('    (pad "%d" smd rect (at %d 0) (size 1 1) '
                  '(layers "F.Cu") (net %d "Net-(U1-Pad%d)"))'
                  % (k, k, 500 + i, k))
        k += 1
    return (
        "(kicad_pcb\n"
        '  (footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm" (at 50 50)\n'
        '    (property "Reference" "U1" (at 0 0 0))\n'
        + "\n".join(u1) + "\n  )\n"
        '  (footprint "Connector:PinHeader_2x20" (at 10 10)\n'
        '    (property "Reference" "J1" (at 0 0 0))\n'
        + "\n".join(j1) + "\n  )\n)"
    ).encode()


def _de(pads, ref):
    return [p for r, p in pads if r == ref]


class TestSelection:
    def test_les_pastilles_signal_du_boitier_dense_sont_retenues(self):
        assert len(_de(_pads_signal_fine_pitch(_board(20)), "U1")) == 20

    def test_les_nets_confies_au_plan_sont_exclus(self):
        """GND sort par le plan, pas par un via d echappement de signal."""
        pads = _pads_signal_fine_pitch(_board(n_signal=20, n_gnd=6))
        assert len(_de(pads, "U1")) == 20

    def test_les_pastilles_orphelines_sont_exclues(self):
        """`Net-(U1-Pad7)` ne mene nulle part : rien a echapper.

        Meme piege que pour le plancher de couches — une pastille n est pas
        une liaison.
        """
        pads = _pads_signal_fine_pitch(_board(n_signal=20, n_orphelins=5))
        assert len(_de(pads, "U1")) == 20

    def test_un_boitier_peu_dense_ne_declenche_rien(self):
        assert _pads_signal_fine_pitch(_board(n_signal=3, n_gnd=1)) == []

    def test_le_seuil_suit_celui_du_placement(self):
        """Meme critere que `_dense_part_refs` : un connecteur a large pas n a
        pas de probleme d echappement."""
        assert _PADS_FINE_PITCH == 16

    def test_un_board_illisible_ne_leve_pas(self):
        assert _pads_signal_fine_pitch(b"pas un board") == []


class TestWiringParNet:
    def test_chaque_via_porte_son_propre_net(self):
        """⚠️ Le bloc DSN n acceptait qu UN net — celui du plan.

        Pour un fanout de signaux, chaque via appartient a un net different :
        les declarer tous sur GND creerait autant de courts-circuits.
        """
        vias = [{"via_x": 1_000_000, "via_y": 2_000_000, "net": "SIG1"},
                {"via_x": 3_000_000, "via_y": 4_000_000, "net": "SIG2"}]
        bloc = _bloc_wiring(vias, "GND")
        assert "(net SIG1)" in bloc
        assert "(net SIG2)" in bloc
        assert "(net GND)" not in bloc

    def test_le_net_global_reste_le_repli(self):
        """Les vias du plan n ont pas de net propre : ils gardent GND."""
        assert "(net GND)" in _bloc_wiring([(1_000_000, 2_000_000)], "GND")

    def test_le_via_reste_protege(self):
        """Sans `type protect`, le routeur deplace ou supprime le via."""
        bloc = _bloc_wiring([{"via_x": 0, "via_y": 0, "net": "SIG1"}], "GND")
        assert "(type protect)" in bloc


# ---------------------------------------------------------------------------
# Cablage — le fanout doit s AJOUTER a la reservation du plan, pas la remplacer.
# ---------------------------------------------------------------------------

import inspect

from routers.routing import route_auto, _vias_signaux_a_reserver


class TestCablage:
    def test_le_fanout_est_appele_dans_la_boucle(self):
        assert "_vias_signaux_a_reserver(" in inspect.getsource(route_auto)

    def test_il_s_ajoute_a_la_reservation_du_plan(self):
        """⚠️ Les deux servent des besoins DIFFERENTS.

        La reservation existante sort les broches GND que le plan n atteint
        pas ; le fanout sort les SIGNAUX d un boitier fine-pitch. Remplacer
        l une par l autre reintroduirait le defaut que chacune corrige.
        """
        src = inspect.getsource(route_auto)
        i = src.index("_vias_signaux_a_reserver(")
        ligne = src[src.rindex("\n", 0, i):src.index("\n", i)]
        assert "_VIAS_RESERVES +" in ligne, (
            "le fanout ECRASE la reservation du plan au lieu de s y ajouter")

    def test_un_echec_du_fanout_ne_fait_pas_echouer_le_routage(self):
        """Le fanout est un BONUS : sans lui le routage se deroule comme avant."""
        src = inspect.getsource(_vias_signaux_a_reserver)
        assert "except Exception" in src
        assert "return []" in src

    def test_aucune_cible_ne_declenche_aucun_travail(self):
        """No-op sur une carte sans boitier fine-pitch."""
        assert _vias_signaux_a_reserver(b"(kicad_pcb)") == []


# ---------------------------------------------------------------------------
# ⚠️ LE FORMAT REEL D UN BOARD, releve sur `examples/` — pas ecrit de memoire.
#
# La premiere version de `_pads_signal_fine_pitch` retenait ZERO pastille sur
# TOUS les boards du depot, et le fanout etait donc inerte. Trois hypotheses
# de format, toutes fausses, toutes validees par mes fixtures :
#
#   1. pastille et net sur la MEME ligne — ils sont sur plusieurs ;
#   2. `[^)]*` entre les deux — le bloc contient `(at -3.15 2.3 180)`, dont
#      la parenthese arretait le motif ;
#   3. `(property "Reference" "U1")` — les boards du depot ecrivent
#      `(fp_text reference "U1"`, la forme KiCad anterieure.
#
# Une fixture ecrite de memoire ne peut pas contredire l hypothese qui l a
# produite. Ces blocs-ci sont COPIES d un board reel.
# ---------------------------------------------------------------------------

_BLOC_REEL_ANCIEN = '''\t(footprint "Package_QFP:LQFP-48_7x7mm_P0.5mm"
\t\t(layer "F.Cu")
\t\t(fp_text reference "U2"
\t\t\t(at 0 -5.5)
\t\t\t(layer "F.SilkS")
\t\t)
%s\t)
'''

_PAD_REEL = '''\t\t(pad "%d" smd rect
\t\t\t(at -3.15 %d.3 180)
\t\t\t(size 2 1.5)
\t\t\t(layers "F.Cu" "F.Paste" "F.Mask")
\t\t\t(net %d "%s")
\t\t)
'''


def _board_format_reel(n: int) -> bytes:
    """Deux boitiers au format REEL, dont un fine-pitch."""
    pads_u2 = "".join(_PAD_REEL % (i + 1, i % 9, i + 1, "SIG%d" % (i + 1))
                      for i in range(n))
    pads_j1 = "".join(_PAD_REEL % (i + 1, i % 9, i + 1, "SIG%d" % (i + 1))
                      for i in range(n))
    return ("(kicad_pcb\n"
            + _BLOC_REEL_ANCIEN % pads_u2
            + _BLOC_REEL_ANCIEN.replace('"U2"', '"J1"') % pads_j1
            + ")\n").encode()


def test_le_format_reel_multi_ligne_est_reconnu():
    """Pastille et net sur des lignes differentes, avec `(at ...)` entre eux."""
    pads = _pads_signal_fine_pitch(_board_format_reel(20))
    assert len(_de(pads, "U2")) == 20, "aucune pastille retenue sur un format reel"


def test_la_reference_ancienne_forme_est_reconnue():
    """`(fp_text reference "U2"` — la forme des boards du depot."""
    pads = _pads_signal_fine_pitch(_board_format_reel(20))
    assert {r for r, _ in pads} == {"U2", "J1"}


def test_les_parentheses_internes_ne_coupent_pas_la_lecture():
    """`(at -3.15 2.3 180)` figure entre le nom de la pastille et son net."""
    board = _board_format_reel(18)
    assert b"(at -3.15" in board
    assert len(_de(_pads_signal_fine_pitch(board), "U2")) == 18
