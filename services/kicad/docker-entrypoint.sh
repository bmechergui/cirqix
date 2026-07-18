#!/bin/sh
# ============================================================
# Cirqix KiCad Service — entrypoint
#
# kicad-tools est installé en ÉDITABLE depuis /opt/kicad-tools dans l'image.
# Le compose sécurisé ne masque pas ce chemin : le backend C++ compilé reste
# disponible et une mise à jour du sous-module impose un rebuild de l'image.
# ============================================================
set -e

KT_DIR="${KICAD_TOOLS_DIR:-/opt/kicad-tools}"

echo "[entrypoint] kicad-tools dir: ${KT_DIR}"

# L'image valide cet import au build. Le runtime est volontairement immuable :
# une installation cassée doit échouer explicitement, pas tenter de modifier le venv.
if ! python3 -c "import kicad_tools" >/dev/null 2>&1; then
    echo "[entrypoint] ERROR: kicad_tools non importable dans l'image immuable"
    exit 1
fi

# Backend C++ A* (10-100× plus rapide). Le build conditionnel reste un fallback
# pour les images personnalisées; le compose standard utilise l'artefact existant.
if kct build-native --check 2>&1 | grep -qi "available"; then
    echo "[entrypoint] backend natif C++ : disponible"
else
    if [ -w "${KT_DIR}" ]; then
        echo "[entrypoint] backend natif C++ manquant — build (cmake+g++)..."
        if (cd "${KT_DIR}" && kct build-native --force); then
            echo "[entrypoint] backend natif C++ : build OK"
        else
            echo "[entrypoint] WARNING: build natif échoué — fallback routeur Python pur"
        fi
    else
        echo "[entrypoint] backend natif absent et sources read-only — fallback routeur Python pur"
    fi
fi

# Xvfb (pcbnew headless) + Freerouting (1 JVM persistante, REST port 37864)
Xvfb :99 -screen 0 1024x768x24 -ac &
java -jar /opt/freerouting/freerouting.jar \
    --api_server.enabled=true \
    --api_server-endpoints=http://127.0.0.1:37864 &

# Laisse Xvfb + la JVM Freerouting démarrer avant uvicorn
sleep 5

# 4 workers = 4 processus séparés (pcbnew n'est PAS thread-safe — cf. CLAUDE.md)
exec uvicorn main:app --host 0.0.0.0 --port 8766 --workers 4
