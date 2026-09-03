"""Le placement doit se juger avec l INSTRUMENT QUI REND LE VERDICT.

Mesure du 2026-08-27, ESP32 du banc. Le journal disait :

    placement propre au tirage 3

...et le board final portait ONZE `courtyards_overlap`, dont U1/D2 et U1/R1.

Les deux ne mesurent pas la meme chose : `_compter_conflits_erreur` interrogeait
`PlacementAnalyzer` (kicad-tools, ses propres DesignRules) tandis que le verdict
final vient de `kicad-cli pcb drc`. Un placement « propre » selon le premier
peut etre refuse par le second — le projet avait deja note que le modele de
faisabilite interne de kicad-tools differe des DesignRules.

Consequence : le re-tirage s arretait sur un placement qu il croyait bon, et la
chaine routait 25 minutes un board condamne.

⚠️ C est le fil rouge de la session : mesurer avec un autre instrument que celui
qui tranche, c est se rassurer sans rien garantir.

Le DRC coute 1 a 2 s par tirage, contre 2 a 4 MINUTES de placement : le juger
avec le bon outil ne change pas l ordre de grandeur du cout.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))

from tools import placement as P  # noqa: E402


class TestInstrument:
    def test_le_compteur_interroge_kicad_cli(self):
        source = (_SERVICE_ROOT / "tools" / "placement.py").read_text(encoding="utf-8")
        corps = source[source.index("def _compter_conflits_erreur(") :]
        corps = corps[: corps.index(chr(10) + "def ")]
        assert "drc" in corps.lower(), "le compteur doit utiliser le DRC"

    def test_les_chevauchements_de_courtyard_sont_comptes(self, monkeypatch, tmp_path):
        rapport = {"violations": [
            {"severity": "error", "type": "courtyards_overlap"},
            {"severity": "error", "type": "shorting_items"},
            {"severity": "warning", "type": "silk_over_copper"},
        ]}
        monkeypatch.setattr(P, "_rapport_drc_placement", lambda _p: rapport)
        f = tmp_path / "b.kicad_pcb"
        f.write_text("(kicad_pcb)", encoding="utf-8")
        assert P._compter_conflits_erreur(f) == 2

    def test_un_board_propre_compte_zero(self, monkeypatch, tmp_path):
        monkeypatch.setattr(P, "_rapport_drc_placement", lambda _p: {"violations": []})
        f = tmp_path / "b.kicad_pcb"
        f.write_text("(kicad_pcb)", encoding="utf-8")
        assert P._compter_conflits_erreur(f) == 0

    def test_un_drc_indisponible_fait_RE_TIRER(self, monkeypatch, tmp_path):
        """⚠️ Ce test affirmait l inverse — et il avait tort.

        Il exigeait `== 0` au motif qu « un compteur en panne ne doit pas
        declencher de re-tirages inutiles ». Mais rendre 0 ne dit pas « je ne
        sais pas » : cela dit « ce board est propre ». Mesure du 2026-08-27 sur
        l ESP32 : le board place etait refuse par kicad-cli, le rapport revenait
        vide, le compteur annoncait 0 — et la boucle acceptait au premier tirage
        un board qui portait vingt erreurs. La chaine a route vingt-cinq minutes
        dessus.

        Un tirage qu on ne sait pas juger doit etre re-tire, jamais retenu.
        """
        def leve(_p):
            raise P.DrcInexecutable("Failed to load board")

        monkeypatch.setattr(P, "_rapport_drc_placement", leve)
        f = tmp_path / "b.kicad_pcb"
        f.write_text("(kicad_pcb)", encoding="utf-8")
        assert P._compter_conflits_erreur(f) == P._CONFLITS_INDETERMINES
