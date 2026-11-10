# Setting up the Phoenix agent service

This is the new agent's service. It runs on its own, as its own user (never root), and only listens on
`127.0.0.1:8097`. Phoenix itself is at `http://127.0.0.1:8095`.

## 1. Run the setup (as root, after the merge)

    sh /opt/phoenix9/deploy/agentkit/setup.sh

It is safe to run twice. It makes the `phoenix-agentkit` user and its folder `/var/lib/phoenix9/agentkit/`,
builds the agent's own environment, copies the example settings (an existing settings file is kept), makes the
shared token without showing it, and tells Phoenix who the agent is in `global.toml`. It never creates or
touches the key.

If the unit file is not in `/etc/systemd/system/` afterwards, copy `phoenix-agentkit.service` there and run
`systemctl daemon-reload`.

## 2. Put the key in place

Save your Claude API key as the file `/var/lib/phoenix9/agentkit/api-key`, owned by `phoenix-agentkit`, with
mode 600:

    chown phoenix-agentkit:phoenix-agentkit /var/lib/phoenix9/agentkit/api-key
    chmod 600 /var/lib/phoenix9/agentkit/api-key

Only the agent service uses this key. Nothing else in Phoenix does, and it is never put in the environment.

## 3. Check the price table before first use

Open `/var/lib/phoenix9/agentkit/config.toml`. The price table says "CHECK BEFORE USE". Compare it with
Anthropic's price page and fill in the real numbers for the model you use. Until every price is a number, the
agent refuses to answer and says its price list hasn't been checked yet. That is on purpose: it is how the
monthly allowance can never be skipped.

## 4. Start it

    systemctl enable --now phoenix-agentkit

## 5. Check

    phoenix doctor

The agent's lines should say it is running and the key is there. The panel is at `#/agent-next` in the
dashboard.
