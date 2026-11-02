"""The ufw rule for the key proxy, and the proxy_ports setting it is built from."""
import pytest

from phoenix9 import hostfw, settings

STATUS = ("Status: active\n\nTo                         Action      From\n--                         ------      ----\n"
          "22/tcp                     ALLOW       Anywhere\n")
RULE = "172.16.0.1 47100:47199/tcp on docker0 ALLOW       172.16.0.0/24              # phoenix9 key proxy\n"
ARGS = ("docker0", "172.16.0.0/24", "172.16.0.1", (47100, 47199))


def test_rule_text():
    assert hostfw.ufw_rule_text(*ARGS) == ("ufw allow in on docker0 from 172.16.0.0/24 to 172.16.0.1 port "
                                           "47100:47199 proto tcp comment 'phoenix9 key proxy'")
    assert hostfw.ufw_rule_args("docker0", "172.16.0.9/24", "172.16.0.1", (1, 2))[6] == "172.16.0.0/24"
    with pytest.raises(ValueError):
        hostfw.ufw_rule_args("docker0; rm", "172.16.0.0/24", "172.16.0.1", (1, 2))


def test_status_parsing():
    assert hostfw.ufw_active(STATUS) and not hostfw.ufw_active("Status: inactive\n")
    assert not hostfw.rule_present(STATUS, *ARGS)
    assert hostfw.rule_present(STATUS + RULE, *ARGS)
    assert hostfw.rule_present(STATUS + RULE.replace("ALLOW ", "ALLOW IN "), *ARGS)
    assert not hostfw.rule_present(STATUS + RULE, "docker0", "172.16.0.0/24", "172.16.0.1", (47100, 47150))
    assert not hostfw.rule_present(STATUS + RULE, "docker0", "10.0.0.0/8", "172.16.0.1", (47100, 47199))


def test_proxy_ports_setting(phoenix_env):
    assert settings.proxy_ports() == (47100, 47199)
    (phoenix_env["home"] / "config").mkdir(parents=True, exist_ok=True)
    (phoenix_env["home"] / "config" / "global.toml").write_text('proxy_ports = "48000 - 48010"\n')
    assert settings.proxy_ports() == (48000, 48010)
    for bad in ("80-90", "5000-4000", "47100", 47100, "47100-70000"):
        with pytest.raises(ValueError, match="proxy_ports"):
            settings.parse_port_range(bad)
