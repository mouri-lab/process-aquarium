"""Publish synthetic, same-PID hosts to a local server for multiverse UI review.

Run main.py server --port 8765, then this script. No real process data is read.
"""
import argparse
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.telemetry import Snapshot, ProcessRecord, Connection
from src.transport import APIClient


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--server', default='http://127.0.0.1:8765')
    parser.add_argument('--hosts', type=int, default=3)
    parser.add_argument('--stale-last', action='store_true')
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
                )
                client.request('POST', '/api/v1/snapshots', snapshot.to_dict())
            time.sleep(1)
    except KeyboardInterrupt:
        pass


if __name__ == '__main__':
    main()
