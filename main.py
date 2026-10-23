#!/usr/bin/env python3
"""Standalone aquarium, telemetry agent, or headless aggregation server."""

import argparse
import math
import os
import signal
import sys

from src.core.runtime import configure_manager, create_local_source, create_process_manager


def positive_interval(value):
    interval = float(value)
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("interval must be a finite positive number")
    return interval


def nonnegative(value):
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("value must be >= 0")
    return number


def positive_integer(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("value must be >= 1")
    return number


def port_number(value):
    number = nonnegative(value)
    if number > 65535:
        raise argparse.ArgumentTypeError("port must be <= 65535")
    return number


def _credentials(parser):
    parser.add_argument("--token", default=os.environ.get("AQUARIUM_TOKEN", ""),
                        help="API bearer token (prefer AQUARIUM_TOKEN)")


def _client_options(parser):
    parser.add_argument("--headless", action="store_true", help="Print statistics without GUI dependencies")
    parser.add_argument("--headless-interval", type=positive_interval, default=1.0)
    parser.add_argument("--width", type=positive_integer, default=1200)
    parser.add_argument("--height", type=positive_integer, default=800)
    origin = parser.add_mutually_exclusive_group()
    origin.add_argument("--source", choices=["psutil", "ebpf"], default=None)
    origin.add_argument("--server", help="Read from an aggregation server instead of collecting locally")
    parser.add_argument("--host", default=os.environ.get("AQUARIUM_HOST"), help="Remote host ID")
    parser.add_argument("--poll-interval", type=positive_interval, default=1.0)
    parser.add_argument("--timeout", type=positive_interval, default=3.0)
    parser.add_argument("--limit", type=nonnegative, default=None, help="Displayed processes; 0 means unlimited")
    parser.add_argument("--sort-by", choices=["cpu", "memory", "name", "pid"],
                        default=os.environ.get("AQUARIUM_SORT_BY", "cpu"))
    parser.add_argument("--sort-order", choices=["asc", "desc"], default=os.environ.get("AQUARIUM_SORT_ORDER", "desc"))
    parser.add_argument("--gpu-driver", default=None)
    parser.add_argument("--gpu", dest="gpu", action="store_true", help="Enable native SDL GPU rendering")
    parser.add_argument("--no-gpu", dest="gpu", action="store_false")
    parser.add_argument("--adaptive-quality", dest="adaptive_quality", action="store_true")
    parser.add_argument("--no-adaptive-quality", dest="adaptive_quality", action="store_false")
    parser.set_defaults(gpu=None, adaptive_quality=None)
    _credentials(parser)


def _run_client(args, parser):
    if args.gpu_driver:
        os.environ["AQUARIUM_GPU_DRIVER"] = args.gpu_driver
    if args.gpu is None:
        os.environ.setdefault("AQUARIUM_GPU", "1")
    else:
        os.environ["AQUARIUM_GPU"] = "1" if args.gpu else "0"
    if args.adaptive_quality is not None:
        os.environ["AQUARIUM_ENABLE_ADAPTIVE_QUALITY"] = "1" if args.adaptive_quality else "0"
    limit = args.limit
    if limit is None:
        limit_value = os.environ.get("AQUARIUM_LIMIT")
        limit = int(limit_value) if limit_value else None
    options = dict(max_processes=int(os.environ.get("AQUARIUM_MAX_PROCESSES", "2000")),
                   process_limit=limit, sort_by=args.sort_by, sort_order=args.sort_order)
    server = args.server or (os.environ.get("AQUARIUM_SERVER") if args.source is None else None)
    try:
        if server:
            from src.remote import RemoteProcessSource
            from src.transport import APIClient

            backend = RemoteProcessSource(APIClient(server, token=args.token, timeout=args.timeout),
                                          host_id=args.host, interval=args.poll_interval)
            process_manager = configure_manager(backend, **options)
        else:
            process_manager = create_process_manager(
                args.source or os.environ.get("AQUARIUM_SOURCE", "ebpf").lower(), **options)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    try:
        if args.headless:
            from src.headless import HeadlessMonitor

            HeadlessMonitor(process_manager, interval=args.headless_interval).run()
        else:
            try:
                from src.visuals.aquarium import Aquarium
            except ModuleNotFoundError as exc:
                if exc.name == "pygame":
                    parser.error("GUI requires pygame-ce; install with 'uv sync --extra gui' or use --headless")
                raise
            Aquarium(width=args.width, height=args.height, use_gpu=args.gpu,
                     process_manager=process_manager).run()
    finally:
        process_manager.shutdown()


def _run_agent(args, parser):
    from src.agent import Agent
    from src.transport import APIClient

    try:
        client = APIClient(args.server, token=args.token, timeout=args.timeout)
        source = create_local_source(args.source, host_id=args.host_id, interval=args.interval,
                                     network_interface=args.network_interface,
                                     network_peers=args.network_peers, network_scope=args.network_scope)
    except (ValueError, RuntimeError) as exc:
        parser.error(str(exc))
    try:
        Agent(source, client, interval=min(args.interval, 1.0)).run()
    except (ValueError, RuntimeError) as exc:
        parser.exit(1, f"{exc}\n")
    finally:
        source.shutdown()


def _run_server(args, parser):
    from src.server import SnapshotStore, TelemetryHTTPServer

    try:
        store = SnapshotStore(stale_after=args.stale_after, retention=args.retention, max_hosts=args.max_hosts)
        server = TelemetryHTTPServer((args.listen, args.port), store=store, token=args.token)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    try:
        print(f"[server] listening on http://{args.listen}:{server.server_port}", flush=True)
        server.serve_forever(poll_interval=0.2)
    finally:
        server.server_close()


def main_cli(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    # Preserve main.py --source ... and main.py --headless ... invocations.
    if not argv or (argv[0].startswith("-") and argv[0] not in ("--help", "-h")):
        argv.insert(0, "client")
    parser = argparse.ArgumentParser(description="Process Aquarium: agent → server → browser/native client")
    modes = parser.add_subparsers(dest="mode", required=True)
    client = modes.add_parser("client", help="Native aquarium or text statistics (legacy default)")
    _client_options(client)
    agent = modes.add_parser("agent", help="Collect this host and publish telemetry")
    agent.add_argument("--server", default=os.environ.get("AQUARIUM_SERVER"),
                       required=not bool(os.environ.get("AQUARIUM_SERVER")))
    agent.add_argument("--host-id", default=os.environ.get("AQUARIUM_HOST_ID"))
    agent.add_argument("--source", choices=["psutil", "ebpf"], default=os.environ.get("AQUARIUM_SOURCE", "ebpf"))
    agent.add_argument("--interval", type=positive_interval, default=1.0)
    agent.add_argument("--network-interface", default=os.environ.get("AQUARIUM_NETWORK_INTERFACE"),
                       help="One interface for water currents (e.g. en0 or eth0); auto-select only when unambiguous")
    agent.add_argument("--network-peers", choices=["auto", "ebpf", "off"],
                       default=os.environ.get("AQUARIUM_NETWORK_PEERS", "auto"),
                       help="Linux/BCC peer byte accounting (independent of the process source)")
    agent.add_argument("--network-scope", default=os.environ.get("AQUARIUM_NETWORK_SCOPE", "default"),
                       help="Shared routing domain for peer IP matching; use distinct names for overlapping networks")
    agent.add_argument("--timeout", type=positive_interval, default=3.0)
    _credentials(agent)
    server = modes.add_parser("server", help="Aggregate telemetry and serve the browser client")
    server.add_argument("--listen", default="127.0.0.1")
    server.add_argument("--port", type=port_number, default=8080)
    server.add_argument("--stale-after", type=positive_interval, default=5.0)
    server.add_argument("--retention", type=positive_interval, default=3600.0)
    server.add_argument("--max-hosts", type=positive_integer, default=128)
    _credentials(server)
    args = parser.parse_args(argv)
    try:
        if args.mode == "agent":
            _run_agent(args, parser)
        elif args.mode == "server":
            _run_server(args, parser)
        else:
            _run_client(args, parser)
    except KeyboardInterrupt:
        print("\n[process-aquarium] stopped", flush=True)


def _interrupt(signum, frame):
    raise KeyboardInterrupt


if __name__ == "__main__":
    signal.signal(signal.SIGTERM, _interrupt)
    main_cli()
