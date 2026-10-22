#!/usr/bin/env python3
"""
Process Aquarium- main entrypoint
Starts the Process Aquariumapplication.

Usage:
    python main.py

Or run directly after making executable:
    chmod +x main.py
    ./main.py
"""

import sys
import os
import argparse
import math

# Add project root directory to the import path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.core.runtime import create_process_manager


def positive_interval(value):
    interval = float(value)
    if not math.isfinite(interval) or interval <= 0:
        raise argparse.ArgumentTypeError("interval must be a finite positive number")
    return interval


def main_cli():
    parser = argparse.ArgumentParser(description="Process Aquarium")
    parser.add_argument("--headless", action="store_true", help="Run without opening a window; periodic stats to stdout")
    parser.add_argument("--headless-interval", type=positive_interval, default=1.0, help="Interval seconds between stats prints in headless mode")
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--source", choices=["psutil", "ebpf"], default=None, help="Process data source backend")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of processes displayed (default: no limit)")
    parser.add_argument("--sort-by", choices=["cpu", "memory", "name", "pid"], default="cpu", help="Sort processes by field (default: cpu)")
    parser.add_argument("--sort-order", choices=["asc", "desc"], default="desc", help="Sort order (default: desc)")
    parser.add_argument("--gpu-driver", default=None, help="SDL render driver hint (e.g. metal, opengl, direct3d)")
    parser.add_argument("--gpu", dest="gpu", action="store_true", help="Enable SDL2 GPU accelerated renderer (requires pygame-ce)")
    parser.add_argument("--no-gpu", dest="gpu", action="store_false", help="Disable SDL2 GPU renderer even if environment requests it")
    parser.add_argument("--adaptive-quality", dest="adaptive_quality", action="store_true",
                        help="Enable automatic downshifting of visual quality when average FPS drops")
    parser.add_argument("--no-adaptive-quality", dest="adaptive_quality", action="store_false",
                        help="Disable automatic FPS-based quality adjustments (default)")
    parser.set_defaults(gpu=None)
    parser.set_defaults(adaptive_quality=None)
    args = parser.parse_args()

    if args.gpu_driver:
        os.environ["AQUARIUM_GPU_DRIVER"] = args.gpu_driver
    if args.gpu is None:
        os.environ.setdefault("AQUARIUM_GPU", "1")
    else:
        os.environ["AQUARIUM_GPU"] = "1" if args.gpu else "0"
    if args.adaptive_quality is not None:
        os.environ["AQUARIUM_ENABLE_ADAPTIVE_QUALITY"] = "1" if args.adaptive_quality else "0"
    # The entry point owns collection. Presentations only receive a ready backend.
    limit = args.limit
    if limit is None:
        limit_value = os.environ.get("AQUARIUM_LIMIT")
        limit = int(limit_value) if limit_value else None
    process_manager = create_process_manager(
        args.source or os.environ.get("AQUARIUM_SOURCE", "ebpf").lower(),
        max_processes=int(os.environ.get("AQUARIUM_MAX_PROCESSES", "2000")),
        process_limit=limit,
        sort_by=args.sort_by,
        sort_order=args.sort_order,
    )
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


if __name__ == "__main__":
    main_cli()
