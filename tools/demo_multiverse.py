"""Publish synthetic, same-PID hosts to a local server for multiverse UI review.

Run main.py server --port 8765, then this script. No real process data is read.
"""
import argparse
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.telemetry import Snapshot, ProcessRecord, Connection, NetworkActivity, SimulatedTransfer
from src.transport import APIClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='http://127.0.0.1:8765')
    parser.add_argument('--hosts', type=int, default=3)
    parser.add_argument('--stale-last', action='store_true')
    parser.add_argument('--tides', choices=['cycle', 'receive', 'send', 'both', 'idle', 'missing'],
                        help='Synthetic interface activity for water-current review')
    parser.add_argument('--between-tanks', action='store_true',
                        help='Simulate traffic between neighbouring tanks (no real measurements)')
    args = parser.parse_args()
    if not 1 <= args.hosts <= 128:
        parser.error('--hosts must be 1..128')
    client = APIClient(args.server)
    session = uuid.uuid4().hex
    names = ['chrome', 'code', 'systemd', 'slack', 'docker', 'zsh', 'python']
    places = ['こもれび', 'しおさい', 'よいまち', 'あわゆき', 'うたたね', 'ほしあかり', 'さざなみ', 'つきしろ']
    sequence = 0
    try:
        while True:
            sequence += 1
            transfers, activities = demo_transfers(args.hosts, sequence)
            for host in range(args.hosts):
                if args.stale_last and host == args.hosts - 1 and sequence > 1:
                    continue
                processes = tuple(ProcessRecord(
                    pid=100+i, ppid=100 if i % 4 else 2,
                    name=names[(i+host) % len(names)], exe='', cmdline=(),
                    cpu_percent=(i*7+host*3) % 40, memory_percent=.2+(i % 4)*.35,
                    num_threads=1+i % 4, create_time=100+i, status='running',
                ) for i in range(14+host % 3*7))
                snapshot = Snapshot(
                    host_id=f'demo-{host}', hostname=places[host % len(places)] + (f' {host+1}' if host >= 8 else ''),
                    boot_id=f'boot-{host}', session_id=session, sequence=sequence,
                    collected_at=time.time(), source='fixture', processes=processes,
                    events=(), connections=(Connection(100, 101, 'pipe'),),
                    network_activity=activities[host] if args.between_tanks else demo_activity(args.tides, sequence, host),
                    simulated_transfers=transfers[host] if args.between_tanks else (),
                )
                client.request('POST', '/api/v1/snapshots', snapshot.to_dict())
            time.sleep(1)
    except KeyboardInterrupt:
        pass


def demo_activity(mode, sequence, host):
    if not mode:
        return None
    if mode == 'cycle':
        mode = ['receive', 'send', 'both', 'idle', 'missing'][((sequence - 1) // 16 + host) % 5]
    if mode == 'missing':
        return NetworkActivity('unavailable', 'demo0')
    return NetworkActivity('ready', 'demo0', 1,
                           4 * 1024**2 if mode in ('send', 'both') else 0,
                           4 * 1024**2 if mode in ('receive', 'both') else 0)


def demo_transfers(hosts, sequence):
    """One owner per pair; interface totals agree with the simulated transfers."""
    transfers = [[] for _ in range(hosts)]
    totals = [[0, 0] for _ in range(hosts)]
    stage = ((sequence - 1) // 16) % 5
    for host in range(hosts - 1):
        # Gentle -> broad -> reverse -> exchange -> settle. Flow speed stays
        # constant in the client; volume changes the breadth and light only.
        tx, rx = [(32 * 1024, 0), (8 * 1024**2, 0), (0, 2 * 1024**2),
                  (4 * 1024**2, 4 * 1024**2), (0, 0)][stage]
        transfers[host].append(SimulatedTransfer(f'demo-{host+1}', f'boot-{host+1}', 1, tx, rx))
        totals[host][0] += tx
        totals[host][1] += rx
        totals[host+1][0] += rx
        totals[host+1][1] += tx
    return ([tuple(t) for t in transfers],
            [NetworkActivity('ready', 'demo0', 1, tx, rx) for tx, rx in totals])


if __name__ == '__main__':
    main()
