FROM python:3.12-slim

ARG EXABGP_VERSION=5.0.3

RUN pip install --no-cache-dir "exabgp==${EXABGP_VERSION}" \
    && useradd --system --uid 10001 --create-home exabgp \
    && mkdir -p /var/lib/exabgp \
    && chown -R exabgp:exabgp /var/lib/exabgp \
    && mkdir -p /opt/fetcher/run \
    && mkfifo /opt/fetcher/run/exabgp.in \
    && mkfifo /opt/fetcher/run/exabgp.out \
    && chown -R exabgp:exabgp /opt/fetcher/run \
    && chmod 600 /opt/fetcher/run/exabgp.{in,out}

USER exabgp
WORKDIR /opt/fetcher