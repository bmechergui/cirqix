# Worker de pipeline PCB.
#
# Image autonome, PAS de montage du dépôt : les `node_modules` installés sous
# Windows ne se résolvent pas dans un conteneur Linux (binaires natifs par
# plateforme, liens pnpm). Tenter de les partager échoue au premier binaire —
# mesuré sur esbuild.
#
# Le contexte de build est la RACINE du dépôt : le worker consomme des paquets
# du workspace (`@cirqix/agents`, `@cirqix/logger`, `@cirqix/types`) et le
# lockfile vit à la racine.
FROM node:20-alpine

RUN corepack enable

WORKDIR /repo

# Manifestes d'abord : la couche d'installation ne se réinvalide que si les
# dépendances changent, pas à chaque édition de source.
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml turbo.json ./
COPY packages/agents/package.json      packages/agents/
COPY packages/logger/package.json      packages/logger/
COPY packages/types/package.json       packages/types/
COPY packages/db/package.json          packages/db/
COPY packages/utils/package.json       packages/utils/
COPY packages/ui/package.json          packages/ui/
COPY packages/config-typescript/package.json packages/config-typescript/
COPY packages/config-eslint/package.json     packages/config-eslint/
COPY apps/web/package.json             apps/web/
COPY services/worker/package.json      services/worker/

# `--no-frozen-lockfile` est requis, pas une facilite : le lockfile est genere
# sous Windows et ne reference que le binaire esbuild win32. Sur linux/amd64,
# pnpm doit resoudre `@esbuild/linux-x64`, que le mode gele lui interdit
# d'ajouter — l'installation reussit alors mais le binaire manque, et le build
# echoue plus loin avec un MODULE_NOT_FOUND trompeur.
# Les VERSIONS restent pinnees par le lockfile ; seuls les binaires
# specifiques a la plateforme sont resolus ici.
RUN pnpm install --no-frozen-lockfile --filter @cirqix/worker...

# Sources des seuls paquets dont le worker a besoin.
COPY packages/ packages/
COPY services/worker/ services/worker/

RUN pnpm --filter @cirqix/worker build

WORKDIR /repo/services/worker

# Le worker ne publie aucun port : il consomme Redis et écrit dans Postgres.
# Le navigateur ne lui parle jamais.
CMD ["node", "dist/worker.cjs"]
