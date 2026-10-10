# Building and maintaining the Docker image

The default image includes Manim, minimal TeX Live, and JupyterLab. Image
variants are a separate change.

## Local checks

From the repository root:

```sh
docker buildx build --load -t manim-local -f docker/Dockerfile .
docker run --rm --network none \
  --mount "type=bind,source=$PWD/docker/test_runtime.py,target=/tmp/test_runtime.py,readonly" \
  manim-local python /tmp/test_runtime.py
python -m unittest discover -s docker -p test_release.py
```

`test_runtime.py` runs as the default non-root user and tests the installed
package, not the checkout. It renders Cairo text/TeX, XeLaTeX/XDV, and headless
OpenGL; decodes video/audio output; and starts Jupyter on loopback. It needs no
external network. Publication unit tests require only Python 3.11+.

The `release.py main` and `release.py release` commands **publish images**;
do not run them as local checks.

## Dependencies

- Python and uv image references are digest-pinned. Dependabot proposes one
  grouped update each month, checked by the native Docker builds.
- Python installation uses `uv.lock`, without development dependencies or an
  editable checkout. Source changes reuse the dependency installation layer.
- TeX has a separate cached stage. `texlive-profile.txt` and
  `texlive-packages.txt` preserve the existing minimal package set.
- `install-texlive.sh` uses the HTTPS **TeX Live 2025 final archive** for the
  installer, installation, and subsequent `tlmgr` operations. It does not use
  mirror discovery. Downloads have bounded retries and the complete install
  has a 20-minute limit. TLS verification stays enabled.

There is no separately maintained installer checksum: the archived installer
is fetched over verified HTTPS, and TeX Live checks package integrity itself.
To upgrade TeX, change the repository in `install-texlive.sh` to a matching
archive and test both architectures. Newer dated snapshots on texlive.info
were rejected because normal clients could receive bot-challenge pages.

These choices improve repeatability, not byte-identical cold builds: Debian
repositories and isolated Python build dependencies can still change.

## Publication

1. Main and Docker-related PRs build on native AMD64/ARM64 runners, with
   architecture-specific BuildKit caches. Each image is loaded and tested
   before pushing. PRs and forks never receive Docker Hub credentials.
2. Upstream main combines the tested architecture digests, verifies both
   platforms and source/version labels, then records the index under
   `sha-<commit>`. **This workflow never overwrites a commit tag.** A rerun
   reuses its first successful image. `latest` changes only if that commit is
   still main's head.
3. Releases check out the immutable event commit, resolve its commit tag to
   a digest, verify it, and copy that digest to `vX.Y.Z`. Existing version
   tags are verified and reused, never replaced. `stable` changes only for
   GitHub's latest release; releases do not change `latest`.

Publication jobs use GitHub's [concurrency queue](https://docs.github.com/en/actions/how-tos/write-workflows/choose-when-workflows-run/control-workflow-concurrency)
to serialize mutable-tag updates without dropping pending version publications. There is no workflow
history crawler, promotion-file schema, or expiring release-proof artifact.
The registry's commit tag is the candidate record; publication credentials
must remain restricted to this workflow/trusted maintainers. Docker Hub can
also enforce immutability for commit/version tags while leaving `latest` and
`stable` mutable; the write-once rule in this workflow does not restrict an
administrator writing directly to the registry.

Keep `sha-*` tags while their commits may be released. `build-*` tags are
intermediate build references. Registry cleanup must preserve manifests and
layers referenced by commit/version tags.

If a release arrives during its main build, publication waits up to 30 minutes.
If no candidate appears, fix/rerun that commit's main build, then rerun release
publication. It never falls back to rebuilding or to the current `latest`.
A failed `latest` update does not invalidate the recorded commit image.

## Extending TeX

System package installation needs root; use a derived image for persistent
changes rather than modifying a throwaway container:

```dockerfile
FROM manimcommunity/manim:stable
USER root
RUN tlmgr install ctex
USER manimuser
```

New images include Perl, curl, and xz for `tlmgr`. Older tags may need these
installed first. Package additions use the image's configured TeX repository;
changing to a different TeX Live year requires rebuilding its installation.
