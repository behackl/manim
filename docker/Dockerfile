# syntax=docker/dockerfile:1

# Dependabot updates these image references together in monthly PRs.
FROM python:3.14-slim-trixie@sha256:a2b82f3c48559aa0a8446d9af49826b6e2b2016f4cd2afabfe6013ec53729170 AS python-base

# Shared by install-tl and tlmgr. TLUtils appends destination and URL, so
# --output must be last. HTTPS and timeouts apply to package downloads too.
ENV TL_DOWNLOAD_PROGRAM=/usr/bin/curl \
    TL_DOWNLOAD_ARGS="--fail --location --silent --show-error --proto =https --proto-redir =https --connect-timeout 15 --max-time 300 --retry 3 --retry-delay 2 --retry-max-time 600 --output"

# uv is mounted only during the Python build.
FROM ghcr.io/astral-sh/uv:0.12.1@sha256:cf4eedcaa81655197f625739489effcbe71b61ceb1506f332c3facae5deceded AS uv

# TeX installation is cached independently of Manim's source.
FROM python-base AS texlive

RUN apt-get update -qq \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        coreutils \
        curl \
        libfontconfig1 \
        libstdc++6 \
        perl \
        xz-utils \
    && rm -rf /var/lib/apt/lists/*

COPY docker/texlive-profile.txt docker/texlive-packages.txt docker/install-texlive.sh /tmp/texlive/
# Bound the whole download/install/tlmgr operation, not just individual requests.
RUN timeout --signal=TERM --kill-after=30s 20m \
        sh /tmp/texlive/install-texlive.sh \
        /tmp/texlive/texlive-profile.txt /tmp/texlive/texlive-packages.txt \
    && rm -rf /tmp/texlive

# Python build dependencies and locked installation.
FROM python-base AS builder

RUN apt-get update -qq \
    && apt-get install --no-install-recommends -y \
        build-essential \
        cmake \
        pkg-config \
        libcairo2-dev \
        libffi-dev \
        libpango1.0-dev \
        libegl-dev \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/opt/venv \
    UV_PYTHON=/usr/local/bin/python \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy
WORKDIR /opt/manim

# Reuse the locked production dependencies when only Manim's source changes.
COPY pyproject.toml uv.lock ./
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra jupyterlab --no-editable --no-install-project

# Only the package and its build metadata are needed for the non-editable wheel.
COPY README.md LICENSE LICENSE.community ./
COPY manim/ ./manim/
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --extra jupyterlab --no-editable

# Runtime: no compiler toolchain, uv, or source checkout.
FROM python-base AS runtime

# PyAV bundles FFmpeg libraries: do not install the FFmpeg CLI.
# Keep EGL/GL for headless rendering, Ghostscript for dvisvgm, and Noto core fonts.
# Perl, curl, and xz allow root to extend the TeX installation with tlmgr.
RUN apt-get update -qq \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        curl \
        perl \
        xz-utils \
        libcairo2 \
        libpango-1.0-0 \
        libpangocairo-1.0-0 \
        libpangoft2-1.0-0 \
        libffi8 \
        libegl1 \
        libgl1 \
        libstdc++6 \
        ghostscript \
        fonts-noto-core \
        fontconfig \
    && rm -rf /var/lib/apt/lists/* \
    && fc-cache -fv

COPY --from=texlive /usr/local/texlive /usr/local/texlive
COPY --from=builder /opt/venv /opt/venv
ENV VIRTUAL_ENV=/opt/venv \
    PATH=/opt/venv/bin:/usr/local/texlive/bin/current:$PATH

ARG NB_USER=manimuser
ARG NB_UID=1000
ENV USER=${NB_USER} \
    NB_UID=${NB_UID} \
    HOME=/manim

RUN adduser --disabled-password \
    --gecos "Default user" \
    --uid ${NB_UID} \
    ${NB_USER}

WORKDIR ${HOME}
RUN chown -R ${NB_USER}:${NB_USER} ${HOME} && chmod 777 ${HOME}
USER ${NB_USER}

CMD ["/bin/bash"]
