# Scenario image for proof_conference: Lean 4, Mathlib and a pinned Formal Conjectures checkout,
# ready to compile problem files offline as an ordinary user on a read-only root filesystem.
# Built on swarmbench's base image (build context: this folder). The slow downloads and builds are
# in lean/Dockerfile, which swarmbench builds and tags first and passes in as LEAN_IMAGE; this file
# only copies the finished toolchain and project onto the base image, so it is quick to rebuild.
# lean-check itself is a protected file (protected/conference/bin/lean-check, copied into /opt
# when each run's team image is built), so editing it does not rebuild this image either.
ARG BASE_IMAGE
ARG LEAN_IMAGE
FROM ${LEAN_IMAGE} AS lean

FROM ${BASE_IMAGE}
ARG LEAN_TOOLCHAIN=leanprover/lean4:v4.33.1
ENV ELAN_HOME=/usr/local/elan
COPY --from=lean /usr/local/elan /usr/local/elan
COPY --from=lean /srv/fc /srv/fc
RUN bin="$ELAN_HOME/toolchains/$(echo "${LEAN_TOOLCHAIN}" | sed 's|/|--|; s|:|---|')/bin" \
    && for b in lean lake leanc; do ln -sf "$bin/$b" /usr/local/bin/$b; done \
    && lean --version \
    && ln -s /opt/conference/bin/lean-check /usr/local/bin/lean-check
