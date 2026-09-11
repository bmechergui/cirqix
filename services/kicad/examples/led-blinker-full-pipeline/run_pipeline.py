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
# ⚠️ VALAIT 600 s JUSQU AU 2026-09-06, pour TOUTES les requetes. Le placement
# d une carte de 47 composants (`carte-07-multi-io`) le depasse : le client a
# raccroche sur `TimeoutError` pendant que le service travaillait encore, et le
# pipeline est sorti en echec sur un placement qui allait aboutir.
#
# C est la famille de defaut deja inscrite dans CLAUDE.md — « le plafond n etait
# pas UN endroit, mais QUATRE » : un budget client plus serre que le service
# rend inatteignable tout ce qui est plus lent que lui. Le service, lui,
# s accorde 900 s pour le placement et jusqu a 3600 s pour le routage.
#
# ⚠️ Ce n est PAS une limite de patience mais une RESSOURCE : `kct route` rend
# la main des 100 % atteint. La relever ne coute rien sur une carte simple —
# `carte-01` finit en 50 s.
_TIMEOUT_S = 3600


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
    # ⚠️ FIGE : la boucle ci-dessous repart du board GENERE a chaque
    # essai. Repartir du board deja place enchainerait les placements les
    # uns sur les autres au lieu de tirer a neuf.
    pcb_gen = pcb
    _done(t, taille=f"{len(pcb)}o")

    # ⑤⑥ Placement + routage — EN BOUCLE, on garde le MEILLEUR ------------
    #
    # ⚠️ CE PIPELINE NE FAISAIT QU UN SEUL PASSAGE. La production, elle,
    # boucle : `shouldRetryPlacement` re-tire quand le routage n atteint pas
    # 100 %, `shouldRetryForDrc` quand le DRC refuse, jusqu a 15 iterations.
    # Le banc n avait pas cette boucle — et je relancais donc a la main, depuis
    # l exterieur, ce qui existait deja a l interieur.
    #
    # Remarque de l utilisateur le 2026-09-10 : « je veux une solution generale
    # pour toutes les cartes ; pourquoi plusieurs tirages ? ». Elle est juste :
    # des tirages externes sont un pansement sur une boucle manquante.
    #
    # ⚠️ POURQUOI RE-TIRER LE PLACEMENT ET PAS SEULEMENT LE ROUTAGE. Les
    # deux sont stochastiques, mais c est le PLACEMENT qui decide de ce que le
    # routeur peut faire : ce depot mesure 6, 8 et 12 connexions manquantes sur
    # trois tirages du meme schema. Re-router un mauvais placement ne le sauve
    # pas.
    #
    # ⚠️ ON GARDE LE MEILLEUR, JAMAIS LE DERNIER. Meme regle que
    # `_palier_meilleur` du routeur, et pour la meme raison : un tirage tardif
    # peut etre pire. Classement sur (routé décroissant, violations croissantes).
    #
    # ⚠️ ET ON S ARRETE DES QUE C EST BON. Un board a 100 % sans violation
    # n a rien a gagner d un tirage de plus, et chaque tirage coute 5 a 40
    # minutes sur les cartes denses.
    tentatives = int(schema.get("tentatives", 4))
    plafond = int(schema.get("max_layers", 2))
    budget = int(schema.get("route_budget_s", 1800))

    meilleur = None          # (routé, -violations, place_b64, route_b64, res)
    echecs = []
    agrandissements = 0      # D-2026-09-11-b : voir `taille_suivante`
    for essai in range(1, max(1, tentatives) + 1):
      # ⚠️ UN ESSAI QUI PLANTE NE DOIT PAS EMPORTER LES SUIVANTS.
      #
      # Mesure du 2026-09-10 : `carte-08`, `09` et `10` echouent TROIS FOIS SUR
      # TROIS avec `RemoteDisconnected`. Le worker uvicorn meurt pendant le
      # POST-TRAITEMENT du routage — replacement des vias, coulee des plans,
      # couture des ilots — sur une assertion NATIVE de pcbnew :
      #
      #     property.h(607): assert "m_choices.GetCount() > 0" failed
      #                      in PROPERTY_ENUM(): No enum choices defined
      #
      # Neuf occurrences en quarante minutes. Elle ne frappe que les cartes
      # denses : plus de zones et de vias a post-traiter, donc plus d occasions
      # de la declencher.
      #
      # ⚠️ CE N EST PAS LA MEMOIRE, et je l ai cru toute la journee. Le cgroup
      # du conteneur dit `oom_kill = 0`, crete 3,4 Go sur 7,6 ; la JVM occupe
      # 1,4 Go REELS — le « 495 Go » du journal Freerouting est un compteur
      # cumule, pas une occupation.
      #
      # Le remede de fond est d isoler ce post-traitement dans un processus
      # ENFANT, comme `cmaes_runner.py` le fait deja — le depot en fait meme une
      # regle. En attendant, on rend la BOUCLE resiliente : un essai perdu coute
      # un essai, pas la carte.
      try:
          t = _step(5, "call_agent_placement → POST /place/auto (essai %d/%d)"
                    % (essai, tentatives))
          res_p = _post("/place/auto", {
              "kicad_pcb_b64": _b64(pcb_gen),
              "board_width_mm": board_w,
              "board_height_mm": board_h,
          })
          place = _unb64(res_p["kicad_pcb_b64"])
          _done(t, placés=res_p.get("placed_count"), status=res_p.get("status"))

          t = _step(6, "call_agent_routing → POST /route/auto (essai %d/%d)"
                    % (essai, tentatives))
          res_r = _post("/route/auto", {"kicad_pcb_b64": _b64(place),
                                        "layers": plafond, "timeout_s": budget})
          routed = res_r.get("routed_percent", 0) or 0
          route = _unb64(res_r["kicad_pcb_b64"]) if res_r.get("kicad_pcb_b64") else place
          manquantes = int(res_r.get("unrouted_count") or 0)
          _done(t, routé="%s%%" % routed, couches=res_r.get("layers"),
                vias=res_r.get("via_count"), warning=res_r.get("warning"))

          # ⚠️ LE DRC DECIDE, PAS LE ROUTEUR. Mesure du 2026-09-10 sur
          # `carte-08` : le routeur annonce « 100 %, 0 manquante », la boucle
          # s arrete satisfaite, et le DRC rend `drc_clean=False` avec
          # `unconnected_items:2`. Les deux comptent des choses differentes et se
          # contredisent — c est exactement la raison d etre de
          # `shouldRetryForDrc` en production, et j avais reproduit ici le defaut
          # qu elle evite.
          #
          # ⚠️ On ne retient donc QUE les erreurs (`severity == "error"`) : la
          # serigraphie qui deborde est un avertissement, elle ne doit pas faire
          # re-tirer un placement de vingt minutes.
          t = _step(7, "call_agent_drc \u2192 POST /drc/auto (essai %d/%d)"
                    % (essai, tentatives))
          res_d = _post("/drc/auto", {"kicad_pcb_b64": _b64(route), "auto_fix": True})
          if res_d.get("kicad_pcb_b64"):
              route = _unb64(res_d["kicad_pcb_b64"])
          vio = res_d.get("violations") or []
          erreurs = len([v for v in vio if str(v.get("severity", "")).lower() == "error"])
          _done(t, clean=res_d.get("drc_clean"), violations=len(vio), erreurs=erreurs)

          note = (routed, -erreurs, -manquantes)
          if meilleur is None or note > meilleur[0]:
              meilleur = (note, place, route, res_r)
              print("   essai %d retenu (%s%%, %d erreur(s) DRC)"
                    % (essai, routed, erreurs))
          else:
              print("   essai %d ecarte (%s%% contre %s%% deja obtenus)"
                    % (essai, routed, meilleur[0][0]))

          if routed >= 100 and erreurs == 0:
              print("   100 % atteint — on arrete les essais")
              break
          # D-2026-09-11-b : au plafond de couches sans 100 % / 0 erreur, on
          # AGRANDIT la carte pour l essai suivant plutot que de re-tirer le
          # meme espace. Le service rend le contour a la taille demandee.
          nw, nh, agrandissements_apres = taille_suivante(
              board_w, board_h, routed, erreurs, res_r.get("layers"), plafond, agrandissements)
          if agrandissements_apres > agrandissements:
              print("   carte AGRANDIE pour l essai suivant : %sx%s -> %sx%s mm "
                    "(routee a %s%% au plafond de %d couches, %d erreur(s))"
                    % (board_w, board_h, nw, nh, routed, plafond, erreurs))
              board_w, board_h, agrandissements = nw, nh, agrandissements_apres
      except SystemExit:
          raise
      except Exception as e:  # noqa: BLE001
          # ⚠️ ON LE DIT, ET ON COMPTE. Un essai perdu en silence ferait passer
          # « 4 essais » pour une mesure alors qu un seul aurait tourne.
          echecs.append("essai %d : %s" % (essai, str(e)[:70]))
          print("   essai %d PERDU (%s) — on passe au suivant"
                % (essai, str(e)[:70]))

    if echecs:
        print("   %d essai(s) perdu(s) sur %d : %s"
              % (len(echecs), tentatives, " · ".join(echecs)))
    if meilleur is None:
        # ⚠️ Aucun essai n a abouti : on echoue FRANCHEMENT plutot que de livrer
        # le board place non route en le faisant passer pour un resultat.
        raise SystemExit("aucun des %d essais n a abouti — %s"
                         % (tentatives, " · ".join(echecs) or "raison inconnue"))

    _, place, pcb, res = meilleur
    routed = meilleur[0][0]
    _write(out / "5_placed.kicad_pcb", place)
    _write(out / "6_routed.kicad_pcb", pcb)

    # ⑥b Reasoner — déclenché DÉTERMINISTIQUEMENT si <100% (règle orchestrateur)
    if routed < 100:
        t = _step(6.5, "shouldRescueRouting → POST /reason/auto")
        # ⚠️ LE SAUVETAGE NE DOIT PAS JETER LE BOARD OBTENU. Mesure du 2026-09-10,
        # `carte-09` : essai 1 retenu a 98 %, essai 4 PERDU (worker tue), puis
        # le reasoner tape sur le meme worker mort -> Traceback, AUCUN SUMMARY.
        # Un board a 98 % existait et n a pas ete livre. Le reasoner est un
        # BONUS : s il echoue, on garde ce qu on a et on le dit.
        try:
            res = _post("/reason/auto", {"kicad_pcb_b64": _b64(pcb)})
        except Exception as e:  # noqa: BLE001
            print("   reasoner PERDU (%s) — on garde le board a %s%%" % (str(e)[:60], routed))
            res = {}
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
    # ⚠️ LE DRC A DEJA TOURNE DANS LA BOUCLE, sur chaque essai — c est lui qui
    # a departage. On le rejoue ici UNIQUEMENT pour le rapport final : sans ce
    # passage, `violations` resterait vide et le SUMMARY annoncerait zero.
    t = _step(7, "call_agent_drc \u2192 POST /drc/auto (rapport final)")
    # ⚠️ Meme protection que le reasoner : le board est DEJA ecrit dans
    # `6_routed.kicad_pcb`. Un service tombe apres coup ne doit pas effacer le
    # verdict de la boucle — on rend le DRC de l essai retenu, deja mesure.
    try:
        res = _post("/drc/auto", {"kicad_pcb_b64": _b64(pcb), "auto_fix": True})
    except Exception as e:  # noqa: BLE001
        print("   DRC final PERDU (%s) — verdict de la boucle conserve" % str(e)[:60])
        res = {"drc_clean": meilleur[0][1] == 0, "violations": [], "skipped": False}
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
    try:
        res = _post("/export/all", {"kicad_pcb_b64": _b64(pcb), "project_id": "led-blinker"})
    except Exception as e:  # noqa: BLE001
        print("   export PERDU (%s) — le board route est livre sans Gerbers" % str(e)[:60])
        res = {"files": []}
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


_AGRANDISSEMENT = 1.2      # +20 % par cote, mesure carte-08 : 98 % -> 100 % a 2 couches
_AGRANDISSEMENTS_MAX = 2   # borne la surface : x1,44 par cote au plus


def taille_suivante(board_w: float, board_h: float, routed: int, erreurs: int,
                    couches: int | None, plafond: int, agrandissements: int,
                    maxi: int = _AGRANDISSEMENTS_MAX) -> tuple[float, float, int]:
    """D-2026-09-11-b : une carte routee a son PLAFOND de couches sans atteindre
    100 % / 0 erreur est AGRANDIE de 20 % pour l essai suivant, au plus `maxi`
    fois — au lieu de re-tirer indefiniment le meme espace.

    Mesure du 2026-09-11 sur carte-08 (56 composants, 125 x 95 mm) : 98 %
    depuis 24 h a 2, 4 et 6 couches ; le meme schema a 150 x 114 mm route a
    100 % / 0 erreur a 2 couches au premier tirage. Le levier des cartes
    denses n est ni le routeur ni les couches, c est l espace — et une carte un
    peu plus grande a 2 couches coute moins cher qu une carte a 98 % sur 6.
    Rend (largeur, hauteur, agrandissements) pour l essai suivant."""
    au_plafond = couches is None or int(couches) >= int(plafond)
    if (routed >= 100 and erreurs == 0) or not au_plafond or agrandissements >= maxi:
        return (board_w, board_h, agrandissements)
    return (round(board_w * _AGRANDISSEMENT, 1), round(board_h * _AGRANDISSEMENT, 1),
            agrandissements + 1)


def _fail(stage: str, res: dict[str, Any]) -> int:
    print(f"    !! échec {stage} : {res.get('error')}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
