#!/usr/bin/env python3
"""
Digital Life Aquarium - メイン実行ファイル
デジタル生命の水族館を起動します

使用方法:
    python main.py
    
あるいは直接実行:
    chmod +x main.py
    ./main.py
"""

import sys
import os
import argparse

# プロジェクトルートディレクトリをパスに追加
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.visuals import Aquarium


def main_cli():
    parser = argparse.ArgumentParser(description="Digital Life Aquarium")
    parser.add_argument("--headless", action="store_true", help="Run without opening a window; periodic stats to stdout")
    parser.add_argument("--headless-interval", type=float, default=1.0, help="Interval seconds between stats prints in headless mode")
    parser.add_argument("--width", type=int, default=1200)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--source", choices=["psutil", "ebpf"], default=None, help="Process data source backend")
    parser.add_argument("--limit", type=int, default=None, help="Limit the number of processes displayed (default: no limit)")
    parser.add_argument("--sort-by", choices=["cpu", "memory", "name", "pid"], default="cpu", help="Sort processes by field (default: cpu)")
    parser.add_argument("--sort-order", choices=["asc", "desc"], default="desc", help="Sort order (default: desc)")
    args = parser.parse_args()

    if args.source:
        os.environ["AQUARIUM_SOURCE"] = args.source
    if args.limit is not None:
        os.environ["AQUARIUM_LIMIT"] = str(args.limit)
    os.environ["AQUARIUM_SORT_BY"] = args.sort_by
    os.environ["AQUARIUM_SORT_ORDER"] = args.sort_order
    aquarium = Aquarium(width=args.width, height=args.height, headless=args.headless, headless_interval=args.headless_interval)
    aquarium.run()


if __name__ == "__main__":
    main_cli()
