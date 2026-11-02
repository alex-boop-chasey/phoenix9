# Research profile: plain Debian + Node 24 (for Claude Code) + python3 + pandoc. Build from the repo root: docker build -f profiles/<p>/image/Dockerfile -t <tag> .
FROM debian:bookworm-slim

ARG TZ=Australia/Brisbane
ENV TZ=$TZ
# Defaults match image/versions.env (one source of truth)
ARG CLAUDE_CODE_VERSION=2.1.301
ARG NODE_VERSION=24.11.0
# Node 24 for Claude Code, from the official tarball (pinned)
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates xz-utils \
  && ARCH="$(dpkg --print-architecture | sed 's/amd64/x64/;s/arm64/arm64/')" \
  && curl -fsSLO "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-linux-${ARCH}.tar.xz" \
  && curl -fsSL "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt" | grep " node-v${NODE_VERSION}-linux-${ARCH}.tar.xz\$" | sha256sum -c - \
  && tar -xJf "node-v${NODE_VERSION}-linux-${ARCH}.tar.xz" -C /usr/local --strip-components=1 \
  && rm "node-v${NODE_VERSION}-linux-${ARCH}.tar.xz" \
  && apt-get clean && rm -rf /var/lib/apt/lists/*
# Non-root agent user `node`, uid 1000 (docker.py and claude.py hard-code /home/node)
RUN useradd --create-home --uid 1000 --shell /bin/bash node

RUN apt-get update && apt-get install -y --no-install-recommends \
  less git procps sudo unzip gnupg2 curl ca-certificates jq iptables ipset iproute2 dnsutils aggregate dnsmasq-base python3 pandoc xz-utils \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global \
    PATH=$PATH:/usr/local/share/npm-global/bin \
    DEVCONTAINER=true \
    DISABLE_AUTOUPDATER=1
RUN mkdir -p /usr/local/share/npm-global /workspace /home/node/.claude && \
  chown -R node:node /usr/local/share/npm-global /workspace /home/node/.claude
USER node
RUN test -n "$CLAUDE_CODE_VERSION" && \
  npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}
USER root
# Firewall and DNS allowlist (safety files, copied unchanged from image/)
COPY image/init-firewall.sh image/hands-dns-conf.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/init-firewall.sh /usr/local/bin/hands-dns-conf.sh && \
  echo "node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall
COPY image/entry.sh /opt/hands/entry.sh
RUN chmod 755 /opt/hands/entry.sh
# Superpowers skills (obra/superpowers, see superpowers-PIN and superpowers-LICENSE)
COPY --chown=node:node image/skills/ /home/node/.claude/skills/
COPY image/superpowers-LICENSE image/superpowers-PIN /home/node/.claude/skills/
USER node
WORKDIR /workspace
