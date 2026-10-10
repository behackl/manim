#!/bin/sh
# The Dockerfile applies a 20-minute wall-clock limit to this entire script.
set -eu

profile=${1:?usage: install-texlive.sh PROFILE PACKAGES}
packages=${2:?usage: install-texlive.sh PROFILE PACKAGES}
test -r "$profile"
test -r "$packages"

# Use the same frozen repository for the installer and installed packages.
repository=https://ftp.math.utah.edu/pub/tex/historic/systems/texlive/2025/tlnet-final

workdir=$(mktemp -d)
trap 'rm -rf "$workdir"' 0
trap 'exit 1' HUP INT TERM

curl --fail --location --silent --show-error \
    --proto '=https' --proto-redir '=https' \
    --connect-timeout 15 --max-time 300 \
    --retry 3 --retry-delay 2 --retry-max-time 600 \
    --output "$workdir/install-tl-unx.tar.gz" \
    "$repository/install-tl-unx.tar.gz"
mkdir "$workdir/installer"
tar -xzf "$workdir/install-tl-unx.tar.gz" \
    -C "$workdir/installer" --strip-components=1

# Detect the installed platform rather than maintaining architecture PATH lists.
platform=$(perl "$workdir/installer/install-tl" --print-platform)
perl "$workdir/installer/install-tl" \
    --repository "$repository" --profile "$profile" \
    --no-interaction --no-continue --no-doc-install --no-src-install \
    --no-persistent-downloads

test -d "/usr/local/texlive/bin/$platform"
ln -s "$platform" /usr/local/texlive/bin/current
export PATH="/usr/local/texlive/bin/current:$PATH"

# Persist the frozen repository and no-doc/src policy for root extensions too.
tlmgr --repository "$repository" option repository "$repository"
tlmgr --repository "$repository" option docfiles 0
tlmgr --repository "$repository" option srcfiles 0

# One trusted package name per line, with blank lines and # comments allowed.
set --
while IFS= read -r package || [ -n "$package" ]; do
    case "$package" in
        ''|\#*) continue ;;
    esac
    set -- "$@" "$package"
done < "$packages"
test "$#" -gt 0
tlmgr --repository "$repository" install "$@"
