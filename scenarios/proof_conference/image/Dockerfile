# Scenario image for proof_conference: Lean 4, Mathlib and a pinned Formal Conjectures checkout,
# ready to compile problem files offline as an ordinary user on a read-only root filesystem.
# Built on swarmbench's base image (build context: this folder). Two stages: everything is
# downloaded and built in the first, and the final image copies only the finished toolchain and
# project, so files deleted while building do not linger in lower layers. The build stage starts
# from the same pinned Debian/Python image as swarmbench's base rather than the base itself, so
# its slow downloads (about 6 GB) stay cached when the base image changes.
ARG BASE_IMAGE
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258 AS build

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl git \
    && apt-get clean && find /var/lib/apt/lists -type f -delete

# Formal Conjectures at the last commit before `answer(sorry)` was removed from its problem files
# (2026-10-13). Its lean-toolchain pins Lean v4.33.1 and Mathlib v4.33.1.
ARG FC_COMMIT=e47a327f7befa3df97115abf87aa8ed35c381f1f
ARG LEAN_TOOLCHAIN=leanprover/lean4:v4.33.1
ARG ELAN_VERSION=v4.2.4

ENV ELAN_HOME=/usr/local/elan

# elan installs the toolchain; lean and lake are then linked straight to the toolchain's binaries,
# so nothing at run time goes through elan (which would want a writable ~/.elan).
RUN curl -sSfL "https://raw.githubusercontent.com/leanprover/elan/${ELAN_VERSION}/elan-init.sh" -o /tmp/elan-init.sh \
    && sh /tmp/elan-init.sh -y --no-modify-path --default-toolchain "${LEAN_TOOLCHAIN}" \
    && rm -f /tmp/elan-init.sh \
    && "$ELAN_HOME/bin/elan" toolchain install "${LEAN_TOOLCHAIN}"
RUN bin="$ELAN_HOME/toolchains/$(echo "${LEAN_TOOLCHAIN}" | sed 's|/|--|; s|:|---|')/bin" \
    && test -x "$bin/lean" && test -x "$bin/lake" \
    && for b in lean lake leanc; do ln -sf "$bin/$b" /usr/local/bin/$b; done \
    && lean --version && lake --version

# Formal Conjectures with Mathlib's prebuilt cache (the downloaded archives are not kept).
RUN git clone --quiet https://github.com/google-deepmind/formal-conjectures.git /srv/fc \
    && cd /srv/fc && git checkout --quiet "${FC_COMMIT}" \
    && test "$(cat lean-toolchain)" = "${LEAN_TOOLCHAIN}" \
    && export XDG_CACHE_HOME=/tmp/xdg-cache HOME=/tmp/build-home \
    && lake exe cache get \
    && rm -rf /tmp/xdg-cache /tmp/build-home

# FC's own libraries. FormalConjecturesUtil (all of Mathlib plus FC's helper definitions,
# attributes and linters) is all a problem file imports. FC's problem files are then removed: the
# conference serves its own copies, and FC's proofs of solved statements should not be lying
# around to copy. .ilean files (editor indexes) and the git history go too.
RUN cd /srv/fc \
    && export HOME=/tmp/build-home \
    && lake build FormalConjecturesUtil \
    && lake env true \
    && rm -rf /tmp/build-home .git FormalConjectures FormalConjectures.lean \
    && find /srv/fc -name '*.ilean' -delete \
    && echo "${FC_COMMIT}" > /srv/fc/FC_COMMIT \
    && chmod -R a+rX,go-w /srv/fc

# Not needed to elaborate files: the C code Lake generated for each module and the toolchain's
# static libraries (both only matter for compiling native executables). Packages keep their .git:
# Lake re-clones a dependency whose .git is missing.
RUN find /srv/fc/.lake -name '*.c' -delete \
    && find "$ELAN_HOME/toolchains" -name '*.a' -delete

FROM ${BASE_IMAGE}
ARG LEAN_TOOLCHAIN=leanprover/lean4:v4.33.1
ENV ELAN_HOME=/usr/local/elan
COPY --from=build /usr/local/elan /usr/local/elan
COPY --from=build /srv/fc /srv/fc
RUN bin="$ELAN_HOME/toolchains/$(echo "${LEAN_TOOLCHAIN}" | sed 's|/|--|; s|:|---|')/bin" \
    && for b in lean lake leanc; do ln -sf "$bin/$b" /usr/local/bin/$b; done \
    && lean --version
COPY lean-check /usr/local/bin/lean-check
RUN chmod 755 /usr/local/bin/lean-check
