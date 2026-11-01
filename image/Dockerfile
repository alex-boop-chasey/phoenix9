FROM node:24-bookworm

ARG TZ=Australia/Brisbane
ENV TZ=$TZ
# Defaults match versions.env, so a plain `docker build -t phoenix9-step:base image/` works (ported from reference/v8/image/Dockerfile; profiles get their own Dockerfiles under profiles/<name>/image/)
ARG CLAUDE_CODE_VERSION=2.1.301
ARG PLAYWRIGHT_VERSION=1.64.1

RUN apt-get update && apt-get install -y --no-install-recommends \
  less git procps sudo unzip gnupg2 curl ca-certificates \
  iptables ipset iproute2 dnsutils aggregate jq \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN corepack enable

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global \
    PATH=$PATH:/usr/local/share/npm-global/bin \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    DEVCONTAINER=true \
    DISABLE_AUTOUPDATER=1

RUN mkdir -p /usr/local/share/npm-global /workspace /home/node/.claude /ms-playwright && \
  chown -R node:node /usr/local/share/npm-global /workspace /home/node/.claude /ms-playwright

# Browser system libraries (root)
RUN test -n "$PLAYWRIGHT_VERSION" && npx -y playwright@${PLAYWRIGHT_VERSION} install-deps chromium

USER node
RUN test -n "$CLAUDE_CODE_VERSION" && \
  npm install -g @anthropic-ai/claude-code@${CLAUDE_CODE_VERSION} && \
  npx -y playwright@${PLAYWRIGHT_VERSION} install chromium

USER root
# DNS allowlist resolver (init-firewall.sh runs it as root; the agent uid gets /etc/resolv.conf -> 127.0.0.1)
RUN apt-get update && apt-get install -y --no-install-recommends dnsmasq-base \
  && apt-get clean && rm -rf /var/lib/apt/lists/*
COPY init-firewall.sh hands-dns-conf.sh /usr/local/bin/
RUN chmod 755 /usr/local/bin/init-firewall.sh /usr/local/bin/hands-dns-conf.sh && \
  echo "node ALL=(root) NOPASSWD: /usr/local/bin/init-firewall.sh" > /etc/sudoers.d/node-firewall && \
  chmod 0440 /etc/sudoers.d/node-firewall
# Phoenix v8: entrypoint baked in (0.6.0 mounted it from the runner checkout)
COPY entry.sh /opt/hands/entry.sh
RUN chmod 755 /opt/hands/entry.sh
# Phoenix v8: Superpowers skills (obra/superpowers, see superpowers-PIN and superpowers-LICENSE)
COPY --chown=node:node skills/ /home/node/.claude/skills/
COPY superpowers-LICENSE superpowers-PIN /home/node/.claude/skills/
USER node
WORKDIR /workspace
