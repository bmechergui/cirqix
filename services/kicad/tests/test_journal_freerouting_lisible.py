"""Le journal de Freerouting doit EXISTER, sinon la detection est inerte.

⚠️ Defaut mesure le 2026-08-29. `_passes_sans_progres` lit
`/tmp/freerouting/freerouting.log` — sa seule fenetre sur l interieur du
routeur, `cancel` repondant 501 et `max_passes` etant ignore. Mais
l entrypoint lancait la JVM SANS `--user_data_path` : Freerouting n ecrivait
alors aucun fichier, ses lignes de passe partant sur la sortie standard du
conteneur, invisibles depuis le service.

Le repertoire n existait que parce que je l avais cree en redemarrant la JVM a
la main pendant mes essais. En production la detection ne se serait JAMAIS
declenchee — et son echec est SILENCIEUX par conception : sans journal elle
rend 0 passe plate, ce qui signifie « tout va bien ».

Un palier condamne reprenait donc ses 44 minutes d attente.
"""
from __future__ import annotations

from pathlib import Path

from routers.routing import _FREEROUTING_LOG

_ENTRYPOINT = Path(__file__).resolve().parents[1] / "docker-entrypoint.sh"


def test_l_entrypoint_fixe_le_chemin_du_journal():
    texte = _ENTRYPOINT.read_text(encoding="utf-8")
    assert "--user_data_path=" in texte, (
        "sans --user_data_path, Freerouting n ecrit aucun journal et la "
        "detection de stagnation est inerte")


def test_le_chemin_de_l_entrypoint_est_CELUI_QUE_LE_CODE_LIT():
    """Deux chemins qui divergent = detection morte, sans le moindre message."""
    texte = _ENTRYPOINT.read_text(encoding="utf-8")
    repertoire = str(_FREEROUTING_LOG.parent)
    assert f"--user_data_path={repertoire}" in texte, (
        f"le code lit {_FREEROUTING_LOG}, l entrypoint ecrit ailleurs")


def test_le_repertoire_est_cree_avant_le_lancement():
    texte = _ENTRYPOINT.read_text(encoding="utf-8")
    i_mkdir = texte.find("mkdir -p " + str(_FREEROUTING_LOG.parent))
    i_java = texte.find("java -jar /opt/freerouting")
    assert i_mkdir != -1, "repertoire jamais cree"
    assert i_mkdir < i_java, "repertoire cree APRES le lancement de la JVM"


# ---------------------------------------------------------------------------
# ⚠️ Les trois tests ci-dessus ont PASSE sur un entrypoint casse.
#
# Une edition programmatique y avait ecrit `\n` LITTERAL — deux caracteres —
# au lieu d une fin de ligne :
#
#     --api_server.enabled=true \n    --user_data_path=/tmp/freerouting &
#
# `bash -n` valide cette ligne : `\n` y est simplement la lettre `n` echappee,
# donc un ARGUMENT de plus passe a la JVM. Le script se lance, Freerouting
# demarre, et le chemin n est jamais applique.
#
# Chercher une sous-chaine ne suffit donc pas : `--user_data_path=/tmp/...`
# etait bien present, sur une ligne inexploitable. Meme famille que le
# backspace trouve dans une regex quelques heures plus tot — un echappement
# interprete trop tot, invisible a la lecture.
# ---------------------------------------------------------------------------

def test_l_entrypoint_ne_contient_aucun_echappement_litteral():
    """Un antislash suivi de `n` ou `t` = edition programmatique ratee.

    ⚠️ Ce test lui-meme s est trompe a sa premiere ecriture : `b"\n"` y avait
    perdu un antislash et cherchait un vrai saut de ligne, donc echouait sur
    tout fichier normal. Troisieme occurrence du meme piege dans la journee —
    un backspace dans une regex, un `\n` dans le shell, celui-ci. Les codes
    d octets explicites sont la seule ecriture non ambigue.
    """
    brut = _ENTRYPOINT.read_bytes()
    ANTISLASH, N, T = 0x5C, 0x6E, 0x74
    for octet, nom in ((N, "n"), (T, "t")):
        assert bytes([ANTISLASH, octet]) not in brut, (
            f"antislash-{nom} litteral dans l entrypoint : une edition a "
            f"interprete l echappement trop tot, la ligne est inexploitable")


def test_la_continuation_de_ligne_est_une_vraie_fin_de_ligne():
    """Chaque `\` de continuation doit etre suivi d un saut de ligne."""
    brut = _ENTRYPOINT.read_bytes()
    for i, octet in enumerate(brut):
        if octet == 0x5C:  # backslash
            suivant = brut[i + 1] if i + 1 < len(brut) else 0
            assert suivant in (0x0A, 0x5C, 0x60, 0x24, 0x22), (
                f"backslash suivi de {chr(suivant)!r} a l octet {i} — "
                "continuation de ligne cassee")
