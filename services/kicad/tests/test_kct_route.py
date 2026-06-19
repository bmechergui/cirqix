"""Tests parse_routed_pct — le parser du % de routage natif kct route.

Régression : sur le board STM32 réel, kct route émet « Nets routed: 5/9 (56%) »
mais l'ancien parser attrapait le PREMIER « (NN%) » du stdout (une ligne de
progression intermédiaire, ex. 11%/22%) → routed_percent largement sous-évalué.
Conséquence prod : routers/routing.py compare routed_pct à _MIN_ROUTED_PCT pour
accepter/rejeter le résultat kicad-tools → un bon routage à 56% pouvait être
rejeté à tort comme 11%.
"""
import sys
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[1]  # services/kicad
sys.path.insert(0, str(_SERVICE_ROOT))

from tools.kct_route import parse_routed_pct  # noqa: E402


# stdout réel (extrait) de `kct route --strategy negotiated` sur 3_final.kicad_pcb.
# Contient des lignes de progression (11%, 22%) AVANT le résultat final 56%.
_PARTIAL_STDOUT = """\
Routing attempt 1 ... (11%)
Routing attempt 2 ... (22%)
Best result so far: 2L with 5/9 (56%)
Result: Best result on 2 layers (56% completion)
  Nets routed:     5/9
PARTIAL: Best result 56% on 2 layers
Routing Incomplete (56% connected)
  Nets routed: 5/9 (56%)
  Partial routes: 3/9 (33%) -- have segments, not all pads connected
  Unrouted: 1/9 (11%) -- no segments at all
"""

_COMPLETE_STDOUT = """\
Routing attempt 1 ... (40%)
Routing Complete
  Nets routed: 9/9 (100%)
"""

# Aucun net à router : tous les power nets coulés en zones cuivre.
_NO_ROUTE_STDOUT = "All power nets poured as copper zones. Nothing to route.\n"

# Ancien format historique de kct route (back-compat).
_OLD_FORMAT_STDOUT = "Routed: 8/8 nets (success)\n"


def test_parse_partial_uses_final_tally_not_progress_percent():
    # 5/9 = 56%, PAS 11% (ligne de progression) ni 11% (Unrouted: 1/9).
    assert parse_routed_pct(_PARTIAL_STDOUT) == 56


def test_parse_complete():
    assert parse_routed_pct(_COMPLETE_STDOUT) == 100


def test_parse_no_route_defaults_to_complete():
    assert parse_routed_pct(_NO_ROUTE_STDOUT) == 100


def test_parse_old_format_backcompat():
    assert parse_routed_pct(_OLD_FORMAT_STDOUT) == 100


def test_unrouted_line_is_not_mistaken_for_tally():
    # « Unrouted: 1/9 » contient le sous-mot "routed" mais ne doit jamais être
    # lu comme le compte de nets routés.
    assert parse_routed_pct("  Nets routed: 7/9 (78%)\n  Unrouted: 2/9\n") == 78
