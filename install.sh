#!/bin/sh
# Bootstraps a MagicBoxie device on a fresh Raspberry Pi. Since the Pi has no
# other easy way to get files onto it and isn't online most of the time,
# this is meant to be curled and run once, while it does have internet
# (e.g. over SSH on the home WiFi during initial setup):
#
#   curl -fsSL https://d.magicboxie.com | sh
#
# It just clones/updates the repo and hands off to `make pi-install`, which
# does the real work (system packages, venv, systemd service) - see the
# "Raspberry Pi (native, no Docker)" section of the Makefile.
set -eu

REPO_URL="https://github.com/kriogenx0/magicboxie-device.git"
REPO_REF="${MAGICBOXIE_REF:-main}"
INSTALL_DIR="${MAGICBOXIE_INSTALL_DIR:-$HOME/magicboxie-device}"

if ! command -v git >/dev/null 2>&1; then
    echo "git not found - installing..."
    sudo apt-get update
    sudo apt-get install -y --no-install-recommends git
fi

if [ -d "$INSTALL_DIR/.git" ]; then
    echo "Found existing checkout at $INSTALL_DIR - updating..."
    git -C "$INSTALL_DIR" fetch --depth 1 origin "$REPO_REF"
    git -C "$INSTALL_DIR" checkout "$REPO_REF"
    git -C "$INSTALL_DIR" reset --hard "origin/$REPO_REF"
else
    echo "Cloning $REPO_URL (ref $REPO_REF) into $INSTALL_DIR..."
    git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$INSTALL_DIR"
fi

cd "$INSTALL_DIR"
make pi-install
