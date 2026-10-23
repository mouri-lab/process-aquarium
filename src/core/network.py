"""Bounded, independent interface activity sampling for ambient water motion."""

import ipaddress
import math
import time

import psutil

from ..telemetry import NetworkActivity


class NetworkSampler:
    def __init__(self, interface=None, *, clock=time.monotonic):
        if interface is not None and (not isinstance(interface, str) or
                                      not interface or len(interface) > 128):
            raise ValueError("Network interface must be 1..128 characters")
        self.interface = interface
        self.clock = clock
        self.previous = None

    def reset(self, status="unavailable", interface=""):
        self.previous = None
        return NetworkActivity(status, interface)

    @staticmethod
    def loopback(name, stat, addresses):
        flags = getattr(stat, "flags", "")
        if "loopback" in flags or name.lower() in ("lo", "lo0", "loopback"):
            return True
        for addr in addresses:
            try:
                if ipaddress.ip_address(addr.address.split("%")[0]).is_loopback:
                    return True
            except ValueError:
                pass
        return False

    def sample(self):
        try:
            # Disable psutil's wrap compensation: a reset must create a fresh
            # baseline, not look like a large transfer.
            counters = psutil.net_io_counters(pernic=True, nowrap=False)
            stats = psutil.net_if_stats()
            addresses = psutil.net_if_addrs()
            eligible = [name for name in counters
                        if name in stats and stats[name].isup and
                        not self.loopback(name, stats[name], addresses.get(name, ()))]
            if self.interface:
                name = self.interface
                if name not in eligible:
                    return self.reset("unavailable", name)
            else:
                # Conservative auto-selection. Never sum physical + virtual
                # interfaces, and never guess between two viable adapters.
                virtual = ("utun", "tun", "tap", "bridge", "br-", "veth", "docker",
                           "virbr", "vmnet", "vbox", "awdl", "llw", "gif", "stf",
                           "wg", "tailscale", "ipsec", "zt", "vpn")
                eligible = [n for n in eligible if not n.lower().startswith(virtual)]
                if len(eligible) != 1:
                    return self.reset("ambiguous" if eligible else "unavailable")
                name = eligible[0]
            count = counters[name]
            sent, received = count.bytes_sent, count.bytes_recv
            if any(type(v) is not int or v < 0 for v in (sent, received)):
                return self.reset("error", name)
            identity = (name, tuple(sorted((str(a.family), a.address)
                                          for a in addresses.get(name, ()))))
            now = self.clock()
            previous = self.previous
            self.previous = (identity, now, sent, received)
            if previous is None or previous[0] != identity:
                return NetworkActivity("warming", name)
            interval = now - previous[1]
            tx, rx = sent - previous[2], received - previous[3]
            if (not math.isfinite(interval) or interval <= 0 or
                    min(tx, rx) < 0 or max(tx, rx) > 2**53 - 1):
                return NetworkActivity("warming", name)
            return NetworkActivity("ready", name, interval, tx, rx)
        except (psutil.AccessDenied, PermissionError):
            return self.reset("denied", self.interface or "")
        except NotImplementedError:
            return self.reset("unsupported", self.interface or "")
        except (psutil.Error, OSError):
            return self.reset("error", self.interface or "")
