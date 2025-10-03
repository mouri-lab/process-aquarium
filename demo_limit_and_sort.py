#!/usr/bin/env python3
"""
Demo script to showcase the process limiting and sorting features.
This script demonstrates the various ways to configure process display.
"""

import subprocess
import sys
import time


def print_section(title):
    """Print a formatted section header"""
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60 + "\n")


def run_demo(args, description):
    """Run a demo with the given arguments"""
    print(f"📋 {description}")
    print(f"   Command: python main.py {' '.join(args)}")
    print()
    
    # In a real demo, you would run the command here
    # For this script, we'll just show what would be executed
    print("   Press Ctrl+C to stop and continue to next demo\n")


def main():
    """Run the demo"""
    print_section("Process Aquarium - Limiting & Sorting Demo")
    
    print("This demo showcases the new process limiting and sorting features.")
    print("Each example shows different configurations you can use.\n")
    
    demos = [
        {
            "args": ["--headless", "--limit", "10", "--sort-by", "cpu"],
            "description": "Display top 10 CPU-intensive processes"
        },
        {
            "args": ["--headless", "--limit", "20", "--sort-by", "memory", "--sort-order", "desc"],
            "description": "Display top 20 memory-consuming processes"
        },
        {
            "args": ["--headless", "--limit", "5", "--sort-by", "name", "--sort-order", "asc"],
            "description": "Display first 5 processes alphabetically"
        },
        {
            "args": ["--headless", "--sort-by", "pid", "--sort-order", "asc"],
            "description": "Display all processes sorted by PID"
        }
    ]
    
    print_section("Examples")
    
    for i, demo in enumerate(demos, 1):
        print(f"{i}. {demo['description']}")
        print(f"   python main.py {' '.join(demo['args'])}\n")
    
    print_section("Interactive GUI Controls")
    
    print("When running in GUI mode (without --headless), you can use:")
    print()
    print("  L - Cycle through process limits:")
    print("      None → 10 → 20 → 50 → 100 → 200 → None")
    print()
    print("  S - Cycle through sort fields:")
    print("      CPU → Memory → Name → PID → CPU")
    print()
    print("  O - Toggle sort order:")
    print("      Descending ↔ Ascending")
    print()
    print("The current settings are displayed in the statistics panel")
    print("in the upper left corner of the window.")
    
    print_section("Try It Yourself")
    
    print("Run any of the examples above to see the feature in action!")
    print()
    print("Example: python main.py --limit 10 --sort-by memory")
    print()


if __name__ == "__main__":
    main()
