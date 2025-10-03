"""
Visual components for Process Aquarium.
Now with GPU acceleration using Pyglet! Falls back to Pygame if needed.
"""

import os
import sys

# Determine which backend to use
BACKEND = os.environ.get('AQUARIUM_BACKEND', 'pyglet').lower()

if BACKEND == 'pygame':
    print("[Backend] Using Pygame renderer")
    from .aquarium_pygame import Aquarium
    from .fish_pygame import Fish
elif BACKEND == 'pyglet':
    print("[Backend] Using Pyglet renderer (GPU-accelerated) 🚀")
    try:
        from .aquarium_pyglet import Aquarium
        from .fish_pyglet import Fish
    except ImportError as e:
        print(f"[Backend] Pyglet not available ({e}), falling back to Pygame")
        from .aquarium_pygame import Aquarium
        from .fish_pygame import Fish
else:
    print(f"[Backend] Unknown backend '{BACKEND}', using Pyglet")
    try:
        from .aquarium_pyglet import Aquarium
        from .fish_pyglet import Fish
    except ImportError:
        print("[Backend] Pyglet not available, falling back to Pygame")
        from .aquarium_pygame import Aquarium
        from .fish_pygame import Fish

__all__ = ['Aquarium', 'Fish']

