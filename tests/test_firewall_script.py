"""The step container firewall script: syntax, the allowed-proxy lines, and the probe markers."""
import subprocess
from pathlib import Path

import pytest

from phoenix9 import docker

SCRIPT = Path(__file__).resolve().parent.parent / "image" / "init-firewall.sh"


def test_firewall_script_syntax():
    assert subprocess.run(["bash", "-n", str(SCRIPT)]).returncode == 0


def test_firewall_script_reads_allowed_proxy():
    text = SCRIPT.read_text()
    assert "/etc/hands/allowed-proxy" in text and "ERROR: bad proxy line" in text
    accept = 'iptables -A OUTPUT -d "$p_ip" -p tcp --dport "$p_port" -j ACCEPT'
    reject = "iptables -A OUTPUT -j REJECT"
    assert text.index(accept) < text.index(reject)
    assert text.index("/etc/hands/allowed-domains") < text.index(accept)
    assert docker.ALLOWED_PROXY_MOUNT == "/etc/hands/allowed-proxy"
    assert "0.0.0.0" not in text.split(accept)[0].split("valid_proxy_line()")[1]


@pytest.mark.parametrize("ip,port,ok", [("172.17.0.1", "8080", True), ("127.0.0.1", "65535", True),
                                        ("172.17.0.1", "0", False), ("172.17.0.1", "65536", False),
                                        ("172.17.0.256", "80", False), ("host.name", "80", False),
                                        ("1.2.3", "80", False), ("1.2.3.4", "8x", False), ("1.2.3.4", "", False)])
def test_proxy_line_validation(ip, port, ok):
    lines = SCRIPT.read_text().splitlines()
    start = lines.index("valid_proxy_line() {")
    end = lines.index("}", start)
    fn = "\n".join(lines[start:end + 1])
    r = subprocess.run(["bash", "-c", f"IFS=$'\\n\\t'\n{fn}\nvalid_proxy_line \"$1\" \"$2\"", "x", ip, port])
    assert (r.returncode == 0) is ok


def test_probe_checks_proxy_markers():
    base = ("blocked ip-blocked anthropic=200 cannot-flush no-sudo v6-blocked dns-allowed-ok dns-random-blocked "
            "dns-direct-blocked-1.1.1.1+udp dns-direct-blocked-1.1.1.1+tcp dns-direct-blocked-8.8.8.8+udp "
            "dns-direct-blocked-8.8.8.8+tcp dnsmasq-running dnsmasq-survived dnsconf-readonly ssh-blocked "
            "host-blocked ghip-blocked gh-dns-blocked github=000 1000")
    assert all(ok for ok, _ in docker.firewall_checks(base))            # no proxy given: no proxy check
    bad = docker.firewall_checks(base, ("172.17.0.1", 5000))
    assert [label for ok, label in bad if not ok] == ["the allowed key proxy address is reachable"]
    good = docker.firewall_checks(base + " proxy-reachable", ("172.17.0.1", 5000))
    assert all(ok for ok, _ in good)
    assert not all(ok for ok, _ in docker.firewall_checks(base + " proxy-reachable PROXY-UNREACHABLE",
                                                          ("172.17.0.1", 5000)))
    assert "proxy-reachable" in docker.proxy_probe("172.17.0.1", 5000)
