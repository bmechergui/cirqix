#!/usr/bin/env python3
"""Pipeline Cirqix COMPLET rejoué contre le service FastAPI réel (HTTP).

Question de ce cas : « la chaîne description → Gerbers tient-elle de bout en
bout, avec le backend C++ disponible ? »

Là où le pipeline de prod appelle un LLM, c'est le DRIVER LLM qui fournit la
sortie (cf. README) :
  - agent Schéma (Haiku 4.5)  → `input/schema.json`, écrit par le driver
  - agent Reasoner (Haiku)    → non nécessaire si le routage atteint 100% ;
                                sinon le service tente `kct reason` heuristique
                                (ANTHROPIC_API_KEY absente du conteneur).

Chaque étape écrit son artefact dans `<out>/`, pour pouvoir diffé/rejouer.
Aucun secret n'est écrit : le token vient de l'environnement.

Usage :
    export KICAD_SERVICE_URL=http://127.0.0.1:8766
    export KICAD_SERVICE_TOKEN=<token du conteneur>
    python run_pipeline.py [out_dir]
"""
from __future__ import annotations

import base64
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

_HERE = Path(__file__).resolve().parent
_DEFAULT_OUT = _HERE / "output"
_TIMEOUT_S = 600


def _service() -> tuple[str, str]:
    url = os.environ.get("KICAD_SERVICE_URL", "http://127.0.0.1:8766").rstrip("/")
    token = os.environ.get("KICAD_SERVICE_TOKEN", "")
    if not token:
        sys.exit("KICAD_SERVICE_TOKEN manquant — toutes les routes sauf /health l'exigent.")
    return url, token


def _post(path: str, payload: dict[str, Any]) -> dict[str, Any]:
    url, token = _service()
    req = urllib.request.Request(
        f"{url}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"HTTP {exc.code} sur {path} : {body}") from exc


def _b64(data: str | bytes) -> str:
    raw = data.encode("utf-8") if isinstance(data, str) else data
    return base64.b64encode(raw).decode("ascii")


def _unb64(data: str) -> bytes:
    """Renvoie des OCTETS, jamais du texte.

    Les .kicad_pcb transitent en base64 et doivent être réécrits à l'identique :
    un aller-retour par `str` avec `errors="replace"` (perte silencieuse) ou une
    écriture texte sous Windows (traduction LF→CRLF) suffit à rendre le fichier
    illisible par KiCad, alors que le service, lui, avait bien travaillé. Les
    artefacts sur disque doivent être fidèles pour être rejouables.
    """
    return base64.b64decode(data)


def _write(path: Path, data: str | bytes) -> None:
    path.write_bytes(data.encode("utf-8") if isinstance(data, str) else data)


def _step(n: int, label: str) -> float:
    print(f"\n{'=' * 62}\n[{n}] {label}\n{'=' * 62}")
    return time.monotonic()


def _done(started: float, **facts: Any) -> None:
    detail = " · ".join(f"{k}={v}" for k, v in facts.items())
    print(f"    -> {detail}  ({time.monotonic() - started:.1f}s)")


def main() -> int:
    out = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else _DEFAULT_OUT
    out.mkdir(parents=True, exist_ok=True)

    schema = json.loads((_HERE / "input" / "schema.json").read_text(encoding="utf-8"))
    board_w = schema["board_width_mm"]
    board_h = schema["board_height_mm"]
    base = {
        "components": schema["components"],
        "nets": schema["nets"],
        "connections": schema["connections"],
        "board_width_mm": board_w,
        "board_height_mm": board_h,
        "project_id": "led-blinker",
    }
    print(f"Schéma (driver LLM) : {len(schema['components'])} composants, "
          f"{len(schema['connections'])} nets, board {board_w}x{board_h}mm")

    # ① Schéma ---------------------------------------------------------------
    t = _step(1, "call_agent_schema → POST /schematic/generate")
    res = _post("/schematic/generate", base)
    if not res.get("success"):
        return _fail("schéma", res)
    sch = res["kicad_sch_content"]
    _write(out / "1_schema.kicad_sch", sch)
    _done(t, taille=f"{len(sch)}o")

    # ② ERC ------------------------------------------------------------------
    t = _step(2, "call_agent_erc → POST /erc")
    res = _post("/erc", {"kicad_sch_b64": _b64(sch), "auto_fix": True})
    if res.get("kicad_sch_b64"):
        sch = _unb64(res["kicad_sch_b64"])
        _write(out / "2_erc.kicad_sch", sch)
    _done(t, clean=res.get("erc_clean"), violations=len(res.get("violations", [])),
          fixed=res.get("fixed_count"), skipped=res.get("skipped"),
          engine=res.get("engine"))

    # ④ Génération PCB (③ footprint : déjà résolus dans le schéma du driver) --
    t = _step(4, "call_agent_gen_pcb → POST /pcb/generate")
    # Le schéma se transmet en base64 (`kicad_sch_b64`) : c'est lui qui active les
    # niveaux 1 (kicad-tools PCBFromSchematic) et 2 (pcbnew) de generate_pcb ;
    # sans lui les deux sont court-circuités et seul le fallback TS reste.
    res = _post("/pcb/generate", {**base, "kicad_sch_b64": _b64(sch)})
    if not res.get("success"):
        return _fail("gen_pcb", res)
    pcb = res["kicad_pcb_content"]
    _write(out / "4_gen.kicad_pcb", pcb)
    _done(t, taille=f"{len(pcb)}o")

    # ⑤ Placement ------------------------------------------------------------
    t = _step(5, "call_agent_placement → POST /place/auto")
    res = _post("/place/auto", {
        "kicad_pcb_b64": _b64(pcb),
        "board_width_mm": board_w,
        "board_height_mm": board_h,
    })
    pcb = _unb64(res["kicad_pcb_b64"])
    _write(out / "5_placed.kicad_pcb", pcb)
    _done(t, placés=res.get("placed_count"), status=res.get("status"))

    # ⑥ Routage --------------------------------------------------------------
    t = _step(6, "call_agent_routing → POST /route/auto")
    res = _post("/route/auto", {"kicad_pcb_b64": _b64(pcb), "layers": 2})
    routed = res.get("routed_percent", 0)
    if res.get("kicad_pcb_b64"):
        pcb = _unb64(res["kicad_pcb_b64"])
        _write(out / "6_routed.kicad_pcb", pcb)
    _done(t, routé=f"{routed}%", couches=res.get("layers"), vias=res.get("via_count"),
          skipped=res.get("skipped"), warning=res.get("warning"))

    # ⑥b Reasoner — déclenché DÉTERMINISTIQUEMENT si <100% (règle orchestrateur)
    if routed < 100:
        t = _step(6.5, "shouldRescueRouting → POST /reason/auto")
        res = _post("/reason/auto", {"kicad_pcb_b64": _b64(pcb)})
        if res.get("kicad_pcb_b64") and res.get("routed_percent", 0) >= routed:
            pcb = _unb64(res["kicad_pcb_b64"])
            _write(out / "6b_rescued.kicad_pcb", pcb)
            routed = res["routed_percent"]
        for s in res.get("steps", [])[:10]:
            print(f"       · {s}")
        _done(t, routé=f"{routed}%", llm=res.get("used_llm"), warning=res.get("warning"))
    else:
        print("\n[6b] Reasoner NON déclenché — routage déjà à 100% (comportement attendu).")

    # ⑦ DRC ------------------------------------------------------------------
    t = _step(7, "call_agent_drc → POST /drc/auto")
    res = _post("/drc/auto", {"kicad_pcb_b64": _b64(pcb), "auto_fix": True})
    if res.get("kicad_pcb_b64"):
        pcb = _unb64(res["kicad_pcb_b64"])
        _write(out / "7_drc.kicad_pcb", pcb)
    drc_clean, drc_skipped = res.get("drc_clean"), res.get("skipped")
    violations = res.get("violations", [])
    _done(t, clean=drc_clean, violations=len(violations), fixed=res.get("fixed_count"),
          skipped=drc_skipped, warning=res.get("warning"))
    for v in violations[:8]:
        print(f"       ! {v.get('type', '?')}: {str(v.get('message', ''))[:90]}")

    # ⑧ Export ---------------------------------------------------------------
    t = _step(8, "call_agent_export → POST /export/all")
    res = _post("/export/all", {"kicad_pcb_b64": _b64(pcb), "project_id": "led-blinker"})
    if res.get("zip_b64"):
        (out / "8_gerbers.zip").write_bytes(base64.b64decode(res["zip_b64"]))
    _done(t, fichiers=len(res.get("files", [])), devis=f"${res.get('quote_usd')}",
          skipped=res.get("skipped"), warning=res.get("warning"))
    for f in res.get("files", []):
        print(f"       + {f}")

    # Verdict ----------------------------------------------------------------
    print(f"\n{'=' * 62}")
    # Ligne de synthèse parsable — sert aux campagnes de mesure (le placement GA
    # est stochastique : toute conclusion demande plusieurs runs).
    from collections import Counter
    types = Counter(str(v.get("type", "?")) for v in violations)
    breakdown = ",".join(f"{k}:{n}" for k, n in sorted(types.items(), key=lambda kv: -kv[1]))
    print(f"SUMMARY routed={routed} drc_violations={len(violations)} "
          f"drc_clean={drc_clean} files={len(res.get('files', []))} types={breakdown or '-'}")
    ok = routed == 100 and drc_clean is True and not drc_skipped and bool(res.get("files"))
    print(f"VERDICT : routage {routed}% · DRC clean={drc_clean} (skipped={drc_skipped}) "
          f"· {len(res.get('files', []))} fichiers exportés")
    print("PIPELINE COMPLET OK" if ok else "PIPELINE INCOMPLET — voir les étapes ci-dessus")
    print(f"Artefacts : {out}")
    return 0 if ok else 1


def _fail(stage: str, res: dict[str, Any]) -> int:
    print(f"    !! échec {stage} : {res.get('error')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
