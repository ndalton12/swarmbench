ARG BASE_IMAGE
FROM ${BASE_IMAGE}

# Debian supplies compilers and source packages for offline builds on both ARM and x86.
# No rustup shims or per-root npm/cargo caches: ordinary users must be able to build.
RUN apt-get update && apt-get install -y --no-install-recommends \
        rustc cargo librust-serde-dev librust-serde-derive-dev librust-serde-json-dev \
        librust-tiny-http-dev golang-go nodejs node-typescript libnode-dev \
    && apt-get clean && find /var/lib/apt/lists -type f -delete \
    && rustc --version && cargo --version && go version && node --version && tsc --version \
    && test -d /usr/share/nodejs/@types/node \
    && test -d /usr/share/cargo/registry \
    && find / -xdev -type f -perm /6000 -exec chmod ug-s {} +

ENV GOPROXY=off GOSUMDB=off
