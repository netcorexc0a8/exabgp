#!/bin/bash
#
# install-exabgp.sh — install ExaBGP from GitHub releases
#
# Usage:
#   ./install-exabgp.sh              # install latest release
#   ./install-exabgp.sh 5.0.3       # install specific version
#   ./install-exabgp.sh latest       # same as no argument
#
# The script resolves the tag in the repository, so you can use it to
# always install the newest release. Run it again after a new tag is
# pushed to upgrade.
#
# Requirements: curl, tar, sudo/root

set -euo pipefail

REPO="exabgp/exabgp"
VERSION="${1:-latest}"

# Resolve to a concrete version/tag
if [ "$VERSION" = "latest" ]; then
    echo "Resolving latest ExaBGP release tag..."
    VERSION=$(curl -s "https://api.github.com/repos/${REPO}/releases/latest" \
        | grep -oP '"tag_name": "\K[^"]+')
    if [ -z "$VERSION" ]; then
        echo "ERROR: could not resolve latest tag" >&2
        exit 1
    fi
    echo "Latest tag: ${VERSION}"
fi

# Strip leading 'v' if present, then re-add it for the download URL
VERSION="${VERSION#v}"
TAG="v${VERSION}"
URL="https://github.com/${REPO}/releases/download/${TAG}/exabgp_${VERSION}_linux_amd64.tar.gz"

echo "Downloading ExaBGP ${TAG} from ${URL}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "${TMPDIR}"' EXIT

if ! curl -fL "${URL}" -o "${TMPDIR}/exabgp.tar.gz"; then
    echo "ERROR: download failed for tag ${TAG}" >&2
    echo "Check available tags: https://github.com/${REPO}/releases" >&2
    exit 1
fi

tar -xzf "${TMPDIR}/exabgp.tar.gz" -C "${TMPDIR}"

# Install
if [ "$(id -u)" -ne 0 ]; then
    sudo cp "${TMPDIR}/exabgp" /usr/local/bin/exabgp
    sudo chmod +x /usr/local/bin/exabgp
else
    cp "${TMPDIR}/exabgp" /usr/local/bin/exabgp
    chmod +x /usr/local/bin/exabgp
fi

echo "ExaBGP ${TAG} installed to /usr/local/bin/exabgp"
exabgp --version