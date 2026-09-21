FROM python:3.12-slim

ARG EXABGP_VERSION=5.0.3

RUN pip install --no-cache-dir "exabgp==${EXABGP_VERSION}" \
    && useradd --system --uid 10001 --create-home exabgp \
    && mkdir -p /var/lib/exabgp \
    && chown -R exabgp:exabgp /var/lib/exabgp

COPY fetcher/fetcher.py /opt/fetcher/fetcher.py

RUN chown -R exabgp:exabgp /opt/fetcher

USER exabgp

WORKDIR /opt/fetcher