"""Le fanout RENONCE a des broches, et ne le disait pas.

⚠️ Constat du 2026-08-31, apres le banc des huit cartes. Le net manquant est
GND sur SEPT messages sur sept :

    5 fois   net(s) : GND
    1 fois   net(s) : GND, GPIO23
    1 fois   net(s) : GND, GPIO19

Le mecanisme charge de resoudre exactement cela — `_escape_pads` — sort chaque
broche isolee par une courte piste et un via. Quand aucune sortie n est
degagee, il RENONCE, et il a raison : une broche orpheline bloque la commande
au DRC, une broche court-circuitee peut partir en fabrication.

Mais il comptait ses renoncements SANS LES DIRE :

    logger.info("fanout: %d broche(s) sortie(s) vers le plan", n)   # escaped

`renonces` etait calcule, place dans le resultat JSON, et jete. Personne ne
savait combien de broches GND avaient ete abandonnees — alors que c est le
seul chiffre qui mesure le dernier verrou du projet.

⚠️ Meme famille que tous les defauts de la session : un mecanisme qui rend un
chiffre plausible sans dire ce qu il n a pas fait. Un renoncement silencieux
est indistinguable d un travail complet.

⚠️ On ne FORCE pas les broches renoncees — ce serait echanger une connexion
manquante contre un court-circuit. On les COMPTE, pour savoir enfin de combien
on parle.
"""
from __future__ import annotations

import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_SERVICE_ROOT))


class TestJournal:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def _corps(self) -> str:
        i = self.SOURCE.index("def _pose_les_vias_d_echappement")
        j = self.SOURCE.index(chr(10) + "def ", i + 5)
        return self.SOURCE[i:j]

    def test_les_renoncements_sont_LUS(self):
        assert '"renonces"' in self._corps(), (
            "le compteur existe dans le resultat et n est jamais lu")

    def test_les_renoncements_sont_DITS(self):
        corps = self._corps()
        i = corps.index('"renonces"')
        assert "logger" in corps[max(0, i - 400):i + 400], (
            "on renonce a des broches sans que rien ne l ecrive")

    def test_un_renoncement_est_un_AVERTISSEMENT(self):
        """⚠️ Pas un `info` noye : ces broches sont le dernier verrou du
        projet, et leur nombre doit sauter aux yeux dans le journal."""
        corps = self._corps()
        i = corps.index('"renonces"')
        assert "logger.warning" in corps[max(0, i - 400):i + 500]


class TestDocumentationHonnete:
    SOURCE = (_SERVICE_ROOT / "routers" / "routing.py").read_text(encoding="utf-8")

    def test_la_docstring_appelante_ne_decrit_plus_l_aveugle(self):
        """⚠️ `_fanout_pads_isolees` decrivait encore « le via est pose A
        L AVEUGLE », alors que `_escape_pads` consulte son environnement depuis
        longtemps. Cette docstring PERIMEE m a fait diagnostiquer un defaut qui
        n existait plus — une documentation fausse coute plus cher qu une
        documentation absente.
        """
        # ⚠️ Verification POSITIVE. Une premiere version cherchait l absence
        # du mot « A L AVEUGLE » — et echouait sur la docstring corrigee, qui
        # CITE l ancien texte pour expliquer qu il etait faux. Une garde qui
        # interdit un mot interdit aussi d en parler.
        i = self.SOURCE.index("def _fanout_pads_isolees")
        j = self.SOURCE.index('"""', self.SOURCE.index('"""', i) + 3)
        doc = self.SOURCE[i:j]
        assert "_choisir_sortie" in doc, (
            "la docstring ne mentionne pas le comportement REEL — consulter "
            "l environnement avant de poser le via")
        assert "RENONCE" in doc, (
            "la docstring ne dit pas que des broches sont abandonnees")
