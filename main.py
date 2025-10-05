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

# Add project root directory to the import path
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.visuals.aquarium import Aquarium


def main_cli():
    parser = argparse.ArgumentParser(description="Process Aquarium")
    parser.add_argument("--headless", action="store_true", help="Run without opening a window; periodic stats to stdout")
    parser.add_argument("--headless-interval", type=float, default=1.0, help="Interval seconds between stats prints in headless mode")
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

    if args.source:
        os.environ["AQUARIUM_SOURCE"] = args.source
    else:
        os.environ.setdefault("AQUARIUM_SOURCE", "ebpf")
    if args.limit is not None:
        os.environ["AQUARIUM_LIMIT"] = str(args.limit)
    os.environ["AQUARIUM_SORT_BY"] = args.sort_by
    os.environ["AQUARIUM_SORT_ORDER"] = args.sort_order
    if args.gpu_driver:
        os.environ["AQUARIUM_GPU_DRIVER"] = args.gpu_driver
    if args.gpu is None:
        os.environ.setdefault("AQUARIUM_GPU", "1")
    else:
        os.environ["AQUARIUM_GPU"] = "1" if args.gpu else "0"
    if args.adaptive_quality is not None:
        os.environ["AQUARIUM_ENABLE_ADAPTIVE_QUALITY"] = "1" if args.adaptive_quality else "0"
    aquarium = Aquarium(width=args.width, height=args.height, headless=args.headless,
                        headless_interval=args.headless_interval, use_gpu=args.gpu)
    aquarium.run()


if __name__ == "__main__":
    main_cli()
