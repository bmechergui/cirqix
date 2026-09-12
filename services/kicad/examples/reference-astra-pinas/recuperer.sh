#!/usr/bin/env bash
# Recupere la carte de reference. Elle n'est PAS versionnee : voir README.md.
set -e
ici="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$ici/input"
url="https://raw.githubusercontent.com/jlcjak/astra_piNas/main/astra_piNas.kicad_pcb"
curl -sSL "$url" -o "$ici/input/astra_piNas.kicad_pcb"
printf 'recupere : %s octets\n' "$(stat -c %s "$ici/input/astra_piNas.kicad_pcb")"
