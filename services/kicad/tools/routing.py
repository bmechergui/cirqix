import subprocess
import tempfile
import pcbnew


def route_with_freerouting(pcb_path: str, output_path: str, timeout: int = 300) -> dict:
    """
    Pipeline : .kicad_pcb → .dsn → Freerouting (Java) → .ses → .kicad_pcb
    Timeouts : 90s (simple) | 300s (4 couches) | 600s (8 couches)
    """
    board = pcbnew.LoadBoard(pcb_path)

    with tempfile.TemporaryDirectory() as tmp:
        dsn_path = f"{tmp}/board.dsn"
        ses_path = f"{tmp}/board.ses"

        pcbnew.ExportSpecctraSession(board, dsn_path)

        result = subprocess.run(
            [
                "java", "-jar", "/opt/freerouting/freerouting.jar",
                "-de", dsn_path,
                "-do", ses_path,
                "-mp", "100",
                "-dr", f"{tmp}/freerouting.log",
            ],
            capture_output=True,
            timeout=timeout,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(f"Freerouting failed: {result.stderr[:500]}")

        pcbnew.ImportSpecctraSession(board, ses_path)

        # Ground pours
        for zone in board.Zones():
            # KiCad 10 : ZONE.SetFilled a disparu (renomme SetIsFilled) ; sous
        # KiCad 9 les deux existent. La boucle ne s executait JAMAIS —
        # aucun board de la chaine ne portait de zone — donc l erreur est
        # restee invisible jusqu au 2026-08-21, ou les plans de masse
        # coules avant le routage l ont declenchee : le processus enfant
        # sortait en AttributeError et Freerouting echouait aux deux
        # niveaux. Garde : tests/test_zone_setisfilled.py.
        # ⚠️ Selon le board, `board.Zones()` rend des `ZONE` types ou de
        # simples `SwigPyObject` sans methodes — constate le 2026-08-21 sur
        # un board issu de `kct stitch` :
        #     AttributeError: 'SwigPyObject' object has no attribute
        #                     'SetIsFilled'
        # On ne force le drapeau que s il est atteignable : `ZONE_FILLER.Fill`
        # le pose de toute facon. Le nom differe aussi entre KiCad 9
        # (`SetFilled`) et 10 (`SetIsFilled`).
        marque = getattr(zone, "SetIsFilled", None) or getattr(zone, "SetFilled", None)
        if marque is not None:
            marque(True)
        filler = pcbnew.ZONE_FILLER(board)
        filler.Fill(board.Zones())

        pcbnew.SaveBoard(output_path, board)

    return {"status": "ok", "path": output_path}
