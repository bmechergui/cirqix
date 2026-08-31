"""Couper l ATTENTE d un job fige — pas le job, qu on ne peut pas tuer.

Mesure du 2026-08-29 : sur `stm32-100` a 2 couches, Freerouting fait tout son
travail a la passe 4 puis repete 995 passes identiques — 44 minutes dont une
dizaine de secondes utiles. `cancel` repond 501, `max_passes` est ignore, et
les parametres du routeur sont interdits (decision utilisateur).

Ce qui reste, et qui suffit : son JOURNAL, une ligne par passe avec score et
nets non routes. Sur 461 jobs mesures, le plus grand ecart entre deux progres
est de 144 passes — une fenetre de 150 ne coupe aucun job vivant.

⚠️ On coupe l ATTENTE, jamais le job : la JVM le digere en fond, et elle
EXECUTE DEUX JOBS EN PARALLELE (verifie le 2026-08-29, deux jobs RUNNING
simultanement) — le palier suivant demarre donc sans attendre le cadavre.

Grok, consulte : « le stall EST la preuve que 2c a echoue » — la regle
utilisateur « partir de 2, escalader sur preuve » est respectee ; seule
l attente de la preuve raccourcit.
"""
from __future__ import annotations

import pytest

from routers.routing import (_passes_sans_progres, _STAGNATION_PASSES,
                             RoutageFige, _LIGNE_PASSE_RE)


def _log(job: str, seq: list) -> str:
    return "\n".join(
        f"2026-08-29 15:00:{i%60:02d}.000 INFO   [{job}] Auto-router pass #{i+1} "
        f"on board 'x' was completed in 2.00 seconds with the score of "
        f"{score:.2f} ({unrouted} unrouted), using 1.0 CPU seconds and 1 MB memory."
        for i, (score, unrouted) in enumerate(seq))


class TestDetection:
    def test_un_job_qui_progresse_ne_stagne_pas(self):
        seq = [(100.0 + i, 50 - i) for i in range(60)]
        assert _passes_sans_progres(_log("AAAAAA", seq), "AAAAAA") == 0

    def test_les_passes_plates_sont_comptees(self):
        seq = [(100.0, 50)] * 3 + [(200.0, 40)] + [(200.0, 40)] * 30
        assert _passes_sans_progres(_log("AAAAAA", seq), "AAAAAA") == 30

    def test_le_journal_d_un_autre_job_ne_compte_pas(self):
        """Deux jobs tournent en PARALLELE : filtrer est obligatoire."""
        seq_fige = [(100.0, 50)] * 40
        log = _log("AAAAAA", seq_fige) + "\n" + _log("BBBBBB", [(1.0 + i, 9 - i) for i in range(9)])
        assert _passes_sans_progres(log, "BBBBBB") == 0

    def test_un_journal_illisible_rend_zero(self):
        """Fail-safe : sans mesure on ATTEND, on n abandonne pas a l aveugle."""
        assert _passes_sans_progres("pas un journal", "AAAAAA") == 0


class TestFenetre:
    def test_la_fenetre_ne_coupe_aucun_job_vivant_mesure(self):
        """Plus grand ecart mesure entre deux progres : 144 passes."""
        assert _STAGNATION_PASSES > 144

    def test_la_fenetre_reste_utile(self):
        """A 2,7 s la passe, 200 passes ~ 9 min : au-dela on repaye l attente."""
        assert _STAGNATION_PASSES <= 200


class TestException:
    def test_l_exception_porte_l_estimation(self):
        exc = RoutageFige(unrouted=46, nets=79)
        assert exc.routed_percent == 42   # round(100 * (79-46) / 79)
        assert "46" in str(exc)

    def test_sans_nets_l_estimation_est_nulle_pas_fausse(self):
        assert RoutageFige(unrouted=5, nets=0).routed_percent == 0


# ---------------------------------------------------------------------------
# Fenetre ADAPTATIVE — le compteur de passes seul ne suffit pas.
#
# Avis de Grok, verifie sur 299 jobs reels : « fenetre courte seulement si
# unrouted reste HAUT et plat ; fenetre 150 si unrouted est petit ».
#
# Calibration, jobs d au moins 20 passes :
#
#     progressent APRES la passe 20 : 101 jobs, unrouted@20 va jusqu a 22
#     morts avant la passe 20       : 198 jobs, unrouted@20 des 1
#
# ⚠️ La separation n est PAS parfaite en bas : un job a 1 net non route peut
# etre mort comme il peut progresser 900 passes plus tard. Un seuil bas
# tuerait des jobs vivants. En HAUT en revanche elle est nette : au-dela de
# 22, aucun des 101 progresseurs tardifs. On prend 25, avec sa marge.
# ---------------------------------------------------------------------------

from routers.routing import _fenetre_stagnation, _MORT_AU_DELA_DE


class TestFenetreAdaptative:
    def test_un_job_tres_incomplet_est_juge_vite(self):
        """stm32-100 : 46 nets non routes — condamne, on ne l attend pas."""
        assert _fenetre_stagnation(46) < _STAGNATION_PASSES

    def test_un_job_presque_fini_n_est_PLUS_COUPE_DU_TOUT(self):
        """⚠️ Ce test exigeait la fenetre LONGUE a 1 net restant.

        Elle ne suffisait pas : `arduino-uno` a ete coupee apres 162 passes
        plates avec 1 net non route, puis poussee a 4 couches — alors qu elle
        routait 100 % A 2 COUCHES dans les deux bancs precedents. Le routeur
        finit ce dernier net APRES la fenetre. On n abandonne donc plus.
        """
        assert _fenetre_stagnation(1) == 0

    def test_le_seuil_est_au_dessus_du_maximum_mesure(self):
        """22 est le plus haut unrouted@20 d un job qui progressait encore."""
        assert _MORT_AU_DELA_DE > 22

    def test_la_zone_grise_garde_la_fenetre_longue(self):
        """⚠️ Ce test exigeait la fenetre longue DES 0 net non route.

        Il consacrait la regression `arduino-uno` : a 1 net restant, couper
        apres 150 passes fait monter d une couche une carte qui routait a 100 %
        en 2. En dessous de `_PRESQUE_FINI` on n abandonne plus du tout.
        """
        for n in range(_PRESQUE_FINI + 1, 23):
            assert _fenetre_stagnation(n) == _STAGNATION_PASSES, (
                f"{n} nets non routes : un job vivant a deja ete mesure ici")

    def test_unrouted_inconnu_ne_raccourcit_rien(self):
        """Sans mesure, on ATTEND — jamais d abandon a l aveugle.

        0 signifie « pas de ligne lue », pas « zero net non route ».
        """
        assert _fenetre_stagnation(0) == 0


# ---------------------------------------------------------------------------
# ⚠️ NE JAMAIS COUPER UN ROUTAGE PRESQUE FINI.
#
# Regression mesuree en production le 2026-08-29, carte arduino-uno :
#
#     Freerouting fige (162 passes sans progres, 1 non route)
#     palier 2 couches fige a ~93% — escalade immediate
#
# Or cette carte routait 100 % A 2 COUCHES dans les deux bancs precedents : le
# routeur finissait par router ce dernier net APRES la fenetre de 150 passes.
# Ma detection la faisait donc monter a 4 couches sans necessite — plus cher a
# fabriquer, pour rien.
#
# Grok l avait dit et je l ai mal implemente : « unrouted deja bas (1-5), meme
# si le score stagne un moment, laisser vivre ». La fenetre longue ne suffit
# pas ; il faut ne PAS couper du tout.
#
# Le cout d attendre est BORNE — le job s arrete de lui-meme a 999 passes, soit
# ~2,5 min sur une carte ou une passe dure 0,15 s. Le gain est un palier de
# couches en moins sur la carte livree.
# ---------------------------------------------------------------------------

from routers.routing import _PRESQUE_FINI, _STAGNATION_PASSES_CONDAMNE


class TestPresqueFini:
    def test_un_seul_net_restant_n_est_jamais_coupe(self):
        """Le cas exact de la regression arduino-uno."""
        assert _fenetre_stagnation(1) == 0

    def test_le_seuil_reste_etroit(self):
        """⚠️ J avais mis 5, sur la phrase de Grok « unrouted deja bas (1-5) ».

        Il l a lui-meme resserre en voyant le cas : sur une carte a 15 nets,
        5 restants font 33 % — ce n est pas « presque fini », c est peut-etre
        un vrai mur a 2 couches. Les rattrapages tardifs MESURES finissent a
        UN net. Entre 3 et 25, la fenetre longue suffit.
        """
        assert 1 <= _PRESQUE_FINI <= 3
        for n in range(0, _PRESQUE_FINI + 1):
            assert _fenetre_stagnation(n) == 0

    def test_au_dela_la_fenetre_longue_reprend(self):
        assert _fenetre_stagnation(_PRESQUE_FINI + 1) == _STAGNATION_PASSES

    def test_un_board_condamne_reste_coupe_vite(self):
        assert _fenetre_stagnation(46) == _STAGNATION_PASSES_CONDAMNE

    def test_zero_ne_coupe_jamais(self):
        """`unrouted` inconnu vaut 0 : sans mesure on attend."""
        assert _fenetre_stagnation(0) == 0


# ---------------------------------------------------------------------------
# Plafond de temps — « ne jamais couper » n est vrai que sur les PASSES.
#
# Diagnostic de Grok, et il a raison : a 2,5 s la passe (stm32-100), 999 passes
# valent 40 minutes. Un « never » sans horloge recreerait exactement le plafond
# qu on vient d abattre. Les rattrapages tardifs mesures tiennent largement
# dessous — 999 passes a 0,15 s font 2,5 min sur arduino-uno.
# ---------------------------------------------------------------------------

from routers.routing import _PLAFOND_ATTENTE_S


class TestPlafondDeTemps:
    def test_le_plafond_existe(self):
        assert _PLAFOND_ATTENTE_S > 0

    def test_il_laisse_finir_un_rattrapage_tardif_rapide(self):
        """999 passes a 0,15 s = 150 s ; le plafond doit etre au-dessus."""
        assert _PLAFOND_ATTENTE_S > 999 * 0.15

    def test_il_coupe_avant_de_recreer_les_quarante_minutes(self):
        assert _PLAFOND_ATTENTE_S < 999 * 2.5

    def test_il_est_cable_dans_la_boucle_de_sondage(self):
        import inspect
        from routers.routing import _route_with_freerouting_api
        src = inspect.getsource(_route_with_freerouting_api)
        # ⚠️ Le plafond survit, mais comme seuil de SILENCE : il est desormais
        # consomme par `_routeur_muet`, pas applique en ligne.
        assert "_routeur_muet(" in src, "garde-fou du silence jamais applique"
        assert "_faut_couper(" in src


class TestSeuilResserre:
    def test_deux_nets_restants_ne_sont_jamais_coupes_sur_les_passes(self):
        assert _fenetre_stagnation(2) == 0

    def test_cinq_nets_retombent_dans_la_fenetre_longue(self):
        """⚠️ Seuil ramene de 5 a 2 : sur 15 nets, 5 restants font 33 %.

        Ce n est pas « presque fini », c est peut-etre un vrai mur a 2 couches.
        Les rattrapages tardifs mesures finissent a UN net.
        """
        assert _fenetre_stagnation(5) == _STAGNATION_PASSES


# ---------------------------------------------------------------------------
# ⚠️ UN TIRAGE FIGE N EST PAS UN PALIER MORT — quatrieme correction du meme
# defaut conceptuel, et toujours la cause nommee par Grok : une seule grandeur
# pour deux decisions.
#
# Mesure du 2026-08-29 :
#
#     arduino-uno, palier 2 couches : tirage 1 -> 93 %, tirage 2 -> 100 %
#     esp32-baseline, palier 2 couches : tirage 1 fige a 73 %, tirages
#         restants ABANDONNES -> escalade a 4 couches, alors que cette carte
#         sortait 100 % A 2 COUCHES dans les deux bancs precedents.
#
# Freerouting est stochastique : 65, 77 et 91 % mesures sur le MEME board
# place. Un tirage fige dit que CE tirage est fini, jamais que le palier l est.
# ---------------------------------------------------------------------------

def test_un_tirage_fige_ne_condamne_pas_le_palier():
    import inspect
    from routers.routing import route_auto
    src = inspect.getsource(route_auto)
    i = src.index("except RoutageFige")
    # Jusqu au `continue` du bloc, pas au-dela : le chemin normal alimente
    # legitimement `meilleur_du_palier` quelques lignes plus bas.
    bloc = src[i:src.index("continue", i) + len("continue")]
    assert "meilleur_du_palier = max" not in bloc, (
        "un tirage fige alimente le compteur qui abandonne les tirages "
        "restants : il condamne le palier au lieu du seul tirage")
    assert "continue" in bloc, "le tirage suivant doit etre tente"


# ---------------------------------------------------------------------------
# ⚠️ Le plafond de temps compte le temps SANS PROGRES, pas le temps total.
#
# Mesure du 2026-08-30, nucleo-f401 (61 nets, 55 composants), palier 4 couches :
#
#     tirage 1 -> 87 %
#     tirage 2 -> 39 %
#     tirage 3 -> 3 %   « 1 passe sans progres, 59 non routes,
#                         plafond de temps atteint »
#
# UNE seule passe en 18 minutes : sur ce board une passe dure plusieurs
# minutes, et mon plafond — compte depuis le DEBUT de l attente — a coupe un
# routage qui n avait meme pas fini son premier passage. 3 % n est pas un
# verdict, c est un abandon premature.
#
# Le compteur se remet donc a zero a chaque baisse du nombre de nets non
# routes. Mon propre commentaire disait deja « sans progres » ; le code, non.
# ---------------------------------------------------------------------------

def test_le_plafond_mesure_le_SILENCE_et_non_la_lenteur():
    """⚠️ Ce test exigeait le contraire, et il avait raison a son epoque.

    Il protegeait un premier correctif : le plafond comptait le temps TOTAL et
    coupait un routage legitimement long (Nucleo, abandonnee apres UNE passe).
    On l a donc fait compter le temps SANS PROGRES.

    Insuffisant, mesure le 2026-08-31 sur `stm32-100`, TROIS tirages
    independants, ligne identique :

        Freerouting fige (42 passes sans progres, 3 non routes, plafond de temps)

    42 passes, pas 150 : c est l horloge qui coupe, sur un board a TROIS nets
    du but (96 %). Une passe y dure ~7 s, donc 300 s n en couvrent que 42,
    quand une carte simple en verrait des centaines. La patience effective
    etait INVERSEMENT proportionnelle a la taille de la carte.

    Le compteur de PASSES s adapte tout seul ; le chronometre, non. On lui rend
    donc son seul role legitime — detecter le SILENCE — avec un seuil cale sur
    la cadence observee, pour ne pas recreer le defaut de la Nucleo.
    """
    import inspect
    from routers.routing import _route_with_freerouting_api
    src = inspect.getsource(_route_with_freerouting_api)
    assert "depart_silence = time.time()" in src, (
        "aucune horloge de silence : impossible de distinguer un routeur muet "
        "d un routeur lent")
    assert "_numero_de_passe(" in src, (
        "sans le NUMERO de passe, « lent » et « muet » sont indistinguables")
    assert "trop_long" not in src, (
        "l ancienne coupe sur le temps sans progres est revenue")


# ---------------------------------------------------------------------------
# ⚠️ L IDENTIFIANT DE LIGNE A DEUX FORMES.
#
# N avoir verifie que la premiere a rendu la detection INERTE sur toute une
# categorie de cartes :
#
#     [AC4604]           job seul
#     [E8A788\BAD9AA]    session ANTISLASH job
#
# Mesure du 2026-08-30 sur `nucleo-f401` : les 27 lignes de passe portaient la
# forme composee. Aucune coupure n a eu lieu, les tirages ont dure 17 a
# 24 minutes, le budget s est epuise, et la carte est sortie a 80 % avec
# 16 connexions manquantes et 2 erreurs — contre 100 % / 0 / 0 au banc de
# reference.
#
# Le job est le DERNIER segment du crochet : on l ancre sur la FIN, jamais sur
# la longueur totale.
# ---------------------------------------------------------------------------

_LIGNE = ("2026-08-30 05:00:00.000 INFO   [{ident}] Auto-router pass #{n} on "
          "board 'x' was completed in 2.00 seconds with the score of "
          "{score}.00 ({u} unrouted), using 1.0 CPU seconds and 1 MB memory.")


class TestFormesDIdentifiant:
    def test_la_forme_simple_est_reconnue(self):
        log = "\n".join(_LIGNE.format(ident="AC4604", n=i, score=100, u=9)
                        for i in range(1, 12))
        assert _passes_sans_progres(log, "AC4604") == 10

    def test_la_forme_composee_est_reconnue(self):
        """`session\job` — la forme qui a rendu la detection inerte."""
        compose = "E8A788" + chr(92) + "BAD9AA"
        log = "\n".join(_LIGNE.format(ident=compose, n=i, score=100, u=9)
                        for i in range(1, 12))
        assert _passes_sans_progres(log, "BAD9AA") == 10

    def test_les_deux_formes_cohabitent_sans_se_melanger(self):
        """Deux jobs en parallele, l un simple et l autre compose."""
        compose = "E8A788" + chr(92) + "BAD9AA"
        fige = "\n".join(_LIGNE.format(ident=compose, n=i, score=100, u=9)
                         for i in range(1, 12))
        vivant = "\n".join(_LIGNE.format(ident="AC4604", n=i, score=100 + i,
                                         u=9 - i) for i in range(1, 9))
        log = fige + "\n" + vivant
        assert _passes_sans_progres(log, "BAD9AA") == 10
        assert _passes_sans_progres(log, "AC4604") == 0


# ---------------------------------------------------------------------------
# ⚠️ LE SUFFIXE DU SCORE A LUI AUSSI DEUX FORMES.
#
#     (46 unrouted)
#     (51 unrouted and 1 violation)
#
# Exiger la parenthese fermante juste apres « unrouted » ne reconnaissait
# AUCUNE ligne du journal reel de la Nucleo — 27 lignes, 0 reconnue, detection
# inerte, tirages de 17 a 24 minutes, carte livree a 80 %.
#
# Troisieme variation de format trouvee sur CE MEME journal, apres le chemin du
# fichier et la forme de l identifiant. Mes fixtures passaient a chaque fois :
# elles etaient ecrites de memoire, pas relevees sur le fichier.
#
# La regle qui en sort : un parseur de format externe se valide contre le
# FICHIER REEL, jamais contre une fixture.
# ---------------------------------------------------------------------------

_LIGNE_REELLE = (
    "2026-08-30 05:41:02.596 INFO   [E8A788" + chr(92) + "BAD9AA] Auto-router "
    "pass #1 on board 'f78fd931bfb067704455632d72055be8' was completed in "
    "20.56 seconds with the score of 641.95 (51 unrouted and 1 violation), "
    "using 1234.00 CPU seconds and 567 MB memory."
)


def test_la_ligne_relevee_sur_le_journal_reel_est_reconnue():
    """Copiee telle quelle depuis /tmp/freerouting/freerouting.log."""
    m = _LIGNE_PASSE_RE.search(_LIGNE_REELLE)
    assert m is not None, "la ligne REELLE n est pas reconnue"
    assert m.group(1) == "BAD9AA"
    assert m.group(2) == "1"
    assert m.group(4) == "51"


def test_le_suffixe_sans_violation_reste_reconnu():
    sans = _LIGNE_REELLE.replace(" and 1 violation", "")
    m = _LIGNE_PASSE_RE.search(sans)
    assert m is not None and m.group(4) == "51"


# ---------------------------------------------------------------------------
# ⚠️ L ECHEC RESTE FRANC — et c est une garde EXISTANTE qui m a corrige.
#
# Quand tous les paliers stagnent, `route_auto` rend une reponse SANS board.
# `banc_exemples.py` plantait alors sur `base64.b64decode(None)`, et j ai
# voulu rendre le board d ENTREE pour eviter le plantage.
#
# `test_aucun_routeur_utilisable_reste_un_echec_franc` l a refuse, et il avait
# raison : un appelant qui ignore `skipped` expedierait une carte NON ROUTEE
# en fabrication, en SILENCE. Un plantage, lui, s entend. Entre les deux
# defaillances, la bruyante est la bonne.
#
# Le defaut etait donc dans le BANC, qui supposait un board sans le verifier.
# ---------------------------------------------------------------------------


def test_l_echec_reste_franc_sans_board_fabrique():
    import inspect
    from routers.routing import route_auto
    src = inspect.getsource(route_auto)
    fin = src[src.rindex("if meilleur is None:"):]
    assert "base64.b64encode(pcb_bytes)" not in fin, (
        "un board d entree rendu ici passerait pour un routage aupres d un "
        "appelant qui ignore `skipped`")


# ---------------------------------------------------------------------------
# ⚠️ Une assertion qui protege un invariant FAUX ne protege rien.
#
# `assert meilleur is not None  # _layer_ladder rend toujours au moins [2]` :
# vrai des PALIERS, faux des RESULTATS — un tirage fige n en produit aucun.
#
# Mesure du 2026-08-30 sur `nucleo-f401` : tous les tirages ont stagne,
# « escalade arretee — 7 paliers sans gain », puis « ECHEC [exception] » et
# RIEN d autre — une `AssertionError` au message vide, impossible a
# diagnostiquer. L assertion transformait un echec previsible en panne muette.
# ---------------------------------------------------------------------------

def test_aucune_assertion_ne_garde_le_resultat_du_routage():
    import inspect
    from routers.routing import route_auto
    src = inspect.getsource(route_auto)
    assert "assert meilleur is not None" not in src, (
        "un tirage fige ne produit aucun resultat : l assertion levera une "
        "AssertionError au message vide au lieu d un echec lisible")


def test_tous_les_tirages_figes_donnent_un_echec_lisible():
    import inspect
    from routers.routing import route_auto
    src = inspect.getsource(route_auto)
    # ⚠️ Fenetre elargie : depuis le 2026-08-31, une TENTATIVE DE RECUPERATION
    # precede l echec. Les jobs abandonnes continuent dans la JVM et finissent
    # seuls ; on va chercher leur cuivre avant de rendre les mains vides.
    # L echec franc reste le dernier mot quand il n y a rien a recuperer — la
    # fenetre de 700 caracteres ne l atteignait plus.
    i = src.index("if meilleur is None:")
    bloc = src[i:i + 2000]
    assert "_recuperer_jobs_abandonnes(" in bloc, (
        "on rend un echec sans avoir tente de recuperer le cuivre existant")
    assert "skipped=True" in bloc
    assert "routed_percent=0" in bloc
    assert "warning=" in bloc, "un echec muet ne se diagnostique pas"
