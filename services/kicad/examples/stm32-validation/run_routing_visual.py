#!/usr/bin/env python3
"""Route + FINIT (qualité layout) le board STM32 depuis le PLACEMENT FINAL
(output/phase3/3_final.kicad_pcb) — pour inspection visuelle dans KiCad.

Chaîne 100% native kicad-tools, qualité de routage :

  ① kct route            — route TOUS les signaux + VCC en PISTES (+5V/+3.3V
                           renommés en noms non-power le temps du routage, sinon
                           kct route les coule en plan et les exclut du routage),
                           seul GND coulé en plan. Escalade native de couches si
                           backend C++ dispo, sinon 2 couches en local.
  ② kct optimize-traces  — coins 90° → chamfers 45° (--chamfer-size 0.5)
  ③ kct zones add GND    — plan de masse GND sur la face manquante → GND sur
                           F.Cu ET B.Cu (top + bottom). PAS de plan VCC.
  ④ kct zones fill       — remplit les plans GND autour de toutes les pistes ;
                           nécessite kicad-cli

Sorties (dans output/routage/) :
  4_routed.kicad_pcb       <- board final (VCC en pistes, GND top+bottom, 45°)
  4_routed_top/bottom.png  <- rendus 2 faces (kicad-cli)
  report.txt               <- métriques (coins 45°/90°, plans GND, VCC pistes)

Détails d'implémentation Windows :
  • kicad-cli n'est pas dans le PATH → détecté dans C:\\Program Files\\KiCad\\*\\bin
    et injecté dans le PATH des sous-process (sinon zones fill + render échouent
    silencieusement → plan GND vide, c'était la cause du « mauvais routage »).
  • toutes les commandes kct tournent dans un TEMPDIR puis le board final est
    COPIÉ dans output/routage : `kct route -o` écrit directement dans le dossier
    projet échoue sur Windows (writer fsync / watcher .history) et le fichier
    disparaît. Le tempdir contourne ça ; shutil.copy persiste bien.

Usage : python run_routing_visual.py
"""
from __future__ import annotations

import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

_SERVICE_ROOT = Path(__file__).resolve().parents[2]  # services/kicad
_KCT_SRC = _SERVICE_ROOT / "kicad-tools" / "src"
sys.path.insert(0, str(_SERVICE_ROOT))
sys.path.insert(0, str(_KCT_SRC))

from tools.kct_route import parse_routed_pct  # noqa: E402


def _find_kicad_cli() -> Path | None:
    """kicad-cli.exe le plus récent sous C:\\Program Files\\KiCad\\*\\bin."""
    bins = sorted(Path(r"C:\Program Files\KiCad").glob("*/bin/kicad-cli.exe"))
    return bins[-1].parent if bins else None


_KICAD_BIN = _find_kicad_cli()


def _run(args: list[str], timeout_s: int) -> subprocess.CompletedProcess[str]:
    """Lance une commande kct/kicad-cli avec UTF-8 forcé + kicad-cli dans le PATH.

    PYTHONUTF8=1 évite le crash charmap (logs emoji) sur console cp1252 ; le
    PATH enrichi rend kicad-cli visible à `kct zones fill` et au rendu.
    """
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
        "PYTHONPATH": str(_KCT_SRC),
    }
    if _KICAD_BIN:
        env["PATH"] = str(_KICAD_BIN) + os.pathsep + env.get("PATH", "")
    try:
        return subprocess.run(
            args, capture_output=True, text=True, encoding="utf-8",
            errors="replace", env=env, check=False, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired as e:
        out = e.stdout.decode("utf-8", "replace") if isinstance(e.stdout, bytes) else (e.stdout or "")
        print(f"  [timeout] commande tuée après {timeout_s}s (routeur Python pur lent).")
        return subprocess.CompletedProcess(args, returncode=-1, stdout=out, stderr="TIMEOUT")


def _native_backend_available() -> bool:
    r = _run([sys.executable, "-m", "kicad_tools.cli", "build-native", "--check"], timeout_s=30)
    return "available" in r.stdout.lower()


def _copper_layers(pcb: Path) -> int:
    t = pcb.read_text(encoding="utf-8", errors="replace")
    block = re.search(r"\(layers\b(.*?)\n\s*\)", t, re.DOTALL)
    scope = block.group(1) if block else t
    return len(re.findall(r'"(?:F|B|In\d+)\.Cu"', scope)) or 2


def _zone_layers_for_net(pcb: Path, net: str) -> set[str]:
    """Couches cuivre portant déjà une zone du net donné (ex. {'B.Cu'})."""
    t = pcb.read_text(encoding="utf-8", errors="replace")
    layers: set[str] = set()
    for m in re.finditer(r"\(zone\b", t):
        blk = t[m.start():m.start() + 300]
        z_net = re.search(r'\(net "([^"]*)"', blk)
        z_layer = re.search(r'\(layer "([^"]+)"', blk)
        if z_net and z_layer and z_net.group(1) == net:
            layers.add(z_layer.group(1))
    return layers


# VCC routé en PISTES (pas en plan) : kct route classe +5V/+3.3V comme nets
# « power » par leur NOM et les coule en zones (auto_pour) + les exclut du
# routage. On les renomme en noms non-power AVANT le routage → le routeur les
# traite en signaux (pistes) ; on renomme en sens inverse APRÈS. Seul GND reste
# coulé en plan. (Connectivité préservée : les pads référencent le net par
# NUMÉRO, pas par nom — seul le label change.)
_VCC_RENAME = {"+5V": "P5V0", "+3.3V": "P3V3"}


def _rename_nets(text: str, mapping: dict[str, str]) -> str:
    for old, new in mapping.items():
        text = re.sub(rf'\(net (\d+) "{re.escape(old)}"\)', rf'(net \1 "{new}")', text)
    return text


def _segments_for_nets(pcb: Path, nets: tuple[str, ...]) -> dict[str, int]:
    """Nombre de segments de piste par net nommé (pour vérifier VCC en pistes)."""
    from collections import Counter
    t = pcb.read_text(encoding="utf-8", errors="replace")
    netmap = dict(re.findall(r'\(net (\d+) "([^"]*)"', t))
    counts: Counter = Counter()
    for blk in re.findall(r"\(segment\b.*?\n\s*\)", t, re.DOTALL):
        nn = re.search(r"\(net (\d+)\)", blk)
        if nn:
            counts[netmap.get(nn.group(1), nn.group(1))] += 1
    return {n: counts.get(n, 0) for n in nets}


def _angle_stats(pcb: Path) -> dict[str, int]:
    """Classe les VRAIS COINS de piste (2 segments d'un même net/layer qui se
    rejoignent) par angle de virage : 90° (angle droit, à éviter), 45° (chamfer,
    bon), ~180° (droit continu). Un segment droit H/V seul n'est PAS un coin —
    seul le virage compte (la règle « jamais de 90° » porte sur les virages)."""
    t = pcb.read_text(encoding="utf-8", errors="replace")
    from collections import defaultdict

    # Parse chaque bloc (segment ...) indépendamment du format/ordre des tokens :
    # kicad-cli (KiCad 9/10) pretty-print sur plusieurs lignes et insère un
    # (uuid ...) entre (layer) et (net) — d'où extraction champ par champ.
    pts: dict[tuple, list[tuple[float, float]]] = defaultdict(list)
    for blk in re.findall(r"\(segment\b.*?\n\s*\)", t, re.DOTALL):
        m_s = re.search(r"\(start ([\d.eE+-]+) ([\d.eE+-]+)\)", blk)
        m_e = re.search(r"\(end ([\d.eE+-]+) ([\d.eE+-]+)\)", blk)
        m_l = re.search(r'\(layer "([^"]+)"\)', blk)
        m_n = re.search(r"\(net (\d+)\)", blk)
        if not (m_s and m_e and m_l and m_n):
            continue
        x1, y1 = float(m_s.group(1)), float(m_s.group(2))
        x2, y2 = float(m_e.group(1)), float(m_e.group(2))
        net, layer = m_n.group(1), m_l.group(1)
        pts[(net, layer, round(x1, 3), round(y1, 3))].append((x2 - x1, y2 - y1))
        pts[(net, layer, round(x2, 3), round(y2, 3))].append((x1 - x2, y1 - y2))

    corner_90 = corner_45 = 0
    for dirs in pts.values():
        if len(dirs) != 2:
            continue
        (ax, ay), (bx, by) = dirs
        a, b = math.degrees(math.atan2(ay, ax)), math.degrees(math.atan2(by, bx))
        turn = abs((b - (a + 180)) % 360)
        turn = min(turn, 360 - turn)
        if abs(turn - 90) < 10:
            corner_90 += 1
        elif abs(turn - 45) < 10 or abs(turn - 135) < 10:
            corner_45 += 1
    return {
        "segments": len(re.findall(r"\(segment", t)),
        "vias": len(re.findall(r"\(via", t)),
        "corner_90": corner_90,
        "corner_45": corner_45,
        "filled_polygon": len(re.findall(r"\(filled_polygon", t)),
    }


def main() -> int:
    example_dir = Path(__file__).parent
    placed = example_dir / "output" / "phase3" / "3_final.kicad_pcb"
    if not placed.exists():
        print(f"Erreur : placement final introuvable — {placed}")
        print("Lance d'abord : python run_phase3_visual.py")
        return 1

    out = example_dir / "output" / "routage"
    out.mkdir(parents=True, exist_ok=True)

    print("=" * 64)
    print("ROUTAGE QUALITÉ — kct route → optimize-traces (45°) → zones fill (GND)")
    print("=" * 64)
    print(f"kicad-cli : {_KICAD_BIN or 'ABSENT (zones fill + rendu indisponibles)'}")
    native = _native_backend_available()
    print(f"backend C++ : {'dispo' if native else 'absent (2 couches en local)'}\n")

    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "in.kicad_pcb"
        board = Path(tmp) / "routed.kicad_pcb"
        # VCC renommés en noms non-power → routés en PISTES (pas en plan).
        src.write_text(
            _rename_nets(placed.read_text(encoding="utf-8", errors="replace"), _VCC_RENAME),
            encoding="utf-8",
        )

        # ── ① ROUTE (VCC en pistes, seul GND coulé) ──────────────────────
        if native:
            route_flags = ["--auto-layers", "--max-layers", "6"]
            route_timeout = 300
        else:
            route_flags = ["--layers", "2"]  # local : 2 couches, rapide et viewable
            route_timeout = 150
        print(f"① kct route {' '.join(route_flags)} --auto-fix (VCC en pistes)")
        r = _run(
            [sys.executable, "-m", "kicad_tools.cli", "route", str(src),
             "-o", str(board), *route_flags, "--auto-fix", "--seed", "42",
             "--timeout", str(route_timeout)],
            timeout_s=route_timeout + 90,
        )
        routed_pct = parse_routed_pct(r.stdout)
        if not board.exists():
            partial = board.with_name("routed_partial.kicad_pcb")
            if partial.exists():
                shutil.copy(str(partial), str(board))
            else:
                print("Échec : route n'a produit aucun board.")
                print((r.stderr or r.stdout)[-300:])
                return 1
        # Renomme les VCC en sens inverse (P5V0→+5V, P3V3→+3.3V).
        board.write_text(
            _rename_nets(board.read_text(encoding="utf-8", errors="replace"),
                         {v: k for k, v in _VCC_RENAME.items()}),
            encoding="utf-8",
        )
        print(f"   -> {routed_pct}% · {_angle_stats(board)['segments']} segments\n")

        # ── ② OPTIMIZE-TRACES (45°) ──────────────────────────────────────
        print("② kct optimize-traces --chamfer-size 0.5 (coins 90° → 45°)")
        _run([sys.executable, "-m", "kicad_tools.cli", "optimize-traces",
              str(board), "--chamfer-size", "0.5"], timeout_s=120)
        s = _angle_stats(board)
        print(f"   -> coins 45°={s['corner_45']} · coins 90°={s['corner_90']}\n")

        # ── ③ PLAN DE MASSE GND sur F.Cu ET B.Cu ─────────────────────────
        # `kct route` coule déjà GND sur une face (souvent B.Cu) ; on AJOUTE
        # le plan GND sur la face manquante → plan de masse top + bottom.
        # zones add exige -o (ne réécrit pas en place) → fichier temp distinct.
        have = _zone_layers_for_net(board, "GND")
        print(f"③ plan GND — déjà sur {sorted(have) or 'aucune face'}")
        for layer in ("F.Cu", "B.Cu"):
            if layer in have:
                continue
            withz = board.with_name(f"with_gnd_{layer.replace('.', '_')}.kicad_pcb")
            rz = _run([sys.executable, "-m", "kicad_tools.cli", "zones", "add",
                       str(board), "--net", "GND", "--layer", layer,
                       "--priority", "0", "-o", str(withz)], timeout_s=60)
            if withz.exists():
                shutil.copy(str(withz), str(board))
                print(f"   + plan GND ajouté sur {layer}")
            else:
                print(f"   ! échec ajout GND {layer}: {(rz.stderr or rz.stdout)[-120:]}")
        print(f"   -> plan GND sur {sorted(_zone_layers_for_net(board, 'GND'))}\n")

        # ── ④ ZONES FILL (remplit GND top+bottom + power islands) ────────
        if _KICAD_BIN:
            print("④ kct zones fill (remplit les plans GND + îlots power)")
            _run([sys.executable, "-m", "kicad_tools.cli", "zones", "fill",
                  str(board)], timeout_s=120)
            print(f"   -> {_angle_stats(board)['filled_polygon']} polygones remplis\n")
        else:
            print("④ zones fill SAUTÉ (kicad-cli absent — plans non remplis)\n")

        # ── Copie du board propre + rendu PNG ────────────────────────────
        final = out / "4_routed.kicad_pcb"
        # nettoie les sorties confuses d'anciens runs
        for stale in ("5_pipeline.kicad_pcb", "5_pipeline_partial.kicad_pcb",
                      "4_routed_partial.kicad_pcb"):
            try:
                (out / stale).unlink(missing_ok=True)
            except OSError:
                pass  # fichier ouvert dans KiCad → on laisse

        shutil.copy(str(board), str(final))
        if not final.exists():
            print(f"Échec : copie du board vers {final} a disparu.")
            return 1

        if _KICAD_BIN:
            for side, dst in (("top", out / "4_routed_top.png"),
                              ("bottom", out / "4_routed_bottom.png")):
                rp = _run([str(_KICAD_BIN / "kicad-cli.exe"), "pcb", "render",
                           "--side", side, "-o", str(dst), str(final)], timeout_s=120)
                if rp.returncode != 0:
                    print(f"   (rendu {side} échoué : {(rp.stderr or '').strip()[-140:]})")

    stats = _angle_stats(final)
    n_layers = _copper_layers(final)
    gnd_layers = sorted(_zone_layers_for_net(final, "GND"))
    both_planes = {"F.Cu", "B.Cu"}.issubset(set(gnd_layers))
    vcc = _segments_for_nets(final, ("+5V", "+3.3V"))
    vcc_zones = _zone_layers_for_net(final, "+5V") | _zone_layers_for_net(final, "+3.3V")
    report = [
        "ROUTAGE STM32 — VCC en pistes · plan GND top+bottom · 45°",
        "=" * 64,
        f"Input            : {placed.name} (placement final auto_place)",
        f"Output           : {final.name}  (+ 4_routed_top.png, 4_routed_bottom.png)",
        f"kicad-cli        : {_KICAD_BIN or 'ABSENT'}",
        f"Backend C++      : {'dispo' if native else 'absent (2 couches local)'}",
        "",
        f"Couches cuivre   : {n_layers}",
        f"Routé            : {routed_pct}%",
        f"Segments         : {stats['segments']}  (vias {stats['vias']})",
        f"Coins 45° (bon)  : {stats['corner_45']}",
        f"Coins 90° (à éviter) : {stats['corner_90']}",
        f"Plan GND         : {', '.join(gnd_layers) or 'aucun'} "
        f"({'top + bottom OK' if both_planes else 'INCOMPLET'})",
        f"VCC en pistes    : +5V={vcc['+5V']} seg · +3.3V={vcc['+3.3V']} seg "
        f"({'PAS de plan VCC OK' if not vcc_zones else 'reste un plan: ' + ', '.join(vcc_zones)})",
        f"Polygones remplis: {stats['filled_polygon']} "
        f"({'OUI' if stats['filled_polygon'] else 'NON — kicad-cli manquant'})",
    ]
    (out / "report.txt").write_text("\n".join(report) + "\n", encoding="utf-8")

    print("=" * 64)
    print(f"Board   : {final}")
    if _KICAD_BIN:
        print(f"Rendus  : {out / '4_routed_top.png'} + 4_routed_bottom.png")
    print(f"Rapport : {out / 'report.txt'}")
    print(f"Qualité : plan GND {', '.join(gnd_layers)} · {stats['corner_45']} coins 45° · "
          f"{stats['corner_90']} coins 90°")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
