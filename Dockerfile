FROM debian:bookworm-slim

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl python3 python3-venv python3-pip gpg \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /arena

COPY requirements.txt ./
RUN python3 -m venv /opt/venv && pip install --no-cache-dir -r requirements.txt

COPY scripts/install-emulator.sh /tmp/install-emulator.sh
RUN bash /tmp/install-emulator.sh && rm /tmp/install-emulator.sh

COPY . .
RUN chmod +x scripts/install-emulator.sh scripts/run.sh

CMD ["bash", "scripts/run.sh"]
