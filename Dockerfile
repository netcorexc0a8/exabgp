FROM python:3.12-slim

ARG EXABGP_VERSION=5.0.3

RUN pip install --no-cache-dir "exabgp==${EXABGP_VERSION}" \
    && useradd --system --uid 10001 --create-home exabgp \
    && mkdir -p /var/lib/exabgp \
    && chown -R exabgp:exabgp /var/lib/exabgp

COPY fetcher/fetcher.py /opt/fetcher/fetcher.py

RUN chown -R exabgp:exabgp /opt/fetcher

# Pre-create the run directory and named FIFO pipes (exabgp.in, exabgp.out)
# required by ExaBGP's CLI control socket. Without these, ExaBGP logs a
# "could not find the named pipes" warning on every start.
RUN mkdir -p /opt/fetcher/run \
    && mkfifo /opt/fetcher/run/exabgp.in /opt/fetcher/run/exabgp.out \
    && chmod 600 /opt/fetcher/run/exabgp.in /opt/fetcher/run/exabgp.out \
    && chown -R exabgp:exabgp /opt/fetcher/run

USER exabgp

WORKDIR /opt/fetcher