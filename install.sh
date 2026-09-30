#!/bin/bash
#
# install.sh — install ExaBGP from GitHub releases
#
# Usage:
#   curl -fsSL https://github.com/OWNER/REPO/releases/latest/download/install.sh | sudo sh
#   curl -fsSLO https://github.com/OWNER/REPO/releases/latest/download/install.sh && sudo sh install.sh v5.0.3
#
# If no version is given, the script resolves the latest release tag
# from the repository. Pass a specific version to install that release.
#
# Requirements: curl, tar, root/sudo

set -euo pipefail

REPO="netcorexc0a8/exabgp"
VERSION="${1:-latest}"

# Detect architecture
case "$(uname -m)" in
    x86_64|amd64)   ARCH="amd64" ;;
    aarch64|arm64)  ARCH="arm64" ;;
    i386|i486|i586|i686|x86) ARCH="386" ;;
    *)
        echo "ERROR: unsupported architecture $(uname -m)" >&2
        exit 1
        ;;
esac

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
URL="https://github.com/${REPO}/releases/download/${TAG}/exabgp_${VERSION}_linux_${ARCH}.tar.gz"

echo "Downloading ExaBGP ${TAG} (${ARCH}) from ${URL}"

TMPDIR=$(mktemp -d)
trap 'rm -rf "${TMPDIR}"' EXIT

if ! curl -fL "${URL}" -o "${TMPDIR}/exabgp.tar.gz"; then
    echo "ERROR: download failed for tag ${TAG} on ${ARCH}" >&2
    echo "Check available releases: https://github.com/${REPO}/releases" >&2
    exit 1
fi

tar -xzf "${TMPDIR}/exabgp.tar.gz" -C "${TMPDIR}"

# Install
cp "${TMPDIR}/exabgp" /usr/local/bin/exabgp
chmod +x /usr/local/bin/exabgp

echo "ExaBGP ${TAG} (${ARCH}) installed to /usr/local/bin/exabgp"
exabgp --version