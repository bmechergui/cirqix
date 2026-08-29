"""Seed du placement — même board ⇒ même RNG, GA séquentiel.

``OptimizationWorkflow`` hybrid n'expose pas de seed. Le GA tire via
``random`` (stdlib) et, avec ``parallel=True``, un ProcessPool rend le seed
inutile. On sème ici, et on force le GA séquentiel.
"""
from __future__ import annotations

import random

from kicad_tools.optim.evolutionary import EvolutionaryConfig

from tools.placement_seed import apply_placement_seed, seed_from_board_bytes


def test_seed_from_board_bytes_is_stable():
    board = b"(kicad_pcb (version 20241201) (generator cirqix))"
    a = seed_from_board_bytes(board)
    b = seed_from_board_bytes(board)
    assert a == b
    assert isinstance(a, int)
    assert a != seed_from_board_bytes(board + b"x")


def test_apply_placement_seed_replays_random():
    apply_placement_seed(42)
    first = [random.random() for _ in range(8)]
    apply_placement_seed(42)
    second = [random.random() for _ in range(8)]
    assert first == second


def test_apply_placement_seed_forces_sequential_ga():
    apply_placement_seed(7)
    cfg = EvolutionaryConfig(generations=2, population_size=4)
    assert cfg.parallel is False
    assert cfg.use_gpu is False
