"""La couture DIT les ilots qu elle n a pas su coudre.

⚠️ Mesure du 2026-09-21, banc de la graine en etoile : carte-07 et carte-10
sortent a UNE connexion manquante, carte-09 a une erreur — toutes du PLAN DE
MASSE, aucun signal. Le journal : « couture : 1 via(s) poses » pendant que
« GND@F.Cu en 17 ilots ».

CAUSE, dans `_stitch_zones` : quand aucun point d un ilot ne passe les filtres
(obstacle d un autre net, ecart entre trous, point hors du polygone), la boucle
fait `continue` SANS RIEN DIRE. `_coudre_jusqu_au_bout` s arrete des qu une
passe ne change plus le board, avec pour commentaire « insister serait vain » —
or « aucun via pose » a DEUX causes :

    tous les ilots sont relies        -> arret legitime
    un ilot resiste, sans site libre  -> connexion manquante, en silence

C est la famille que ce depot traque : un echec rend la meme valeur que son cas
normal. On ne sait pas encore REPARER ces ilots ; on exige d abord de les VOIR.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE) not in sys.path:
    sys.path.insert(0, str(RACINE))

RUNNER = (RACINE / "tools" / "routing_pcbnew_runner.py").read_text(encoding="utf-8")
ROUTING = (RACINE / "routers" / "routing.py").read_text(encoding="utf-8")


def _corps(source: str, nom: str) -> str:
    debut = source.index(f"def {nom}(")
    return source[debut:source.index("\ndef ", debut + 1)]


class TestLeRunnerCompteCeQuIlAbandonne:
    def test_le_resultat_porte_les_ilots_perdus(self):
        corps = _corps(RUNNER, "_stitch_zones")
        assert '"perdus"' in corps, "le resultat ne dit que les vias POSES"

    def test_un_ilot_sans_site_est_compte_et_non_ignore(self):
        corps = _corps(RUNNER, "_stitch_zones")
        # `pose` reste faux APRES la seconde passe : l ilot rejoint les perdus.
        # ⚠️ `rindex` : le premier `if not pose:` ouvre desormais la recherche
        # fine. S ancrer sur le premier ferait mesurer le mauvais bloc — piege
        # deja paye par une garde qui visait sa propre docstring.
        i = corps.rindex("if not pose:")
        assert "perdus" in corps[i:i + 260], "l abandon reste silencieux"


class TestLAppelantLeDit:
    def test_le_journal_nomme_les_ilots_non_cousus(self):
        corps = _corps(ROUTING, "_recoudre_les_zones")
        # S ancrer sur le TEST lui-meme, pas sur le premier mot « perdus » :
        # la signature en porte un desormais, et la garde mesurait le vide.
        i = corps.index("if perdus:")
        assert "logger.warning" in corps[i:i + 500], \
            "un ilot perdu doit sortir en AVERTISSEMENT, pas en silence"

    def test_la_boucle_ne_conclut_plus_au_travail_fini(self):
        corps = _corps(ROUTING, "_coudre_jusqu_au_bout")
        assert "perdus" in corps or "_ILOTS_PERDUS" in corps, \
            "« aucun via pose » se lit encore comme « plus rien a coudre »"


class TestLaRaisonDuRefus:
    """⚠️ Premiere mesure, 2026-09-21 : « GND@2 5.11 mm2 (13 candidats) » — treize
    points essayes, zero retenu, et RIEN ne dit lequel des trois filtres a
    refuse. Sans la raison, le remede se devine ; ce depot a deja paye deux fois
    le fait de deviner (la condition « cuivre en face », refutee 1 -> 4
    manquantes, et le halo pose au mauvais moment).

    Trois filtres, trois compteurs : hors du polygone, obstacle d un autre net,
    trou voisin trop proche."""

    def test_le_runner_compte_chaque_refus(self):
        corps = _corps(RUNNER, "_stitch_zones")
        for raison in ("hors_polygone", "obstacle", "trou_trop_pres"):
            assert raison in corps, raison

    def test_les_refus_voyagent_dans_le_rapport(self):
        corps = _corps(RUNNER, "_stitch_zones")
        bloc = corps[corps.index("perdus.append("):]
        assert chr(34) + "refus" + chr(34) + ": refus" in bloc[:700], \
            "le detail des refus ne sort pas du runner"

    def test_l_appelant_journalise_la_raison(self):
        corps = _corps(ROUTING, "_recoudre_les_zones")
        assert "refus" in corps


class TestOnCherchheALaResolutionDuVia:
    """⚠️ Mesure du 2026-09-21, trois ilots abandonnes sur le banc :

        GND@F.Cu  2,96 mm2   10 candidats   7 hors du cuivre, 3 sur obstacle
        GND@B.Cu  1,05 mm2    3 candidats
        GND@F.Cu 25,41 mm2   13 candidats   8 hors du cuivre, 5 sur obstacle

    Meme un ilot de 25 mm2 ne recoit que TREIZE points d essai : le pas de
    `_pas_d_echantillonnage` ne descend jamais sous 1 mm (`max(via_d, 1.0)`),
    et la grille est celle du RECTANGLE ENGLOBANT — sur une languette coudee,
    la majorite des points tombe a cote du cuivre.

    Le plancher de 1 mm est juste pour la PREMIERE passe (« deux points a moins
    d un diametre donnent le meme verdict »). Il ne l est plus pour un ilot
    qu on s apprete a ABANDONNER : la regle est qu on ne renonce jamais sans
    avoir cherche a la resolution du via lui-meme. Le cout est borne — seuls
    les ilots perdus paient la seconde passe."""

    def test_un_pas_fin_existe_et_vaut_le_via(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "_runner_couture", RACINE / "tools" / "routing_pcbnew_runner.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules["_runner_couture"] = mod
        spec.loader.exec_module(mod)
        via = 0.6
        # Premiere passe : plancher a 1 mm, inchange.
        assert mod._pas_d_echantillonnage(5.0, 5.0, via) >= 1.0
        # Seconde passe : on descend au via.
        fin = mod._pas_d_echantillonnage(5.0, 5.0, via, fin=True)
        assert fin <= via, "un ilot abandonne n a pas ete cherche plus finement"
        assert fin > 0

    def test_la_seconde_passe_n_a_lieu_que_sur_un_ilot_perdu(self):
        corps = _corps(RUNNER, "_stitch_zones")
        ouverture = corps.index("if not pose:")
        abandon = corps.rindex("if not pose:")
        assert "fin=True" in corps[ouverture:abandon],             "la seconde passe ne se declenche pas sur l abandon"
        # ... et si elle echoue AUSSI, l ilot reste avoue : la recherche fine
        # ne doit pas devenir une facon d enterrer l echec.
        assert "perdus.append(" in corps[abandon:abandon + 400],             "l abandon doit rester avoue s il persiste"
