import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import textwrap

import pytest


def test_gui_cli_renders_and_stops_the_collector():
    if importlib.util.find_spec("pygame") is None:
        pytest.skip("Install the gui extra to exercise rendering")

    result = subprocess.run(
        [sys.executable, "-c", textwrap.dedent("""
            import runpy
            import sys
            import threading
            import pygame
            from src.visuals.aquarium import Aquarium

            original_run = Aquarium.run

            def render_one_frame(self):
                pygame.event.post(pygame.event.Event(pygame.QUIT))
                original_run(self)

            Aquarium.run = render_one_frame
            sys.argv = ['main.py', '--source', 'psutil', '--no-gpu',
                        '--limit', '2', '--width', '480', '--height', '320']
            runpy.run_path('main.py', run_name='__main__')
            assert not pygame.get_init()
            assert not any(t.name == 'PsutilProcessSource' for t in threading.enumerate())
        """)],
        cwd=Path(__file__).resolve().parents[1],
        env={**os.environ, "SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"},
        capture_output=True, text=True, timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
