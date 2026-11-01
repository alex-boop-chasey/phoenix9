# Mobile profile: Node 24 + Expo tooling (eas-cli) + JDK 17. No Android SDK yet: native Android builds are not possible in this image. Build from the repo root: docker build -f profiles/<p>/image/Dockerfile -t <tag> .
FROM node:24-bookworm

ARG TZ=Australia/Brisbane
ENV TZ=$TZ
# Defaults match image/versions.env (one source of truth)
ARG CLAUDE_CODE_VERSION=2.1.301
ARG EAS_CLI_VERSION=16.28.0

RUN apt-get update && apt-get install -y --no-install-recommends \
  less git procps sudo unzip gnupg2 curl ca-certificates jq iptables ipset iproute2 dnsutils aggregate dnsmasq-base openjdk-17-jdk-headless \
  && apt-get clean && rm -rf /var/lib/apt/lists/*

ENV NPM_CONFIG_PREFIX=/usr/local/share/npm-global \
    PATH=$PATH:/usr/local/share/npm-global/bin \
    DEVCONTAINER=true \
    DISABLE_AUTOUPDATER=1
RUN mkdir -p /usr/local/share/npm-global /workspace /home/node/.claude && \
  chown -R node:node /usr/local/share/npm-global /workspace /home/node/.claude
RUN corepack enable
RUN npm install -g eas-cli@${EAS_CLI_VERSION}
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
