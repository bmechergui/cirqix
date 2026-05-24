# ============================================================
# Layrix KiCad Service — Docker headless
# Base : KiCad 8.0 + Python 3.11 + FastAPI + Freerouting
# Port : 8766 (matches KICAD_SERVICE_URL in .env.local)
# ============================================================

FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive

# KiCad PPA signing key fingerprint
ENV KICAD_PPA_KEY=FDA854F61C4D0D9572BB95E5245D5502FAD7A805

RUN apt-get update && apt-get install -y --no-install-recommends \
        gnupg \
        curl \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && echo "deb https://ppa.launchpadcontent.net/kicad/kicad-8.0-releases/ubuntu jammy main" \
        > /etc/apt/sources.list.d/kicad-kicad-8_0-releases.list \
    && mkdir -p /root/.gnupg && chmod 700 /root/.gnupg \
    && for i in 1 2 3; do \
           curl -fsSL \
               "https://keyserver.ubuntu.com/pks/lookup?op=get&search=0x${KICAD_PPA_KEY}" \
           | gpg --dearmor \
           | tee /etc/apt/trusted.gpg.d/kicad.gpg > /dev/null \
           && break || sleep 10; \
       done \
    && chmod 644 /etc/apt/trusted.gpg.d/kicad.gpg \
    && apt-get update \
    && for i in 1 2 3; do \
           apt-get install -y --no-install-recommends --fix-missing \
               kicad \
               kicad-symbols \
               kicad-footprints \
               python3-pip \
               python3-dev \
               python3-pcbnew \
               xvfb \
               openjdk-17-jre-headless \
               zip \
               unzip \
           && break || sleep 30; \
       done \
    && rm -rf /var/lib/apt/lists/*

ENV KICAD_SYMBOL_DIR=/usr/share/kicad/symbols
ENV KICAD_FOOTPRINT_DIR=/usr/share/kicad/footprints
ENV PYTHONUNBUFFERED=1
ENV DISPLAY=:99

# Add KiCad system Python path so pcbnew is importable by pip-installed uvicorn
ENV PYTHONPATH=/usr/lib/python3/dist-packages:${PYTHONPATH}

WORKDIR /app
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Freerouting JAR
RUN mkdir -p /opt/freerouting && \
    for i in 1 2 3; do \
        curl -fL https://github.com/freerouting/freerouting/releases/latest/download/freerouting.jar \
            -o /opt/freerouting/freerouting.jar && break || sleep 15; \
    done

COPY . .

RUN mkdir -p /tmp/kicad-jobs

EXPOSE 8766

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8766/health || exit 1

# Start Xvfb (headless display for kicad-cli) then uvicorn on port 8766
CMD ["sh", "-c", "Xvfb :99 -screen 0 1024x768x24 -ac &\
     uvicorn main:app --host 0.0.0.0 --port 8766 --workers 4"]
