"""Validation manuelle — routage en mode STRICT sur les pads sans net.

Question industrielle (2026-07-19) : les boards routés à 100 % le sont parce
que kicad-tools exempte les pads ``(net 0 "")`` de son validateur de clearance
(arbitrage upstream #3281). Sur un LQFP-48 STM32F103C8T6 aucune broche n'est
réellement NC : ce sont des broches silicium inutilisées, donc une piste qui
les touche est un court-circuit réel (mesuré : 9 shorting_items + 9
solder_mask_bridge, tous contre le pad 33 de U2, voisin de SWDIO).

Ce script assigne un net unique à chaque pad ``(net 0 "")`` — ils redeviennent
des obstacles normaux — puis route. Il mesure le coût en complétion sur
PLUSIEURS placements (tirages GA distincts), le retry placement étant le levier
qui débloque habituellement les cas difficiles.

Usage (dans le conteneur cirqix-kicad, backend C++ requis) :
    python scripts/strict_nc_route.py <placed.kicad_pcb> [<placed2.kicad_pcb> …]

N'est PAS appelé par les agents en production — les endpoints utilisent
``tools/kct_route.py`` directement.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]          # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_SERVICE_ROOT / "kicad-tools" / "src"))

from tools.kct_route import route_kct  # noqa: E402

_ROUTE_TIMEOUT_S = 300


def assign_nc_nets(text: str) -> tuple[str, int]:
    """Donne un net unique à chaque pad ``(net 0 "")``.

    Renvoie (board modifié, nombre de pads convertis). Les déclarations de nets
    correspondantes sont ajoutées après la dernière déclaration existante — un
    net référencé par un pad mais non déclaré rendrait le board invalide.
    """
    next_net = max([int(n) for n in re.findall(r'\(net (\d+) "', text)] or [0]) + 1
    declarations: list[str] = []

    def _assign(_m: re.Match) -> str:
        nonlocal next_net
        n = next_net
        next_net += 1
        declarations.append(f'  (net {n} "NC_{n}")')
        return f'(net {n} "NC_{n}")'

    out = re.sub(r'\(net 0 ""\)', _assign, text)
    if not declarations:
        return out, 0

    last = None
    for m in re.finditer(r'\n\s*\(net \d+ "[^"]*"\)', text):
        last = m
    if last:
        idx = out.index(last.group(0)) + len(last.group(0))
        out = out[:idx] + "\n" + "\n".join(declarations) + out[idx:]
    return out, len(declarations)


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2

    for arg in sys.argv[1:]:
        board = Path(arg)
        if not board.is_file():
            print(f"{board} : introuvable")
            continue

        text, converted = assign_nc_nets(board.read_text(encoding="utf-8"))
        strict_bytes = text.encode("utf-8")

        permissive = route_kct(board.read_bytes(), timeout_s=_ROUTE_TIMEOUT_S)[1]
        strict = route_kct(strict_bytes, timeout_s=_ROUTE_TIMEOUT_S)[1]

        print(f"MESURE {board.parent.parent.name} : {converted} pads convertis | "
              f"permissif {permissive}% | strict {strict}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
