"""The one host firewall (ufw) rule Phoenix needs: step containers on the Docker bridge may reach the
key proxy on the bridge gateway, on the proxy's fixed port range only (architecture 14).

deploy/install.sh adds the same rule (it builds the same text from the same values; a test checks the
two agree) and `phoenix doctor` looks for it in `ufw status`. Pure functions only: no I/O here.
"""
import ipaddress
import re
import shlex

RULE_COMMENT = "phoenix9 key proxy"


def ufw_rule_args(interface: str, subnet: str, gateway: str, ports: tuple[int, int]) -> list[str]:
    """The ufw command (as argv) allowing TCP from the bridge subnet to the gateway on the proxy ports."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,15}", interface or ""):
        raise ValueError(f"not a network interface name: {interface!r}")
    net = ipaddress.IPv4Network(subnet, strict=False)
    gw = ipaddress.IPv4Address(gateway)
    lo, hi = int(ports[0]), int(ports[1])
    return ["ufw", "allow", "in", "on", interface, "from", str(net), "to", str(gw),
            "port", f"{lo}:{hi}", "proto", "tcp", "comment", RULE_COMMENT]


def ufw_rule_text(interface: str, subnet: str, gateway: str, ports: tuple[int, int]) -> str:
    """The same command as one line to paste into a root shell."""
    return shlex.join(ufw_rule_args(interface, subnet, gateway, ports))


def ufw_active(status: str) -> bool:
    """True when `ufw status` says 'Status: active'."""
    return bool(re.search(r"^Status:\s*active\b", status or "", re.M))


def rule_present(status: str, interface: str, subnet: str, gateway: str, ports: tuple[int, int]) -> bool:
    """True when `ufw status` lists the rule (to gateway on the port range, in on the interface, from subnet)."""
    net = ipaddress.IPv4Network(subnet, strict=False)
    to = rf"{re.escape(gateway)}\s+{int(ports[0])}:{int(ports[1])}/tcp\s+on\s+{re.escape(interface)}"
    line = rf"^{to}\s+ALLOW(\s+IN)?\s+{re.escape(str(net))}(\s|$)"
    return bool(re.search(line, status or "", re.M))
