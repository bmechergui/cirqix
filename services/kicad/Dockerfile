# ============================================================
# Layrix KiCad Service — Docker headless
# Base : KiCad 8.0 + Python 3.11 + FastAPI + Freerouting
# ============================================================

FROM ubuntu:22.04 AS base

# Prevent interactive prompts during apt
ENV DEBIAN_FRONTEND=noninteractive

# System dependencies + KiCad 8.0 via official PPA
#
# We deliberately AVOID `add-apt-repository ppa:kicad/...` here because it
# depends on the Launchpad REST API (api.launchpad.net) which is flaky and
# regularly times out (HTTP 504), failing the CI build. Instead we add the
# PPA repository line manually and import the signing key directly from a
# keyserver — both steps wrapped in retry loops so transient outages of the
# Ubuntu archive, the Launchpad CDN, or keyserver.ubuntu.com don't kill the
# build. KiCad PPA signing key fingerprint:
#   FDA854F61C4D0D9572BB95E5245D5502FAD7A805
ENV KICAD_PPA_KEY=FDA854F61C4D0D9572BB95E5245D5502FAD7A805

RUN apt-get update && apt-get install -y --no-install-recommends \
        gnupg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    # Add the KiCad 8.0 PPA repository line directly
    && echo "deb https://ppa.launchpadcontent.net/kicad/kicad-8.0-releases/ubuntu jammy main" \
        > /etc/apt/sources.list.d/kicad-kicad-8_0-releases.list \
    # Import the PPA signing key via HTTP + --dearmor (no dirmngr needed).
    # curl downloads the ASCII-armored public key; gpg --dearmor converts it
    # to binary format required by modern apt (trusted.gpg.d/*.gpg).
    && mkdir -p /root/.gnupg && chmod 700 /root/.gnupg \
    && for i in 1 2 3; do \
           curl -fsSL \
               "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${KICAD_PPA_KEY}" \
           | gpg --dearmor \
           | tee /etc/apt/trusted.gpg.d/kicad.gpg > /dev/null \
           && break || sleep 10; \
       done \
    && chmod 644 /etc/apt/trusted.gpg.d/kicad.gpg \
    # Now install KiCad — retry up to 3 times on archive CDN flakes
    && apt-get update \
    && for i in 1 2 3; do \
           apt-get install -y --no-install-recommends --fix-missing \
               kicad \
               kicad-footprints \
               python3-pip \
               python3-dev \
               openjdk-17-jre-headless \
               zip \
               unzip \
           && break || sleep 30; \
       done \
    && rm -rf /var/lib/apt/lists/*

# Copier les requirements et installer Python deps
WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Télécharger Freerouting JAR
RUN mkdir -p /opt/freerouting && \
    curl -L https://github.com/freerouting/freerouting/releases/latest/download/freerouting.jar \
    -o /opt/freerouting/freerouting.jar

# Copier le code source
COPY . .

# Créer le répertoire de travail temporaire
RUN mkdir -p /tmp/kicad-jobs

# Variables d'environnement
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "4"]
