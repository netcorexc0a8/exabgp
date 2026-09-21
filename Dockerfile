FROM python:3.12-slim

ARG EXABGP_VERSION=5.0.3

RUN pip install --no-cache-dir "exabgp==${EXABGP_VERSION}" \
    && useradd --system --uid 10001 --create-home exabgp \
    && mkdir -p /var/lib/exabgp \
    && chown -R exabgp:exabgp /var/lib/exabgp

# Pre-create the named FIFO pipes (exabgp.in, exabgp.out) required by
# ExaBGP's CLI control socket. ExaBGP's named_pipe() lookup only scans a
# fixed list of absolute paths (/run/exabgp/, /run/<uid>/, /run/, and the
# /var/run and $PREFIX equivalents) - it does NOT check the cwd-relative
# "run/" path shown in its own log hint, so the pipes must live here.
RUN mkdir -p /run/exabgp \
    && mkfifo /run/exabgp/exabgp.in /run/exabgp/exabgp.out \
    && chmod 600 /run/exabgp/exabgp.in /run/exabgp/exabgp.out \
    && chown -R exabgp:exabgp /run/exabgp

COPY fetcher/fetcher.py /opt/fetcher/fetcher.py

RUN chown -R exabgp:exabgp /opt/fetcher

USER exabgp

WORKDIR /opt/fetcher