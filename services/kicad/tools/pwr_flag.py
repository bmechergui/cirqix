"""Un `PWR_FLAG` par rail d'alimentation — sinon l'ERC de KiCad refuse le schema.

⚠️ Mesure du 2026-09-14 sur le schema NE555, par la VRAIE route `/erc` : apres
le passage des labels en globaux il restait DEUX erreurs, toutes deux
`power_pin_not_driven` — « Input Power pin not driven by any Output Power
pins » sur `#PWR001.1` et `#PWR006.1`.

C'est le comportement normal de KiCad : un symbole `power:VCC` ou `power:GND`
porte une broche `power_in`. Personne ne la PILOTE tant qu'aucune broche
`power_out` ne touche le meme net. Sur une carte reelle, c'est le regulateur
ou le connecteur d'entree qui pilote ; sur un schema genere, rien ne le
declare, et l'usage etabli est de poser un `PWR_FLAG` — un symbole dont
l'unique broche est `power_out`.

La geometrie rend la pose sure : la broche de `PWR_FLAG` est a (0, 0) de son
symbole, exactement comme celle de `power:VCC` et `power:GND` (verifie dans
`/usr/share/kicad/symbols/power.kicad_sym`). Poser le drapeau AUX MEMES
coordonnees qu'un symbole d'alimentation place donc les deux broches au meme
point : elles sont sur le meme net, sans le moindre fil a tracer.

⚠️ Reparation : au moindre doute — definition introuvable, schema illisible —
on rend le contenu TEL QUEL. Un schema sans drapeau est refuse par l'ERC, ce
qui se voit ; un schema casse par une reparation ne se voit pas.
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Optional

__all__ = ["poser_pwr_flags", "definition_pwr_flag", "rails_sans_drapeau"]

_LIB_ID_PWR_FLAG = "power:PWR_FLAG"
# Les symboles d'alimentation de KiCad : `power:VCC`, `power:GND`, `power:+3V3`…
_LIB_ID_ALIM_RE = re.compile(r'\(lib_id "power:([^"]+)"\)')
_AT_RE = re.compile(r"\(at\s+(-?[\d.]+)\s+(-?[\d.]+)\s+(-?[\d.]+)\s*\)")
_VALEUR_RE = re.compile(r'\(property "Value" "([^"]*)"')
_REFERENCE_RE = re.compile(r'\(property "Reference" "([^"]*)"')


def _blocs_symboles(texte: str, depuis: int) -> list[tuple[int, int]]:
    """Les bornes de chaque bloc `(symbol …)` de premier niveau apres `depuis`.

    On COMPTE LES PARENTHESES : une expression reguliere sur un bloc imbrique
    coupe au mauvais endroit, faute déjà payée plusieurs fois dans ce dépôt.
    """
    bornes: list[tuple[int, int]] = []
    i = texte.find("(symbol", depuis)
    while i != -1:
        prof = 0
        for j in range(i, len(texte)):
            if texte[j] == "(":
                prof += 1
            elif texte[j] == ")":
                prof -= 1
                if prof == 0:
                    bornes.append((i, j + 1))
                    i = texte.find("(symbol", j + 1)
                    break
        else:
            break
    return bornes


def definition_pwr_flag(racine_symboles: Optional[str] = None) -> Optional[str]:
    """La definition canonique de `PWR_FLAG`, lue dans la bibliotheque de KiCad.

    Rend None si la bibliotheque est absente : on ne fabrique pas un symbole
    approximatif, on renonce a poser le drapeau.
    """
    racine = racine_symboles or os.environ.get("KICAD_SYMBOL_DIR") or "/usr/share/kicad/symbols"
    chemin = Path(racine) / "power.kicad_sym"
    try:
        texte = chemin.read_text(encoding="utf-8")
        i = texte.index('(symbol "PWR_FLAG"')
    except Exception:  # noqa: BLE001 — bibliotheque absente ou illisible
        return None
    prof = 0
    for j in range(i, len(texte)):
        if texte[j] == "(":
            prof += 1
        elif texte[j] == ")":
            prof -= 1
            if prof == 0:
                return texte[i:j + 1].replace('(symbol "PWR_FLAG"', f'(symbol "{_LIB_ID_PWR_FLAG}"', 1)
    return None


def rails_sans_drapeau(sch_content: str) -> dict[str, tuple[float, float]]:
    """Les rails d'alimentation du schema, et OU poser leur drapeau.

    Rend `{nom du rail: (x, y)}` — la position d'un de ses symboles
    d'alimentation, ou la broche du drapeau doit tomber. Un rail qui porte
    deja un `PWR_FLAG` n'y figure pas.
    """
    debut = sch_content.find("(lib_symbols")
    apres_lib = 0
    if debut != -1:
        prof = 0
        for j in range(debut, len(sch_content)):
            if sch_content[j] == "(":
                prof += 1
            elif sch_content[j] == ")":
                prof -= 1
                if prof == 0:
                    apres_lib = j + 1
                    break

    rails: dict[str, tuple[float, float]] = {}
    deja: set[str] = set()
    for i, f in _blocs_symboles(sch_content, apres_lib):
        bloc = sch_content[i:f]
        m_lib = _LIB_ID_ALIM_RE.search(bloc)
        if not m_lib:
            continue
        nom = m_lib.group(1)
        m_val = _VALEUR_RE.search(bloc)
        rail = m_val.group(1) if m_val else nom
        if nom == "PWR_FLAG" or rail == "PWR_FLAG":
            # Le drapeau lui-meme : on note le rail qu il couvre deja.
            deja.add(rail)
            continue
        m_at = _AT_RE.search(bloc)
        if not m_at:
            continue
        rails.setdefault(rail, (float(m_at.group(1)), float(m_at.group(2))))
    return {r: p for r, p in rails.items() if r not in deja}


def _fin_de_bloc(texte: str, debut: int) -> int:
    """L'index de la parenthese qui ferme le bloc ouvert a `debut`, ou -1."""
    prof = 0
    for j in range(debut, len(texte)):
        if texte[j] == "(":
            prof += 1
        elif texte[j] == ")":
            prof -= 1
            if prof == 0:
                return j
    return -1


def avec_definition_pwr_flag(sch_content: str, racine_symboles: Optional[str] = None) -> Optional[str]:
    """Le schema avec la definition de `PWR_FLAG` dans `lib_symbols`, ou None.

    Rend le contenu tel quel si la definition y est deja ; None si elle est
    introuvable ou si le schema n'a pas de `lib_symbols` lisible.
    """
    if f'(symbol "{_LIB_ID_PWR_FLAG}"' in sch_content:
        return sch_content
    definition = definition_pwr_flag(racine_symboles)
    i = sch_content.find("(lib_symbols")
    fin_lib = _fin_de_bloc(sch_content, i) if i != -1 else -1
    if definition is None or fin_lib == -1:
        return None
    return sch_content[:fin_lib] + "\t\t" + definition + "\n\t" + sch_content[fin_lib:]


def ajouter_pwr_flag(
    sch_content: str, x: float, y: float, racine_symboles: Optional[str] = None
) -> Optional[str]:
    """Pose UN `PWR_FLAG` dont la broche tombe en (x, y), ou None si impossible."""
    sortie = avec_definition_pwr_flag(sch_content, racine_symboles)
    if sortie is None:
        return None
    fin = sortie.rstrip()
    if not fin.endswith(")"):
        return None
    reference = f"#FLG{_prochaine_reference(sortie):02d}"
    return fin[:-1] + _instance_pwr_flag(x, y, reference) + ")\n"


def retirer_pwr_flag(sch_content: str, reference: str) -> tuple[str, bool]:
    """Retire l'instance `PWR_FLAG` de reference donnee. Rend (contenu, retire ?)."""
    debut = sch_content.find("(lib_symbols")
    apres_lib = _fin_de_bloc(sch_content, debut) + 1 if debut != -1 else 0
    for i, f in _blocs_symboles(sch_content, apres_lib):
        bloc = sch_content[i:f]
        if f'(lib_id "{_LIB_ID_PWR_FLAG}")' in bloc and f'(property "Reference" "{reference}"' in bloc:
            avant = sch_content[:i].rstrip("\t ")
            return avant + sch_content[f:].lstrip("\n"), True
    return sch_content, False


def _drapeaux_existants(sch_content: str) -> set[str]:
    """Les rails couverts par un `PWR_FLAG` deja pose (idempotence)."""
    couverts: set[str] = set()
    for i, f in _blocs_symboles(sch_content, 0):
        bloc = sch_content[i:f]
        if f'(lib_id "{_LIB_ID_PWR_FLAG}")' not in bloc:
            continue
        m_at = _AT_RE.search(bloc)
        if m_at:
            couverts.add(f"{m_at.group(1)},{m_at.group(2)}")
    return couverts


def _prochaine_reference(sch_content: str) -> int:
    """Le premier numero `#FLGnn` libre."""
    utilises = {int(m.group(1)) for m in re.finditer(r'"#FLG0*(\d+)"', sch_content)}
    n = 1
    while n in utilises:
        n += 1
    return n


def _instance_pwr_flag(x: float, y: float, reference: str) -> str:
    return (
        "\t(symbol\n"
        f'\t\t(lib_id "{_LIB_ID_PWR_FLAG}")\n'
        f"\t\t(at {x} {y} 0)\n"
        "\t\t(unit 1)\n"
        "\t\t(exclude_from_sim no)\n"
        "\t\t(in_bom yes)\n"
        "\t\t(on_board yes)\n"
        "\t\t(dnp no)\n"
        f'\t\t(uuid "{uuid.uuid4()}")\n'
        f'\t\t(property "Reference" "{reference}"\n'
        f"\t\t\t(at {x} {y - 3.81} 0)\n"
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n"
        "\t\t)\n"
        '\t\t(property "Value" "PWR_FLAG"\n'
        f"\t\t\t(at {x} {y - 5.08} 0)\n"
        "\t\t\t(effects\n\t\t\t\t(font\n\t\t\t\t\t(size 1.27 1.27)\n\t\t\t\t)\n\t\t\t\t(hide yes)\n\t\t\t)\n"
        "\t\t)\n"
        '\t\t(pin "1"\n'
        f'\t\t\t(uuid "{uuid.uuid4()}")\n'
        "\t\t)\n"
        "\t\t(instances\n"
        '\t\t\t(project ""\n'
        '\t\t\t\t(path "/"\n'
        f'\t\t\t\t\t(reference "{reference}")\n'
        "\t\t\t\t\t(unit 1)\n"
        "\t\t\t\t)\n"
        "\t\t\t)\n"
        "\t\t)\n"
        "\t)\n"
    )


def poser_pwr_flags(sch_content: str, racine_symboles: Optional[str] = None) -> str:
    """Pose un `PWR_FLAG` sur chaque rail d'alimentation qui n'en a pas.

    Idempotente : un rail deja couvert est laisse tel quel. Rend le contenu
    inchange — identite comprise — quand il n'y a rien a poser, quand la
    definition du symbole est introuvable, ou au moindre echec.
    """
    if not sch_content:
        return sch_content
    try:
        rails = rails_sans_drapeau(sch_content)
        if not rails:
            return sch_content
        deja = _drapeaux_existants(sch_content)
        a_poser = {r: p for r, p in rails.items() if f"{p[0]},{p[1]}" not in deja}
        if not a_poser:
            return sch_content

        sortie = avec_definition_pwr_flag(sch_content, racine_symboles)
        if sortie is None:
            return sch_content  # sans definition, on ne pose rien

        n = _prochaine_reference(sortie)
        blocs = []
        for _rail, (x, y) in sorted(a_poser.items()):
            blocs.append(_instance_pwr_flag(x, y, f"#FLG{n:02d}"))
            n += 1
        fin = sortie.rstrip()
        if not fin.endswith(")"):
            return sch_content
        return fin[:-1] + "".join(blocs) + ")\n"
    except Exception:  # noqa: BLE001 — une reparation ne casse jamais un schema
        return sch_content
