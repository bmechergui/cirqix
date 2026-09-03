"""Le filet du snap annulait TOUT ; il doit retirer seulement ce qui casse.

⚠️ Mesure du 2026-09-02, `stm32-100` (100 composants, 208 x 156 mm).

Le snap fonctionne parfaitement sur cette carte — appelé directement, il ramène
les treize condensateurs de découplage de 64-94 mm à **6,5-12,5 mm d'écart
libre**, en déplaçant 71 composants. Mais le board livré les laisse à 84 mm,
parce que le filet a tout annulé :

    auto_place: snap bypass a laisse 5 conflit(s) ERROR contre 0 avant —
                board pre-snap restaure

Le filet a RAISON : un board à cinq erreurs ne part pas en fabrication. Le
défaut est qu'il est **tout ou rien** — on déplace 71 composants, cinq posent
problème, on annule les soixante et onze.

REMÈDE — le motif existe déjà dans ce dépôt. La couture des vias a reçu le même
traitement cette nuit (`_sans_derniers_vias`) : on ne jette pas la passe
entière, on retire progressivement ce qui gêne et on garde le reste. Ici, le
rapport DRC NOMME les composants fautifs : on remet ceux-là — et eux seuls — à
leur position d'avant.

⚠️ Le repli total reste la dernière ligne : si le retrait ciblé ne suffit pas,
on restaure tout. On ne livre jamais un board plus mauvais qu'avant le snap.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402


_RAPPORT = {
    "violations": [
        {
            "severity": "error",
            "type": "courtyards_overlap",
            "items": [
                {"description": "Footprint C7 on F.Cu"},
                {"description": "Footprint R12 on F.Cu"},
            ],
        },
        {
            "severity": "error",
            "type": "clearance",
            "items": [
                {"description": "Pad 1 [GND] of C13 on F.Cu"},
                {"description": "Pad 2 [VCC] of U1 on F.Cu"},
            ],
        },
        {
            "severity": "warning",
            "type": "silk_overlap",
            "items": [{"description": "Footprint D99 on F.Cu"}],
        },
    ]
}


class TestQuiEstFautif:
    def test_elle_nomme_les_composants_des_ERREURS(self):
        assert P._refs_en_conflit(_RAPPORT) == {"C7", "R12", "C13", "U1"}

    def test_elle_ignore_les_avertissements(self):
        # ⚠️ Un `silk_overlap` ne justifie pas de defaire un deplacement :
        # ce n est pas lui qui fait refuser la carte.
        assert "D99" not in P._refs_en_conflit(_RAPPORT)

    def test_un_rapport_vide_ne_nomme_personne(self):
        assert P._refs_en_conflit({}) == set()
        assert P._refs_en_conflit({"violations": []}) == set()

    def test_un_rapport_illisible_ne_leve_pas(self):
        # Un filet en panne ne doit pas faire echouer un placement valide.
        assert P._refs_en_conflit({"violations": [{"severity": "error"}]}) == set()


class TestQuoiRetirer:
    """Seuls les composants QUE LE SNAP A BOUGES peuvent etre remis."""

    def test_on_ne_remet_que_les_deplaces(self):
        fautifs = {"C7", "R12", "U1"}
        deplaces = {"C7", "C13", "R12"}
        assert P._a_remettre(fautifs, deplaces) == {"C7", "R12"}

    def test_un_conflit_qui_ne_vient_PAS_du_snap_ne_donne_rien(self):
        # ⚠️ Cas important : si les erreurs preexistaient ou viennent d ailleurs,
        # defaire des deplacements ne les corrigerait pas. L appelant doit
        # alors tomber sur le repli total, pas s acharner.
        assert P._a_remettre({"U1", "U2"}, {"C7", "C13"}) == set()

    def test_sans_fautif_on_ne_remet_rien(self):
        assert P._a_remettre(set(), {"C7"}) == set()


class TestCablage:
    SOURCE = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")

    def test_le_filet_utilise_REELLEMENT_le_retrait_cible(self):
        # ⚠️ Une regle correcte jamais appelee est indistinguable d une regle
        # absente.
        i = self.SOURCE.index("snap bypass a laisse")
        assert "_a_remettre(" in self.SOURCE[:i], (
            "le filet annule encore tout sans tenter le retrait cible")

    def test_le_repli_TOTAL_reste_la_derniere_ligne(self):
        # On ne supprime pas la garde : on l atteint plus rarement.
        i = self.SOURCE.index("snap bypass a laisse")
        assert "avant_snap" in self.SOURCE[i:i + 700], (
            "le repli total a disparu — un board pire qu avant pourrait sortir")
