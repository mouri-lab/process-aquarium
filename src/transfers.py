"""Resolve measured IP traffic into directed host currents, without guessing."""

from collections import defaultdict


def resolve_transfers(hosts, *, stale_after, limit=512):
    """hosts contains (snapshot, monotonic receipt age). Sender wins per direction.

    Different observation windows are never added or compared by maximum. An
    available sender's empty peer list means zero, not permission to replay the
    receiver's older nonzero window. Unresolved/external traffic stays in the
    original host telemetry and never creates a galaxy.
    """
    addresses = defaultdict(set)
    live = {}
    for snapshot, age in hosts:
        activity = snapshot.network_peers
        if activity is None or snapshot.source == "fixture":
            continue
        for address in activity.addresses:
            addresses[activity.network_scope, address].add(snapshot.host_id)
        if not snapshot.error and age <= stale_after:
            live[snapshot.host_id] = (snapshot, age)

    observations = {}
    pairs = set()
    for host_id, (snapshot, age) in live.items():
        activity = snapshot.network_peers
        if activity.status != "ready":
            continue
        totals = defaultdict(lambda: [0, 0])
        for peer in activity.peers:
            matches = addresses[activity.network_scope, peer.address]
            if len(matches) != 1:
                continue
            target = next(iter(matches))
            if target == host_id or target not in live:
                continue
            totals[target][0] += peer.sent_bytes
            totals[target][1] += peer.received_bytes
            pairs.add((host_id, target))
            pairs.add((target, host_id))
        observations[host_id] = totals

    def identity(snapshot):
        return {k: getattr(snapshot, k) for k in ("host_id", "boot_id", "session_id")}

    result = []
    for sender, receiver in sorted(pairs):
        # Only one observer supplies each direction. Never sum both ends.
        owner = sender if sender in observations else receiver
        direction = 0 if owner == sender else 1
        other = receiver if owner == sender else sender
        amount = observations[owner].get(other, (0, 0))[direction]
        if amount <= 0 or amount > 2**53 - 1:
            continue
        snapshot, age = live[owner]
        activity = snapshot.network_peers
        result.append({
            "source": identity(live[sender][0]), "target": identity(live[receiver][0]),
            "observer": {**identity(snapshot), "sequence": snapshot.sequence,
                         "interface": activity.interface},
            "network_scope": activity.network_scope, "byte_basis": activity.byte_basis,
            "interval_seconds": activity.interval_seconds, "bytes": amount,
            "age_seconds": age,
        })
    return result[:limit]
