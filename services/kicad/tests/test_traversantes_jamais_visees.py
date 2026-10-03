"""Une pastille TRAVERSANTE n'est jamais visée par un via d'échappement.

⚠️ Mesuré sur `carte-11-croisements`, board livré et déclaré `drc_clean` :

    J1.33 (GND, traversante, perçage 1 mm) en (83,5 ; 89,42)
    via GND en (83,5 ; 90,02)         bord à bord : -0,050 mm   -> perçages RECOUPÉS
    via GND en (83,1894 ; 90,5791)    à 0,340 mm du précédent   -> 0,50 exigés
    J2.33 : exactement le même motif

Aucun fabricant ne perce cela. La cause : `_pads_gnd_fine_pitch` ne vise que
les boîtiers d'au moins 16 pastilles, et comptait TOUTES les pastilles — un
connecteur 2×20 au pas de 2,54 mm en a 40, il passait donc pour un boîtier
« fine-pitch ». Sa broche GND recevait un via d'échappement… posé dans son
propre perçage.

⚠️ La SŒUR le savait. `_pads_plan_a_degager` porte en toutes lettres : « LES
TRAVERSANTES SONT EXCLUES : leur perçage atteint déjà le plan de la face
opposée ». Le filtre `smd` y est depuis le 2026-09-02 ; il n'a jamais été
porté dans `_pads_gnd_fine_pitch` ni dans `_pads_signal_fine_pitch`. C'est la
faute inscrite dans CLAUDE.md le 2026-09-09 : « NEVER corriger un piège de
forme sans chercher SES SŒURS ».

La règle, pour les deux fonctions :
  - la DENSITÉ se compte sur les pastilles CMS — « fine-pitch » est une
    notion CMS ;
  - seules les pastilles CMS sont VISÉES — une traversante est déjà reliée
    aux deux faces par son propre perçage.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE))

from routers import routing as R  # noqa: E402

_CARTE_11 = _SERVICE / "examples" / "carte-11-croisements" / "expected" / "final.kicad_pcb"


def _pad(nom: str, type_: str, net_num: int, net: str) -> str:
    return ('    (pad "%s" %s rect (at 0 0) (size 1 1) (layers "F.Cu") '
            '(net %d "%s"))\n' % (nom, type_, net_num, net))


def _empreinte(ref: str, pads: list) -> str:
    return ('  (footprint "X" (layer "F.Cu")\n'
            '    (property "Reference" "%s")\n%s  )\n' % (ref, "".join(pads)))


def _board(*empreintes: str) -> bytes:
    return ('(kicad_pcb (version 20240108)\n  (net 0 "")\n  (net 1 "GND")\n'
            '  (net 2 "SIG")\n' + "".join(empreintes) + ")").encode()


def _connecteur_2x20() -> str:
    """40 pastilles TRAVERSANTES, dont une GND — comme J1 de carte-11."""
    pads = [_pad(str(i), "thru_hole", 2, "SIG") for i in range(1, 41) if i != 33]
    pads.append(_pad("33", "thru_hole", 1, "GND"))
    return _empreinte("J1", pads)


def _lqfp(ref: str = "U1") -> str:
    """20 pastilles CMS, dont une GND — un vrai boîtier fine-pitch."""
    pads = [_pad(str(i), "smd", 2, "SIG") for i in range(1, 20)]
    pads.append(_pad("20", "smd", 1, "GND"))
    return _empreinte(ref, pads)


class TestGndFinePitch:
    def test_le_connecteur_traversant_n_est_PAS_vise(self):
        cibles = R._pads_gnd_fine_pitch(_board(_connecteur_2x20()), {"GND"})
        assert ("J1", "33") not in cibles, (
            "une broche traversante est deja reliee aux deux faces par son "
            "percage : lui poser un via d echappement, c est percer dans son trou")

    def test_un_vrai_boitier_fine_pitch_reste_vise(self):
        """Le correctif ne doit pas éteindre le mécanisme."""
        cibles = R._pads_gnd_fine_pitch(_board(_lqfp()), {"GND"})
        assert ("U1", "20") in cibles

    def test_la_densite_se_compte_sur_les_pastilles_CMS(self):
        """10 CMS + 30 traversantes : pas un boîtier fine-pitch."""
        pads = [_pad(str(i), "smd", 2, "SIG") for i in range(1, 10)]
        pads.append(_pad("10", "smd", 1, "GND"))
        pads += [_pad(str(i), "thru_hole", 2, "SIG") for i in range(11, 41)]
        cibles = R._pads_gnd_fine_pitch(_board(_empreinte("J9", pads)), {"GND"})
        assert cibles == []


class TestSignalFinePitch:
    def test_le_connecteur_traversant_n_est_PAS_vise(self):
        # Deux boîtiers portent SIG, sinon ce n'est pas une liaison.
        cibles = R._pads_signal_fine_pitch(_board(_connecteur_2x20(), _lqfp()))
        assert not any(ref == "J1" for ref, _ in cibles)

    def test_un_vrai_boitier_fine_pitch_reste_vise(self):
        cibles = R._pads_signal_fine_pitch(_board(_connecteur_2x20(), _lqfp()))
        assert any(ref == "U1" for ref, _ in cibles)


class TestSurLeVraiBoard:
    """⚠️ Une fixture dit ce qu'on a imaginé, un board dit ce qui est —
    leçon payée deux fois le 2026-08-29."""

    def test_carte_11_ne_vise_plus_ses_connecteurs(self):
        pcb = _CARTE_11.read_bytes()
        cibles = R._pads_gnd_fine_pitch(pcb, {"GND"})
        visees = sorted({ref for ref, _ in cibles})
        assert not any(ref.startswith("J") for ref in visees), (
            "les connecteurs 2x20 de carte-11 sont traversants : ils ne "
            "doivent plus recevoir de via d echappement (vises : %s)" % visees)
