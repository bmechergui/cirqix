#!/bin/sh
# ============================================================
# Cirqix KiCad Service — entrypoint
#
# kicad-tools est installé en ÉDITABLE depuis /opt/kicad-tools. En dev ce
# chemin est un bind-mount de l'hôte (services/kicad/kicad-tools) → le code
# est live. Mais le bind-mount masque le .so C++ compilé dans l'image (l'hôte
# Windows n'a pas de .so Linux), donc on (re)build le backend natif ici si
# `kct build-native --check` ne le voit pas disponible. En prod (sans mount),
# le .so de l'image est présent → --check passe → on saute le build (start rapide).
# ============================================================
set -e

KT_DIR="${KICAD_TOOLS_DIR:-/opt/kicad-tools}"

echo "[entrypoint] kicad-tools dir: ${KT_DIR}"

# Réinstalle en éditable seulement si l'import casse (ex: chemin de mount différent
# du build, métadonnées absentes). Idempotent et silencieux si déjà lié.
if ! python3 -c "import kicad_tools" >/dev/null 2>&1; then
    echo "[entrypoint] kicad_tools non importable — réinstallation éditable..."
    pip3 install --no-cache-dir -e "${KT_DIR}[placement,drc,geometry,native]" || \
        echo "[entrypoint] WARNING: pip install -e a échoué"
fi

# Backend C++ A* (10-100× plus rapide). Build si absent (cas bind-mount).
if kct build-native --check 2>&1 | grep -qi "available"; then
    echo "[entrypoint] backend natif C++ : disponible"
else
    echo "[entrypoint] backend natif C++ manquant — build (cmake+g++)..."
    if (cd "${KT_DIR}" && kct build-native --force); then
        echo "[entrypoint] backend natif C++ : build OK"
    else
        echo "[entrypoint] WARNING: build natif échoué — fallback routeur Python pur"
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
