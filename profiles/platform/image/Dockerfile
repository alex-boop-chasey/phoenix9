# Platform profile (full-stack): Node 24 + Python 3.13 (Debian 13) + pytest + pnpm (switches to the project-pinned version). Build from the repo root: docker build -f profiles/<p>/image/Dockerfile -t <tag> .
FROM node:24-trixie

ARG TZ=Australia/Brisbane
ENV TZ=$TZ
# Defaults match image/versions.env (one source of truth)
ARG CLAUDE_CODE_VERSION=2.1.301
ARG PNPM_VERSION=12.16.1
ARG PYTEST_VERSION=8.4.2

RUN apt-get update && apt-get install -y --no-install-recommends \
  less git procps sudo unzip gnupg2 curl ca-certificates jq iptables ipset iproute2 dnsutils aggregate dnsmasq-base python3 python3-pip python3-venv \
  && apt-get clean && rm -rf /var/lib/apt/lists/*
# pytest for Python projects (and for Phoenix building itself)
RUN pip install --no-cache-dir --break-system-packages pytest==${PYTEST_VERSION}

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global \
    PATH=$PATH:/usr/local/share/npm-global/bin \
    DEVCONTAINER=true \
    DISABLE_AUTOUPDATER=1
RUN mkdir -p /usr/local/share/npm-global /workspace /home/node/.claude && \
  chown -R node:node /usr/local/share/npm-global /workspace /home/node/.claude
RUN NPM_CONFIG_PREFIX=/usr/local npm install -g pnpm@${PNPM_VERSION}   # plain pnpm (not corepack): it switches to the version a project pins
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
