"""Vérifier qu'une empreinte EXISTE avant de générer le board — et la retrouver.

## Le défaut, et pourquoi corriger une carte ne suffisait pas

Mesure du 2026-09-09 sur `carte-05-capteur-i2c`. Le schéma déclarait :

    Package_LGA:LGA-8_2.5x2.5mm_P0.65mm

Ce nom **n'existe pas** dans KiCad. La bibliothèque livre l'empreinte du BME280
sous `Bosch_LGA-8_2.5x2.5mm_P0.65mm_ClockwisePinNumbering` — préfixe fabricant et
suffixe de numérotation horaire, parce que ce capteur ne suit pas la convention
LGA habituelle.

Conséquence : `add_component` rendait `None`, le composant disparaissait, et la
carte sortait **« 100 % routée, 0 erreur » SANS SON CAPTEUR**. Un composant
absent n'a aucune connexion manquante à signaler ; le DRC juge ce qui est sur la
carte, jamais ce qui devrait y être.

⚠️ **CORRIGER LE NOM DANS CE SCHÉMA-LÀ NE CORRIGE RIEN.** La prochaine carte qui
déclare une empreinte inexistante reperdra ses composants de la même façon. Le
nom vient d'un modèle de langage : il sera **plausible et faux** aussi souvent
qu'on lui demandera. C'est la remarque de l'utilisateur — « je veux toujours une
solution générale pour marcher avec tous les types de cartes ».

## Ce que ce module fait

Avant de générer, pour chaque composant :

1. **L'empreinte existe-t-elle ?** Vérification par le natif
   (`_find_footprint` de `kicad_tools.cli.lib`), qui connaît les chemins de
   bibliothèques de l'installation.
2. **Sinon, on cherche la vraie.** Dans la même bibliothèque, on retient le
   fichier dont le nom CONTIENT celui demandé — c'est exactement le cas
   `Bosch_<demandé>_ClockwisePinNumbering` — puis, à défaut, le plus proche par
   similarité de chaîne.
3. **On journalise, toujours.** Trouvée ou non.

⚠️ **ON NE DEVINE PAS AU-DELÀ DE CE QUI EST SÛR.** Un remplacement se fait
uniquement si le candidat contient le nom demandé, ou s'il est très proche ET
seul de son espèce. Poser une empreinte qui a le mauvais nombre de pastilles ou
le mauvais pas serait pire que de perdre le composant : le board partirait en
fabrication avec un boîtier qui ne se soude pas.

⚠️ **CE N'EST PAS L'AGENT FOOTPRINT.** `call_agent_footprint` RÉSOUT une
empreinte manquante par une cascade (KiCad → pgvector → LCSC → SnapMagic → IA).
Ici on traite le cas qu'il ne voit pas : une empreinte **déclarée**, donc jamais
signalée comme `unresolved`, mais qui n'existe pas sous ce nom.
"""
from __future__ import annotations

import difflib
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Similarité minimale pour accepter un candidat qui ne CONTIENT pas le nom
# demandé. 0,80 laisse passer un suffixe ou un préfixe, jamais un autre boîtier.
_SIMILARITE_MINIMALE = 0.80


def _dossier_de_bibliotheque(bibliotheque: str) -> Path | None:
    """Le répertoire `.pretty` d'une bibliothèque, via la détection NATIVE."""
    try:
        from kicad_tools.cli.lib import detect_kicad_library_path
        chemins = detect_kicad_library_path()
    except Exception as e:  # noqa: BLE001
        logger.warning("empreintes: detection des bibliotheques indisponible (%s)", e)
        return None
    racine = getattr(chemins, "footprints_path", None)
    if not racine:
        return None
    nom = bibliotheque if bibliotheque.endswith(".pretty") else bibliotheque + ".pretty"
    dossier = Path(racine) / nom
    return dossier if dossier.is_dir() else None


def existe(reference_complete: str) -> bool:
    """L'empreinte `LIB:NOM` existe-t-elle ? Vérification native."""
    if ":" not in reference_complete:
        return False
    bib, nom = reference_complete.split(":", 1)
    try:
        from kicad_tools.cli.lib import _find_footprint
        return _find_footprint(bib, nom) is not None
    except Exception:  # noqa: BLE001
        # ⚠️ Repli PRUDENT : on regarde le fichier nous-mêmes plutôt que de
        # rendre `True`. Rendre « elle existe » sur une panne de détection
        # ferait taire exactement le défaut qu'on cherche.
        dossier = _dossier_de_bibliotheque(bib)
        return bool(dossier and (dossier / (nom + ".kicad_mod")).is_file())


def trouver_la_vraie(reference_complete: str) -> str | None:
    """Le nom réel de l'empreinte demandée, ou `None` si on n'est pas sûr.

    ⚠️ On préfère AVOUER l'ignorance à poser un boîtier approchant : une
    empreinte au mauvais pas ne se soude pas, et le board partirait en
    fabrication sans que rien ne le dise.
    """
    if ":" not in reference_complete:
        return None
    bib, nom = reference_complete.split(":", 1)
    dossier = _dossier_de_bibliotheque(bib)
    if dossier is None:
        logger.warning("empreintes: bibliotheque %r introuvable", bib)
        return None

    disponibles = [f.stem for f in dossier.glob("*.kicad_mod")]
    if not disponibles:
        return None

    # 1. Le nom demandé est CONTENU dans un nom réel. C'est le cas du BME280 :
    #    `Bosch_<demande>_ClockwisePinNumbering`. Sans ambiguïté possible s'il
    #    n'y en a qu'un.
    contenants = [d for d in disponibles if nom in d]
    if len(contenants) == 1:
        return "%s:%s" % (bib, contenants[0])
    if len(contenants) > 1:
        # ⚠️ Plusieurs candidats : on ne tranche PAS. Choisir au hasard entre
        # deux boîtiers voisins est le genre d erreur qui ne se voit qu'à la
        # refusion.
        logger.error("empreintes: %r a %d candidats (%s) — aucun choix sur",
                     reference_complete, len(contenants),
                     ", ".join(sorted(contenants)[:4]))
        return None

    # 2. Le plus proche par similarité, et SEULEMENT s'il est nettement seul.
    proches = difflib.get_close_matches(nom, disponibles, n=2,
                                        cutoff=_SIMILARITE_MINIMALE)
    if len(proches) == 1:
        return "%s:%s" % (bib, proches[0])
    if len(proches) > 1:
        logger.error("empreintes: %r a plusieurs voisins proches (%s) — "
                     "aucun choix sur", reference_complete, ", ".join(proches))
    return None


def verifier_et_corriger(composants: list) -> tuple[int, list[str]]:
    """Vérifie chaque empreinte déclarée ; corrige celles qu'on retrouve.

    `composants` est modifié sur place. Rend `(corrigees, introuvables)`.

    ⚠️ ON NE LÈVE PAS. La cascade de génération sait retomber, et
    `_composants_perdus` refuse déjà un board incomplet. Ce module apporte ce
    qui manquait : le NOM du coupable, avant que le composant ne disparaisse.
    """
    corrigees, introuvables = 0, []
    for c in composants or []:
        ref = getattr(c, "ref", None) or (c.get("ref") if isinstance(c, dict) else None)
        fp = getattr(c, "footprint", None) or (c.get("footprint") if isinstance(c, dict) else None)
        if not fp or existe(fp):
            continue

        vraie = trouver_la_vraie(fp)
        if vraie:
            logger.warning("empreintes: %s — %r n existe pas, remplacee par %r",
                           ref, fp, vraie)
            if isinstance(c, dict):
                c["footprint"] = vraie
            else:
                c.footprint = vraie
            corrigees += 1
        else:
            # ⚠️ On le DIT, fort. Sans cela le composant disparaitra du board
            # sans un mot, et la carte sortira « 100 % routee » sans lui.
            logger.error("empreintes: %s — %r N EXISTE PAS et aucun "
                         "remplacement sur ; le composant sera PERDU",
                         ref, fp)
            introuvables.append("%s (%s)" % (ref, fp))
    return corrigees, introuvables
