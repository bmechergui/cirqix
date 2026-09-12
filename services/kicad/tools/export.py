import pcbnew
import logging
import zipfile
import os
import subprocess
import csv


GERBER_LAYERS = {
    "F.Cu":     pcbnew.F_Cu,
    "B.Cu":     pcbnew.B_Cu,
    "F.SilkS":  pcbnew.F_SilkS,
    "B.SilkS":  pcbnew.B_SilkS,
    "F.Mask":   pcbnew.F_Mask,
    "B.Mask":   pcbnew.B_Mask,
    "Edge.Cuts": pcbnew.Edge_Cuts,
}


logger = logging.getLogger(__name__)


def export_gerbers(pcb_path: str, output_dir: str) -> dict:
    board = pcbnew.LoadBoard(pcb_path)
    os.makedirs(output_dir, exist_ok=True)

    ctrl = pcbnew.PLOT_CONTROLLER(board)
    opts = ctrl.GetPlotOptions()
    opts.SetOutputDirectory(output_dir)
    opts.SetUseGerberProtelExtensions(True)
    opts.SetGerberPrecision(6)
    opts.SetCreateGerberJobFile(True)

    # ⚠️ RETIRER DE LA SERIGRAPHIE CE QUI TOMBE SUR DU CUIVRE EXPOSE.
    #
    # Mesure du 2026-09-09 : nos boards portent `subtractmaskfromsilk no`, et
    # le DRC compte jusqu a 136 `silk_over_copper` sur `carte-10`. Ce ne sont
    # pas des erreurs — le board reste fabricable — mais c est ce qui rend les
    # rendus illisibles, et c est le reproche que l utilisateur a formule le
    # 2026-09-08, captures a l appui.
    #
    # ⚠️ LA CAUSE N EST PAS NOTRE PLACEMENT. L essentiel vient des CONTOURS de
    # serigraphie des empreintes, qui traversent leurs propres pastilles : c est
    # normal dans toute bibliotheque KiCad, et cela se traite au TRACE, pas en
    # deplacant des traits. J avais commence par ecrire un module qui degageait
    # les TEXTES — utile, mais il ne touchait qu une petite part du compte.
    #
    # ⚠️ Ce reglage ne CACHE rien : il decoupe la serigraphie la ou elle
    # deborderait sur du cuivre nu, exactement ce que tout fabricant attend.
    # Baisser la taille du texte ou pousser la reference en `F.Fab` aurait fait
    # taire le DRC en emportant l information — faire taire une garde n est pas
    # la satisfaire.
    try:
        opts.SetSubtractMaskFromSilk(True)
    except AttributeError:
        # ⚠️ On le DIT. Un reglage silencieusement absent laisserait croire que
        # la serigraphie est decoupee alors qu elle ne l est pas — et le defaut
        # ne se verrait qu a la fabrication.
        logger.error("export: SetSubtractMaskFromSilk indisponible dans ce "
                     "pcbnew — la serigraphie NE SERA PAS decoupee")

    for name, layer_id in GERBER_LAYERS.items():
        ctrl.SetLayer(layer_id)
        ctrl.OpenPlotfile(name, pcbnew.PLOT_FORMAT_GERBER, name)
        ctrl.PlotLayer()
    ctrl.ClosePlot()

    # Fichiers de perçage
    drill = pcbnew.EXCELLON_WRITER(board)
    drill.SetOptions(False, False, pcbnew.VECTOR2I(0, 0), False)
    drill.SetFormat(True)
    drill.CreateDrillandMapFilesSet(output_dir, True, False)

    # ZIP
    zip_path = os.path.join(output_dir, "gerbers.zip")
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in os.listdir(output_dir):
            if not f.endswith(".zip"):
                zf.write(os.path.join(output_dir, f), f)

    return {
        "status": "ok",
        "zip_path": zip_path,
        "files": [f for f in os.listdir(output_dir) if not f.endswith(".zip")],
    }


def export_step(pcb_path: str, output_dir: str) -> dict:
    os.makedirs(output_dir, exist_ok=True)
    step_path = os.path.join(output_dir, "board.step")

    result = subprocess.run(
        ["kicad-cli", "pcb", "export-step", "--output", step_path, pcb_path],
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        raise RuntimeError(f"kicad-cli STEP export failed: {result.stderr}")

    return {"status": "ok", "step_path": step_path}


def export_bom(pcb_path: str, output_dir: str) -> dict:
    board = pcbnew.LoadBoard(pcb_path)
    os.makedirs(output_dir, exist_ok=True)

    bom_path = os.path.join(output_dir, "bom.csv")
    cpl_path = os.path.join(output_dir, "cpl.csv")

    # BOM CSV (JLCPCB format)
    components: dict[str, dict] = {}
    for fp in board.GetFootprints():
        value = fp.GetValue()
        ref = fp.GetReference()
        lcsc = fp.GetFieldByName("LCSC").GetText() if fp.GetFieldByName("LCSC") else ""

        key = f"{value}_{lcsc}"
        if key not in components:
            components[key] = {"Comment": value, "Designator": [], "Footprint": fp.GetFPIDAsString(), "LCSC": lcsc}
        components[key]["Designator"].append(ref)

    with open(bom_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Comment", "Designator", "Footprint", "LCSC Part #"])
        writer.writeheader()
        for comp in components.values():
            writer.writerow({
                "Comment": comp["Comment"],
                "Designator": ",".join(comp["Designator"]),
                "Footprint": comp["Footprint"],
                "LCSC Part #": comp["LCSC"],
            })

    # CPL CSV (centroid)
    with open(cpl_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Designator", "Mid X", "Mid Y", "Layer", "Rotation"])
        writer.writeheader()
        for fp in board.GetFootprints():
            pos = fp.GetPosition()
            writer.writerow({
                "Designator": fp.GetReference(),
                "Mid X": f"{pcbnew.ToMM(pos.x):.3f}mm",
                "Mid Y": f"{pcbnew.ToMM(pos.y):.3f}mm",
                "Layer": "T" if fp.GetLayer() == pcbnew.F_Cu else "B",
                "Rotation": fp.GetOrientationDegrees(),
            })

    return {
        "status": "ok",
        "bom_path": bom_path,
        "cpl_path": cpl_path,
    }
