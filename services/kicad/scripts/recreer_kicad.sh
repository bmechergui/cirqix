#!/usr/bin/env bash
# Recree le conteneur KiCad SANS jamais le perdre.
#
# ## Pourquoi ce script existe
#
# Le service meurt par intermittence pendant un routage HTTP — un
# `RemoteDisconnected` cote client, un `Child process died` cote journal, sans
# ligne applicative. Un conteneur NEUF (`/tmp` vierge, pas de job Freerouting
# zombie, pas de verrou X orphelin) le fait disparaitre : mesure du 2026-09-05,
# 9 routages sur 9, et re-mesure du 2026-09-07 apres deux occurrences.
#
# `docker restart` ne suffit PAS : il conserve `/tmp`.
#
# ## Ce que ce script corrige
#
# La sequence naive est `docker rm -f` puis `docker run`. Le 2026-09-07, une
# tache interrompue ENTRE LES DEUX a laisse la machine sans service du tout —
# et cela ressemblait a un conteneur qui « se supprime tout seul ». Il ne se
# supprimait pas : on le supprimait, et on n arrivait pas jusqu au `run`.
#
# Ici l ancien est RENOMME, pas detruit. Il n est supprime qu une fois le
# nouveau declare sain ; si le nouveau echoue, l ancien est remis en service.
# A aucun instant il n existe zero conteneur recuperable.
#
# ⚠️ `docker-compose` v1 est CASSE avec Docker 29 (`KeyError: 'ContainerConfig'`)
# et supprime le conteneur AVANT d echouer. Ne pas l employer ici.
#
# ⚠️ Les variables d environnement — dont `KICAD_SERVICE_TOKEN` — sont relues du
# conteneur EXISTANT et ecrites dans un fichier a 600. Elles ne transitent
# jamais par une ligne de commande ni par la sortie standard.
#
# Usage : bash services/kicad/scripts/recreer_kicad.sh
set -euo pipefail

NOM=cirqix-kicad
ANCIEN="${NOM}-ancien"
IMAGE="${NOM}:latest"
ENVF=/tmp/kicad.env
R=/mnt/c/Users/Mechegui/Desktop/dev/cirqix/services/kicad

demarrer() {
  docker run -d --name "$1" --restart unless-stopped --env-file "$ENVF" \
    -p 127.0.0.1:8766:8766 --network kicad_default --network-alias kicad \
    -v kicad_kicad-jobs:/tmp/kicad-jobs \
    -v "$R/main.py:/app/main.py:ro" \
    -v "$R/routers:/app/routers:ro" \
    -v "$R/tools:/app/tools:ro" \
    -v "$R/security.py:/app/security.py:ro" \
    -v "$R/observability.py:/app/observability.py:ro" \
    "$IMAGE" >/dev/null
}

sain() {
  for _ in $(seq 1 40); do
    if [ "$(curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8766/health || true)" = "200" ]; then
      return 0
    fi
    sleep 5
  done
  return 1
}

if docker inspect "$NOM" >/dev/null 2>&1; then
  docker inspect "$NOM" --format '{{range .Config.Env}}{{println .}}{{end}}' \
    | grep -v '^$' > "$ENVF"
  chmod 600 "$ENVF"
  echo "environnement preserve : $(wc -l < "$ENVF") variables"
  docker rm -f "$ANCIEN" >/dev/null 2>&1 || true
  # RENOMME, pas supprime : c est le filet.
  docker stop "$NOM" >/dev/null
  docker rename "$NOM" "$ANCIEN"
elif [ ! -s "$ENVF" ]; then
  echo "aucun conteneur et aucun $ENVF : impossible de recreer sans l environnement" >&2
  exit 1
fi

if demarrer "$NOM" && sain; then
  docker rm -f "$ANCIEN" >/dev/null 2>&1 || true
  echo "conteneur recree et sain"
  exit 0
fi

echo "le nouveau conteneur ne repond pas — retour a l ancien" >&2
docker rm -f "$NOM" >/dev/null 2>&1 || true
if docker inspect "$ANCIEN" >/dev/null 2>&1; then
  docker rename "$ANCIEN" "$NOM"
  docker start "$NOM" >/dev/null
  sain && echo "ancien conteneur remis en service" || echo "ancien conteneur NON sain" >&2
fi
exit 1
