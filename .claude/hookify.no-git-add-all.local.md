---
name: no-git-add-all
enabled: true
event: bash
pattern: "git add -A|git add \."
action: block
---

⛔ BLOQUÉ — `git add -A` et `git add .` sont interdits dans Cirqix.

TOUJOURS utiliser : `git add <fichiers spécifiques>`

Raison : éviter d'inclure accidentellement des fichiers sensibles (.env, secrets, binaires).
