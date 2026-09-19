# Déploiement de production — proposition (en attente de décision)

> Statut : **proposition**, rien n'est appliqué. Décision `D-2026-09-19-b` dans
> `docs/DECISIONS.md`, **en attente**. Les coûts sont des ORDRES DE GRANDEUR à
> vérifier chez chaque fournisseur, jamais des mesures. Rédigé le 2026-09-19.

## Contraintes mesurées (2026-09-19)

| Élément | Fait |
|---|---|
| Vercel | non lié (ni `.vercel/` ni `vercel.json`) ; Supabase est déjà un projet cloud (RLS, Realtime prouvé) |
| Appels directs web → service | `GET /api/projects/[id]/render` (1-4 s) et `/model` (1-6 s), `maxDuration = 120` ; `/api/agent` (SSE synchrone, `maxDuration = 300`) |
| Appels directs web → **Redis** | `/api/agent` **enfile lui-même** le job BullMQ (`createPipelineQueue(REDIS_URL)`, `route.ts` l. 201 et 239) : l'app web doit joindre Redis **en plus** du service |
| Service KiCad | image 7,3 Go + volume de modèles 3D ~1,3 Go ; 3,7 Go de RAM au repos ; JVM Freerouting 0,4 → 2,4-2,5 Go en quelques heures ; ~0,2 Go par routage ; Xvfb ; 4 workers uvicorn ; routages sérialisés par un verrou |
| Worker | image 1,2 Go, sans plafond de durée (runs de 3 à 45 min), écrit dans Supabase avec la clé service-role |
| Sécurité | jeton Bearer de 48 caractères, fail-closed, pas de CORS ; HTTPS obligatoire hors localhost ; **Redis sans mot de passe** |
| Dépendance hors réseau | en production, le schéma vient de l'API Anthropic (Haiku) : `CIRQIX_SCHEMA_PROVIDER=claude-code` n'existe que sur l'hôte de dev |

**Dimensionnement estimé (les trois options)** : 3,7 Go au repos + ~2 Go de dérive de
la JVM + pics de routage, pcbnew et worker → **16 Go de RAM**, 4 à 8 vCPU, 80 Go de
disque ou plus. 8 Go ne suffit pas : la dérive de la JVM mène à l'OOM killer. L'option 3
ajoute ~1 Go pour Next.js.

## Option 1 — VPS exposé derrière un reverse proxy, Vercel en façade

    navigateur ─▶ Vercel (Next.js) ──HTTPS + Bearer──▶ Caddy/Nginx :443 (VPS) ─▶ kicad:8766
                        │                                   (TLS, limitation de débit)
                        └──rediss:// + mot de passe──▶ Redis (VPS publié en TLS, OU Redis managé)
                                                        ▲
                                              worker (VPS) ── Supabase cloud

- **Exposition** : le service a une IP publique ; le jeton est la seule barrière, avec la
  limitation de débit du proxy. Liste d'IP peu utile (sorties Vercel dynamiques ; IP fixes
  sur offres payantes, à vérifier). Redis doit sortir de la boucle locale : TLS +
  `requirepass`, ou Redis managé à prix FIXE (pas à la commande — BullMQ interroge en boucle).
- **Coût estimé** : VPS 16 Go 20-40 €/mois (Hetzner, OVH…) ou 80-130 $/mois (DigitalOcean,
  Lightsail…) ; Vercel Pro ~20 $/membre/mois (Hobby interdit l'usage commercial) ;
  Redis managé éventuel 0-15 $/mois.
- **Latence ajoutée** : une traversée Internet, ~10-40 ms dans la même région —
  négligeable devant 1-6 s de rendu. Corps base64 de plusieurs Mo à prévoir.
- **Travail** : proxy (TLS, taille de corps, délais > 120 s, limitation de débit) ; Redis
  TLS + mot de passe ; `docker-compose.prod.yml` (sans montages à chaud, limites mémoire) ;
  DNS ; variables Vercel ; jeton tourné.
- **Risques** : surface publique qui exécute du calcul lourd sur des fichiers fournis
  (déni de service si le jeton fuit) ; Redis public ; VPS point unique de défaillance.

## Option 2 — même VPS, aucun port entrant : Cloudflare Tunnel + Access

    navigateur ─▶ Vercel ──HTTPS + CF-Access-Client-Id/Secret + Bearer──▶ Cloudflare (Access, WAF)
                                                                            │ tunnel sortant
                                                            cloudflared (VPS) ─▶ kicad:8766
    Vercel ──rediss://──▶ Redis MANAGÉ ◀── worker (VPS)         (aucun port ouvert sur le VPS)

- **Faisabilité depuis Vercel** : Cloudflare Tunnel + jeton de service Access — **faisable**
  (un `fetch` HTTPS avec deux en-têtes de plus) ; le service est alors public CHEZ
  Cloudflare, origine masquée, second facteur avant le Bearer. Tailscale / WireGuard —
  **peu réaliste** en serverless (pas de démon persistant), écarté. **Redis** : un tunnel
  HTTP ne transporte pas le protocole Redis → Redis managé obligatoire, ou un endpoint
  d'enfilage HTTP sur le VPS (changement de code, contraire à « worker sans surface réseau »).
- **Coût estimé** : option 1 + Cloudflare Tunnel/Access (gratuits en petit volume, à vérifier)
  + Redis managé à prix fixe (~10-30 $/mois).
- **Latence ajoutée** : ~10-50 ms. Délai maximal de réponse du proxy Cloudflare ~100 s par
  défaut (à vérifier) : render/model tiennent ; le SSE synchrone de `/api/agent` serait
  fragile → garder `CIRQIX_ASYNC_PIPELINE=1`.
- **Travail** : conteneur `cloudflared` ; application Access + jeton de service ; en-têtes CF
  dans les routes et clients qui appellent le service ; `REDIS_URL` vers Redis managé.
- **Risques** : dépendance à Cloudflare ; deux secrets de plus ; limite de taille de corps
  Cloudflare à vérifier ; VPS point unique de défaillance.

## Option 3 — tout sur le VPS, Next.js compris (pas de Vercel)

    navigateur ─▶ Caddy :443 (TLS auto) ─▶ web (Next.js standalone) ─▶ kicad:8766 (réseau Docker interne)
                                                                   └──▶ redis:6379  (interne, jamais publié)
                                                     worker ────────▶ kicad, redis, Supabase cloud

- **Exposition** : seul le port 443 est ouvert. Service KiCad et Redis restent internes,
  comme en dev ; `KICAD_SERVICE_TOKEN` ne quitte jamais la machine. Cloudflare en proxy
  DNS possible (anti-DDoS gratuit).
- **Coût estimé** : un VPS 16 Go (32 Go pour la marge) : 25-60 €/mois (Hetzner/OVH) ou
  100-190 $/mois (DigitalOcean). Ni Vercel ni Redis managé.
- **Latence ajoutée** : ~0. Plus aucun `maxDuration` : le plafond de 300 s disparaît.
- **Travail** : `output: 'standalone'` + Dockerfile pour `apps/web` ; `docker-compose.prod.yml`
  (4 services + Caddy, `mem_limit`/`cpus` pour que le routage n'affame pas le web) ; CI de
  build/déploiement ; sauvegarde du volume Redis ; supervision ; URLs de redirection OAuth
  Supabase et webhook Lemon Squeezy sur le nouveau domaine.
- **Risques** : calcul lourd sur la même machine que le site (atténué par les cgroups) ; ni
  CDN ni préversions ; déploiement entièrement à notre charge. Point unique de défaillance
  identique aux options 1 et 2 (le service KiCad n'est redondé dans aucune).

## Comparaison

| | Option 1 (proxy) | Option 2 (tunnel) | Option 3 (tout VPS) |
|---|---|---|---|
| Service joignable depuis Internet | oui (jeton seul) | via Cloudflare seulement (Access + jeton) | non |
| Redis | à exposer ou externaliser | Redis managé obligatoire | interne |
| Coût mensuel estimé | ~40-150 | ~50-180 | ~25-190 selon le fournisseur |
| Pièces mobiles | VPS + Vercel (+ Redis) | VPS + Vercel + Cloudflare + Redis managé | VPS seul |
| Code à modifier | configuration seule | en-têtes CF dans les clients | Dockerfile web, config Next |

## Recommandation (proposée, non décidée)

**Option 3 pour le lancement, option 2 comme trajectoire d'évolution.**
1. Le service KiCad est un point unique de défaillance dans les trois options : Vercel
   n'apporte pas de redondance là où elle compterait.
2. Seule option où ni le service ni Redis n'ont de surface Internet — le raisonnement déjà
   écrit dans `docker-compose.yml`, sans nouveau secret ni fournisseur.
3. Elle supprime à la fois « Vercel doit joindre Redis » et les plafonds `maxDuration`, qui
   ont déjà coûté quatre frontières de délai à ce dépôt.
4. Coût le plus bas, et configuration la plus proche de celle prouvée en dev.

Bascule vers l'option 2 le jour où le trafic justifie un CDN ou des préversions ; le
tunnel se greffe sans rien défaire.

## Décision à prendre par l'utilisateur

1. **Hébergement du web** : (a) Vercel — options 1 ou 2 ; (b) sur le VPS — option 3.
2. **Si Vercel** : (a) service exposé derrière un proxy, jeton seul ; (b) Cloudflare Tunnel
   + Access, avec un Redis managé à prix fixe.
3. **Fournisseur et taille du VPS** : (a) Hetzner/OVH 16 Go (le moins cher, UE) ;
   (b) DigitalOcean 16 Go (déjà évoqué dans `CLAUDE.md`) ; (c) 32 Go pour absorber la
   dérive de la JVM et un second routage.
