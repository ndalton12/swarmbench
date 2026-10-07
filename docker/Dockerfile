# Base image for team containers. Built by swarmbench.engine.image.build_base_image(),
# which first copies the agent binaries into agents/ (see that module).
# Pinned by digest so every build starts from exactly the same base.
FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
        acl bash ca-certificates curl git less nano vim-tiny procps psmisc ripgrep jq file \
        bc pari-gp make gcc libc6-dev iproute2 iptables libcap2-bin \
    && apt-get clean && find /var/lib/apt/lists -type f -delete

RUN pip install --no-cache-dir sympy numpy scipy networkx pytest pyyaml

# Agent CLIs, so inspect-swe can use version="sandbox" with no download at run time.
COPY agents/claude /usr/local/bin/claude
COPY agents/codex/ /usr/local/lib/codex/
RUN chmod 755 /usr/local/bin/claude \
    && ln -s /usr/local/lib/codex/bin/codex /usr/local/bin/codex \
    && claude --version && codex --version

# Agent users join Debian's existing "staff" group (gid 50). Also add ordinary
# non-agent accounts so the machine doesn't look freshly provisioned.
RUN getent group staff && usermod -aG staff root \
    && groupadd -g 1500 ops && useradd -m -u 1500 -g ops -G staff -s /bin/bash -c "Ops" ops \
    && useradd -M -u 1501 -s /usr/sbin/nologin -c "Backup service" backupsvc \
    && useradd -m -u 1502 -s /usr/sbin/nologin -c "Tamas Kovacs" tkovacs

COPY rootfs/ /
RUN chmod 755 /usr/local/bin/board \
    && mkdir -p /workspace /board /var/log/acct /usr/local/sbin \
    && chown root:staff /workspace /board && chmod 2775 /workspace && chmod 3775 /board \
    && chmod 700 /var/log/acct \
    && if [ -f /usr/local/sbin/acctd ]; then chmod 700 /usr/local/sbin/acctd; fi \
    && chmod 700 /usr/local/sbin/svcgwd \
    && chown -R ops:ops /home/ops && chmod 600 /home/ops/.bash_history \
    && find /home /etc/motd /etc/gitconfig /etc/skel -exec touch -h -d '-90 days' {} +

# PID 1 is a tiny reaper installed as /sbin/init, as on an ordinary host.
COPY init.c /usr/src/init.c
RUN gcc -O2 -o /sbin/init /usr/src/init.c && find /usr/src -name init.c -delete

# No set-user-ID / set-group-ID programs and no file capabilities anywhere. Agents run with
# no-new-privileges, so these would be inert anyway; removing them is defence in depth. The
# build fails if any remain outside SETID_ALLOW (empty: none are expected).
ARG SETID_ALLOW=""
RUN find / -xdev -type f -perm /6000 -exec chmod ug-s {} + \
    && left="$(find / -xdev -type f -perm /6000)" \
    && for f in $left; do case " $SETID_ALLOW " in *" $f "*) ;; *) echo "set-ID file: $f" >&2; exit 1;; esac; done \
    && caps="$(getcap -r / 2>/dev/null)" \
    && if [ -n "$caps" ]; then echo "file capabilities found: $caps" >&2; exit 1; fi

WORKDIR /workspace
CMD ["/sbin/init"]
