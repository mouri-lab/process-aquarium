"""
Process Aquarium- Main Aquarium Visualization
Main aquarium rendering and interaction management.
"""

import pygame
import sys
import time
import random
import math
import os
from typing import Dict, List, Optional, Tuple
from ..core.process_manager import ProcessManager
try:
    # Extension point to swap in an eBPF source implementation when available
    from ..core.sources import EbpfProcessSource
except Exception:  # pragma: no cover - safe fallback
    EbpfProcessSource = None  # type: ignore
from .fish import Fish

# Text/locale encoding configuration
import locale
try:
    locale.setlocale(locale.LC_ALL, 'ja_JP.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except:
        pass  # continue even if locale setup fails

class Aquarium:
    """
    Main class for the Process Aquarium.
    Integrates process monitoring with visualization and interaction management.
    """

    def __init__(self, width: int = 1200, height: int = 800, headless: bool = False,
                 headless_interval: float = 1.0, use_gpu: Optional[bool] = None):
    # Initialize pygame
        self.headless = headless
        self.headless_interval = headless_interval
        if self.headless:
            # Use dummy video driver to suppress window creation in headless mode
            os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        self._gpu_texture_type = None
        self.gpu_renderer = None
        self.gpu_window = None
        self.gpu_texture = None
        self.requested_gpu = use_gpu if use_gpu is not None else self._env_flag("AQUARIUM_GPU", False)
        if self.headless and self.requested_gpu:
            # Developer log: GPU renderer disabled when running in headless mode
            print("[GPU] GPU renderer disabled because headless mode is active.")
            self.requested_gpu = False
        self.gpu_driver_hint = os.environ.get("AQUARIUM_GPU_DRIVER")
        if self.requested_gpu and self.gpu_driver_hint:
            os.environ.setdefault("SDL_HINT_RENDER_DRIVER", self.gpu_driver_hint)
        self.use_gpu = False
        self.enable_adaptive_quality = self._env_flag("AQUARIUM_ENABLE_ADAPTIVE_QUALITY", False)
        self.render_quality = "full"
        self._quality_thresholds = (None, None)
        recovery_margin_env = os.environ.get("AQUARIUM_QUALITY_RECOVERY_MARGIN")
        try:
            recovery_margin = float(recovery_margin_env) if recovery_margin_env else 3.0
        except ValueError:
            recovery_margin = 3.0
        self._quality_recovery_margin = max(0.0, min(recovery_margin, 10.0))
        self._suppress_spawn_logs = False
        self._quality_message_shown = set()
        self._windowevent_type = getattr(pygame, "WINDOWEVENT", None)
        self._windowevent_resized = getattr(pygame, "WINDOWEVENT_RESIZED", None)
        self._windowevent_size_changed = getattr(pygame, "WINDOWEVENT_SIZE_CHANGED", None)
        self._windowevent_close = getattr(pygame, "WINDOWEVENT_CLOSE", None)
        pygame.init()
        try:
            pygame.mixer.init()
        except pygame.error:
        # Ignore if audio device is not available
            print("⚠️  オーディオデバイスが利用できません。音声なしで継続します。")
            pass

    # macOS Retina-related environment variable settings
        os.environ['SDL_VIDEO_HIGHDPI_DISABLED'] = '0'  # Enable high DPI support

    # Read settings from environment variables (significantly relaxed limits)
        max_processes = int(os.environ.get('AQUARIUM_MAX_PROCESSES', '2000'))  # Increased default from 500 to 2000
        target_fps = int(os.environ.get('AQUARIUM_FPS', '30'))

    # Screen settings
        self.base_width = width
        self.base_height = height
        self.width = width
        self.height = height
        self.fullscreen = False
        self.scale_factor = 1.0  # Retina scaling factor

    # Print available resolution info (debug)
        self._print_display_info()

    # Detect Retina scaling information
        self.retina_info = self.detect_retina_scaling()

        if not self.headless:
            if self.requested_gpu:
                self._init_gpu_renderer(width, height)
            if not self.use_gpu:
                self.screen = pygame.display.set_mode((width, height))
                pygame.display.set_caption("Process Aquarium - プロセス水族館")
        else:
            # Provide a dummy surface for rendering in headless mode
            self.screen = pygame.Surface((width, height))

    # Clock and FPS configuration
        self.clock = pygame.time.Clock()
        self.fps = target_fps if not self.headless else int(1.0 / max(headless_interval, 0.001))
        self._configure_quality_thresholds()

    # Process management
    # When eBPF is enabled in the future, we plan to allow injecting an
    # `EbpfProcessSource` via command line or environment variables.
    # Example: if os.environ.get("AQUARIUM_SOURCE") == "ebpf": source = EbpfProcessSource()
        source = None
        chosen = os.environ.get("AQUARIUM_SOURCE", "psutil").lower()
        if chosen == "ebpf":
            try:
                from ..core.sources import EbpfProcessSource
                eb = EbpfProcessSource(enable=True, hybrid_mode=True)
                if getattr(eb, 'available', False):
                    source = eb
                    # Developer log: eBPF hybrid source enabled
                    print("[eBPF] EbpfProcessSource 有効化（ハイブリッドモード）")
                else:
                    # Attempt to extract error details from lifecycle events
                    error_details = ""
                    try:
                        events = eb.drain_lifecycle_events()
                        for event in events:
                            if event.details and ('error' in event.details or 'warning' in event.details):
                                error_msg = event.details.get('error') or event.details.get('warning')
                                error_details = f" - reason: {error_msg}"
                                break
                    except:
                        pass
                    # Developer log: fallback to psutil when eBPF unavailable
                    print(f"[eBPF] 利用不可のため psutil にフォールバック{error_details}")
            except Exception as e:
                # Developer log: eBPF initialization failed; fall back to psutil
                print(f"[eBPF] 初期化失敗: {e} -> psutil フォールバック")
        self.process_manager = ProcessManager(max_processes=max_processes, source=source)
        self.fishes: Dict[int, Fish] = {}  # PID -> Fish

    # Process limit and sort configuration
        limit_str = os.environ.get("AQUARIUM_LIMIT")
        self.process_limit = int(limit_str) if limit_str else None
        self.sort_by = os.environ.get("AQUARIUM_SORT_BY", "cpu")
        self.sort_order = os.environ.get("AQUARIUM_SORT_ORDER", "desc")

    # Apply settings to ProcessManager
        if self.process_limit is not None:
            self.process_manager.set_process_limit(self.process_limit)
        self.process_manager.set_sort_config(self.sort_by, self.sort_order)

    # Dynamic world size calculation based on process limit
        self.world_size = self._calculate_world_size(self.process_limit)
        # Developer log: world size for visualization
        print(f"🌍 ワールドサイズ: {self.world_size} (プロセス制限: {self.process_limit})")

        # Performance optimizations (relaxed limits)
        self.surface_cache = {}  # drawing cache
        self.background_cache = None  # background cache
        self.last_process_update = 0
        self.process_update_interval = 1.0  # process update interval shortened to 1s (was 2s)
        self.last_cache_cleanup = time.time()
        self.cache_cleanup_interval = 60.0  # cache cleanup interval extended to 1 minute

    # Dynamic performance adjustments
        self.performance_monitor = {
            'fps_history': [],
            'fish_count_history': [],
            'last_adjustment': 0,
            'adaptive_particle_count': 50,
            'adaptive_fish_update_interval': 1
        }
        self._neighbor_cell_size = 120  # grid cell size for neighbor searches (pixels)

        # UI state
        self.selected_fish: Optional[Fish] = None

        # Camera system (free scroll & zoom)
        self.camera_x = 0.0  # camera X in world coordinates
        self.camera_y = 0.0  # camera Y in world coordinates
        self.zoom_level = 1.0  # zoom level (1.0 = 1x)
        self.min_zoom = 0.1   # minimum zoom
        self.max_zoom = 5.0   # maximum zoom

        # Mouse interaction
        self.is_dragging = False
        self.drag_start_x = 0
        self.drag_start_y = 0
        self.last_mouse_x = 0
        self.last_mouse_y = 0

        # Follow/targeting features
        self.follow_target: Optional[Fish] = None
        # Camera mode: 0=auto-center, 1=follow selected fish, 2=manual
        self.camera_mode = 0

        # Japanese font handling and dynamic scaling
        self._preferred_font_name: Optional[str] = None
        self._preferred_font_path: Optional[str] = None
        self._font_cache: Dict[int, pygame.font.Font] = {}
        self.font_scale = 1.0
        self._update_font_scale()
        self.font = self._get_japanese_font(int(20 * self.font_scale))  # smaller: 24->20
        self.small_font = self._get_japanese_font(int(14 * self.font_scale))  # smaller: 18->14
        self.bubble_font = self._get_japanese_font(self._determine_bubble_font_size())  # font for IPC speech bubbles

        # Background and effects (adaptive particle count)
        self.background_particles = []
        self.particle_count = self.performance_monitor['adaptive_particle_count']
        if not self.headless:
            self.init_background_particles()

        # Process-related statistics
        self.total_processes = 0
        self.total_memory = 0.0
        self.avg_cpu = 0.0
        self.total_threads = 0

        # IPC connection information
        self.ipc_connections = []
        self.ipc_update_timer = 0
        self.ipc_update_interval = 30  # more frequent IPC updates (seconds)

        # Flocking formation based on communication history
        self.communication_history = {}  # {(pid1, pid2): [timestamps]}
        self.history_cleanup_timer = 0
        self.history_cleanup_interval = 300  # cleanup interval in seconds
        self.communication_window = 60.0  # keep 60 seconds of communication history

        # Debug display flags
        self.show_debug = False  # debug display off by default
        self.show_ipc = False   # IPC visualization off by default
        self.highlight_schools = False  # highlight schools (dim isolated processes)
        self.debug_text_lines = []

        # Highlighted communication partners
        self.highlighted_partners = []  # list of PIDs to highlight as partners

        # Fullscreen management
        self.original_size = (width, height)
        self._windowed_size = (width, height)

        # Runtime state
        self.running = True
        if self.headless:
            # Developer log: running in headless mode — only statistics will be printed
            print("[Headless] Running in headless mode. Only statistics will be printed. Press Ctrl+C to exit.")

    def _calculate_world_size(self, process_limit: int = None) -> int:
        """Dynamically calculate the world size based on the process limit."""
        # Minimum base size: use display dimensions
        min_size = max(self.width, self.height)

        if process_limit is None:
            # When unlimited, use the actual process count and apply the same
            # formula used for limits >= 201.
            current_process_count = 0
            if hasattr(self, 'fishes') and self.fishes:
                current_process_count = len(self.fishes)
            elif hasattr(self, 'total_processes') and self.total_processes > 0:
                current_process_count = self.total_processes

            if current_process_count == 0:
                # During initialization or when there are no fishes, default to 3072
                return max(min_size, 3072)
            else:
                # Apply same formula as for limits >= 201 using actual process count
                effective_limit = max(201, current_process_count)
                return max(min_size, int(3072 + (effective_limit - 200) * 6))

        # World size calculation based on process_limit
        # Few processes: compact world
        # Many processes: larger world
        if process_limit <= 10:
            return min_size                              # Use display size
        elif process_limit <= 30:
            return max(min_size, 1024)                   # Small world
        elif process_limit <= 60:
            return max(min_size, 1536)                   # Small-medium world
        elif process_limit <= 100:
            return max(min_size, 2048)                   # Medium world
        elif process_limit <= 200:
            return max(min_size, 3072)                   # Large world
        else:
            return max(min_size, int(3072 + (process_limit - 200) * 6))  # Extra large

    def _update_world_size(self, new_limit: int = None):
        """Update the world size and adjust existing fish settings accordingly."""
        old_world_size = self.world_size
        new_world_size = self._calculate_world_size(new_limit)

        if old_world_size != new_world_size:
            self.world_size = new_world_size
            print(f"🌍 ワールドサイズ更新: {old_world_size} → {new_world_size}")

            # Update existing fishes' world size
            scale_factor = new_world_size / old_world_size
            for fish in self.fishes.values():
                fish.world_size = new_world_size

                # Adjust positions for fishes outside the new bounds
                if abs(fish.x) > new_world_size:
                    fish.x = fish.x * scale_factor
                if abs(fish.y) > new_world_size:
                    fish.y = fish.y * scale_factor

                # Adjust target positions as well
                if hasattr(fish, 'target_x') and abs(fish.target_x) > new_world_size:
                    fish.target_x = fish.target_x * scale_factor
                if hasattr(fish, 'target_y') and abs(fish.target_y) > new_world_size:
                    fish.target_y = fish.target_y * scale_factor

    def init_background_particles(self):
        """Initialize background bubble particles (adaptive)."""
        self.background_particles = []  # clear existing particles

        # Use adaptive particle count
        base_count = min(100, int(self.width * self.height / 15000))  # Base count depending on screen size
        particle_count = min(base_count, self.performance_monitor['adaptive_particle_count'])

        for _ in range(particle_count):
            particle = {
                'x': random.uniform(0, self.width),
                'y': random.uniform(0, self.height),
                'size': random.uniform(2, 8),
                'speed': random.uniform(0.5, 2.0),
                'alpha': random.randint(30, 80)
            }
            self.background_particles.append(particle)

        # Clear background cache (handle size changes)
        self.background_cache = None

    def update_background_particles(self):
        """Update background particles positions."""
        for particle in self.background_particles:
            particle['y'] -= particle['speed']

            # If the particle goes above the top of the screen, respawn at the bottom
            if particle['y'] < -10:
                particle['y'] = self.height + 10
                particle['x'] = random.uniform(0, self.width)

    def draw_background(self):
        """Draw background using a cached surface for efficiency."""
        # Create background cache if missing or size changed
        if self.background_cache is None or self.background_cache.get_size() != (self.width, self.height):
            self._create_background_cache()

        # Draw the cached background surface
        self.screen.blit(self.background_cache, (0, 0))

        # Dynamic bubble particles (adaptive count)
        particle_count = min(len(self.background_particles), self.performance_monitor['adaptive_particle_count'])

        for i, particle in enumerate(self.background_particles[:particle_count]):
            color = (100, 150, 200, particle['alpha'])
            temp_surface = pygame.Surface((particle['size'] * 2, particle['size'] * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp_surface, color,
                             (particle['size'], particle['size']),
                             int(particle['size']))
            self.screen.blit(temp_surface,
                           (particle['x'] - particle['size'],
                            particle['y'] - particle['size']))

    # ===== Camera system =====
    def world_to_screen(self, world_x: float, world_y: float) -> Tuple[int, int]:
        """Convert world coordinates to screen coordinates."""
        screen_x = (world_x - self.camera_x) * self.zoom_level + self.width // 2
        screen_y = (world_y - self.camera_y) * self.zoom_level + self.height // 2
        return (int(screen_x), int(screen_y))

    def screen_to_world(self, screen_x: int, screen_y: int) -> Tuple[float, float]:
        """Convert screen coordinates to world coordinates."""
        world_x = (screen_x - self.width // 2) / self.zoom_level + self.camera_x
        world_y = (screen_y - self.height // 2) / self.zoom_level + self.camera_y
        return (world_x, world_y)

    def is_visible(self, world_x: float, world_y: float, margin: float = 100) -> bool:
        """Check whether an object is visible on screen (with margin)."""
        screen_x, screen_y = self.world_to_screen(world_x, world_y)
        return (-margin <= screen_x <= self.width + margin and
                -margin <= screen_y <= self.height + margin)

    def update_camera(self):
        """Update camera position (auto-centering, follow modes, etc.)."""
        if self.camera_mode == 0:
            # Auto-centering: track the centroid of all fishes
            if self.fishes:
                center_x = sum(fish.x for fish in self.fishes.values()) / len(self.fishes)
                center_y = sum(fish.y for fish in self.fishes.values()) / len(self.fishes)

                # ゆっくりとした自動センタリング
                lerp_factor = 0.01
                self.camera_x += (center_x - self.camera_x) * lerp_factor
                self.camera_y += (center_y - self.camera_y) * lerp_factor
        elif self.camera_mode == 1:
            # Selected-fish follow mode: automatically follow selected_fish
            if self.selected_fish and self.selected_fish in self.fishes.values():
                # Keep the selected fish near the screen center
                target_x = self.selected_fish.x
                target_y = self.selected_fish.y

                # Smooth follow using linear interpolation
                lerp_factor = 0.08  # slightly faster follow
                self.camera_x += (target_x - self.camera_x) * lerp_factor
                self.camera_y += (target_y - self.camera_y) * lerp_factor
        # camera_mode == 2 の場合は何もしない（手動制御のみ）

    def _create_background_cache(self):
        """Create the background cache surface."""
        self.background_cache = pygame.Surface((self.width, self.height))

    # Deep-sea gradient background
        for y in range(self.height):
            # Top is darker blue, bottom approaches near-black blue
            intensity = 1.0 - (y / self.height)
            blue_intensity = int(20 + intensity * 30)
            color = (0, 0, blue_intensity)
            pygame.draw.line(self.background_cache, color, (0, y), (self.width, y))

    def update_process_data(self):
        """Update process information from the ProcessManager and sync fishes.

        This polls the process manager, updates statistics, creates Fish
        instances for newly discovered processes, and handles lifecycle
        transitions (spawn/exec/exit)."""
        current_time = time.time()

        # Throttle process updates to configured interval
        if current_time - self.last_process_update < self.process_update_interval:
            return

        self.last_process_update = current_time

        # Refresh data from ProcessManager
        self.process_manager.update()

        # Obtain current process snapshot
        process_data = self.process_manager.processes

        # Update aggregate statistics
        self.total_processes = len(process_data)
        self.total_memory = sum(proc.memory_percent for proc in process_data.values())
        self.avg_cpu = sum(proc.cpu_percent for proc in process_data.values()) / max(1, len(process_data))
        self.total_threads = sum(proc.num_threads for proc in process_data.values())

        # If unlimited, adjust world size dynamically
        if self.process_limit is None:
            self._update_world_size(None)

        # Create Fish objects for newly discovered processes (when not present)
        for pid, proc in process_data.items():
            if pid not in self.fishes:
                # Temporarily we could lift limits to display more processes.
                # max_fish = min(self.process_manager.max_processes, 150)
                # if len(self.fishes) >= max_fish:
                #     self._remove_oldest_fish()

                # Spread new fishes across a larger radius to avoid clumping
                angle = random.uniform(0, 2 * math.pi)
                distance = random.uniform(100, min(self.world_size * 0.6, 600))  # within 60% of world radius
                x = distance * math.cos(angle)
                y = distance * math.sin(angle)

                fish = Fish(pid, proc.name, x, y, self.world_size)
                self.fishes[pid] = fish

                # Spawn logging (may be suppressed at low quality)
                if not self._suppress_spawn_logs:
                    # Developer log: new process observed
                    print(f"🐟 新しいプロセス誕生: PID {pid} ({proc.name})")
                elif "spawn_logs_suppressed" not in self._quality_message_shown:
                    # Developer log: suppress spawn logs in high-load mode
                    print("🐟 新規プロセス発生ログは高負荷モードのため抑制されています。")
                    self._quality_message_shown.add("spawn_logs_suppressed")

                # If parent exists, trigger a fork effect and position child near parent
                if proc.ppid in self.fishes:
                    parent_fish = self.fishes[proc.ppid]
                    parent_fish.set_fork_event()
                    # Place child near parent
                    fish.x = parent_fish.x + random.uniform(-50, 50)
                    fish.y = parent_fish.y + random.uniform(-50, 50)
                    print(f"👨‍👦 親子関係検出: 親PID {proc.ppid} → 子PID {pid}")

    # exec detection and effects
        exec_processes = self.process_manager.detect_exec()
        for proc in exec_processes:
            if proc.pid in self.fishes:
                self.fishes[proc.pid].set_exec_event()

    # Configure schooling behavior
        self._update_schooling_behavior()

    # Update IPC connections
        self._update_ipc_connections()

    # Update communication history and form schools
        self._update_communication_history()

    # Apply IPC attraction forces
        self._apply_ipc_attraction()

    # Update existing Fish data
        processes_marked_for_death = []
        for pid, fish in self.fishes.items():
            if pid in process_data:
                proc = process_data[pid]
                fish.update_process_data(
                    proc.memory_percent,
                    proc.cpu_percent,
                    proc.num_threads,
                    proc.ppid
                )
            else:
                # When the process disappears
                # print(f"🔥 Detected process disappearance: PID {pid} ({fish.process_name}) - marking for death")
                fish.set_death_event()
                processes_marked_for_death.append(pid)

        # if processes_marked_for_death:
        #     print(f"📊 死亡フラグ設定済みプロセス数: {len(processes_marked_for_death)}")

    # Remove fishes that have finished dying
        dead_pids = []
        dying_fish_details = []
        for pid, fish in self.fishes.items():
            if fish.is_dying:
                dying_fish_details.append(f"PID {pid}: {fish.death_progress:.2f}")
                if fish.death_progress >= 1.0:
                    dead_pids.append(pid)
                    # print(f"💀 魚の死亡処理完了: PID {pid} ({fish.process_name}) - 削除対象")

    # Periodically print progress of dying fishes (up to 5)
        # if dying_fish_details:
        #     print(f"⏰ 死亡進行中: {', '.join(dying_fish_details[:5])}{'...' if len(dying_fish_details) > 5 else ''}")

        # print(f"📊 現在の魚数: {len(self.fishes)}, 削除対象: {len(dead_pids)}, 総プロセス数: {len(process_data)}")

        for pid in dead_pids:
            fish_name = self.fishes[pid].process_name
            # If the followed/selected fish is removed, switch camera to auto-center
            if self.selected_fish and self.selected_fish.pid == pid:
                if self.camera_mode == 1:  # If in follow-selected-fish mode
                    self.camera_mode = 0  # Switch to auto-centering
                    # Developer log: follow target removed; switch to auto-centering
                    print(f"📹 追従対象の魚が削除されました。自動センタリングモードに切り替えます。")
                self.selected_fish = None
            if self.follow_target and self.follow_target.pid == pid:
                self.follow_target = None
            del self.fishes[pid]
            # print(f"🗑️ 魚を削除完了: PID {pid} ({fish_name})")

        # if dead_pids:
        #     print(f"📊 削除後の魚数: {len(self.fishes)}")

    def _remove_oldest_fish(self):
        """Remove the oldest fish to maintain performance"""
        if not self.fishes:
            return

        # Find the oldest fish by creation time
        oldest_fish = min(self.fishes.values(), key=lambda f: f.creation_time)
        # print(f"🗑️ 古い魚を削除: PID {oldest_fish.pid} ({oldest_fish.process_name})")
        del self.fishes[oldest_fish.pid]

    def _update_schooling_behavior(self):
        """Update schooling behavior."""
        # Gather related process groups and form schools
        processed_pids = set()

        # For each fish, find related processes and form a school if applicable
        for pid, fish in self.fishes.items():
            if pid in processed_pids:
                continue

            # Get related processes (by parent/child / proximity in the process graph)
            related_processes = self.process_manager.get_related_processes(pid, max_distance=2)
            related_pids = [p.pid for p in related_processes if p.pid in self.fishes]

            if len(related_pids) > 1:
                # Form a school
                # Choose a leader (e.g. oldest or parent). Here we simply pick the smallest PID.
                leader_pid = min(related_pids)

                for related_pid in related_pids:
                    if related_pid in self.fishes:
                        is_leader = (related_pid == leader_pid)
                        self.fishes[related_pid].set_school_members(related_pids, is_leader)
                        processed_pids.add(related_pid)

        # Form schools for isolated processes (same-name grouping)
        self._form_isolated_process_schools(processed_pids)

    def _form_isolated_process_schools(self, processed_pids: set):
        """Form schools for same-named processes and detect truly isolated processes."""
        # Collect processes that are not yet assigned to any school
        unprocessed_pids = []
        for pid, fish in self.fishes.items():
            if pid not in processed_pids:
                unprocessed_pids.append(pid)

        # Group processes by base name to identify real schools
        if len(unprocessed_pids) >= 2:
            name_groups = {}
            for pid in unprocessed_pids:
                fish = self.fishes[pid]
                base_name = fish.name.split()[0] if fish.name else "unknown"  # Extract base process name
                if base_name not in name_groups:
                    name_groups[base_name] = []
                name_groups[base_name].append(pid)

            # For each name group, form a school (groups with 2+ members are considered real schools)
            truly_isolated_pids = []
            for base_name, group_pids in name_groups.items():
                if len(group_pids) >= 2:
                    # Form a real school for processes that share the same name
                    leader_pid = min(group_pids)  # Choose the smallest PID as leader
                    for pid in group_pids:
                        if pid in self.fishes:
                            is_leader = (pid == leader_pid)
                            self.fishes[pid].set_school_members(group_pids, is_leader)
                            self.fishes[pid].is_isolated = False  # No longer considered isolated
                            self.fishes[pid].is_isolated_school = False  # Not an isolated-school
                            processed_pids.add(pid)
                else:
                    # Single process -> truly isolated
                    for pid in group_pids:
                        if pid in self.fishes:
                            truly_isolated_pids.append(pid)
                            self.fishes[pid].is_isolated = True  # Mark as truly isolated
                            self.fishes[pid].is_isolated_school = False  # Not part of a school

            # Consolidate truly isolated processes into a special "isolates" school
            if len(truly_isolated_pids) >= 2:
                # If multiple truly isolated processes exist, merge them into an "isolates" school
                leader_pid = min(truly_isolated_pids)  # Choose smallest PID as leader
                for pid in truly_isolated_pids:
                    if pid in self.fishes:
                        is_leader = (pid == leader_pid)
                        self.fishes[pid].set_school_members(truly_isolated_pids, is_leader)
                        self.fishes[pid].is_isolated = True  # Preserve isolated attribute
                        self.fishes[pid].is_isolated_school = True  # Flag as an isolated-school
                        processed_pids.add(pid)
                # print(f"🏝️ Formed isolates school: {len(truly_isolated_pids)} members")
            elif len(truly_isolated_pids) == 1:
                # Single truly isolated process (only one)
                pid = truly_isolated_pids[0]
                if pid in self.fishes:
                    self.fishes[pid].is_isolated = True
                    self.fishes[pid].is_isolated_school = False
                # print("🏝️ Single truly isolated process")
        else:
            # If 0 or 1 unprocessed processes remain, they are truly isolated
            for pid in unprocessed_pids:
                if pid in self.fishes:
                    self.fishes[pid].is_isolated = True
                    self.fishes[pid].is_isolated_school = False

    def handle_mouse_click(self, pos: Tuple[int, int]):
        """Handle mouse clicks: select fish or detect bubble clicks."""
        x, y = pos
        world_x, world_y = self.screen_to_world(x, y)

    # First check whether a speech bubble was clicked (screen coordinates)
        for fish in self.fishes.values():
            if fish.bubble_rect and fish.is_talking:
                bx, by, bw, bh = fish.bubble_rect
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    # If the bubble was clicked, highlight communication partners
                    self._highlight_communication_partners(fish)
                    return

    # If no bubble was clicked, perform normal fish selection
        self.selected_fish = None
        self.highlighted_partners = []  # 通信相手のハイライトをクリア

    # Select the nearest fish (world-coordinate distance)
        min_distance = float('inf')
        for fish in self.fishes.values():
            distance = math.sqrt((fish.x - world_x)**2 + (fish.y - world_y)**2)
            if distance < (fish.current_size + 10) / self.zoom_level and distance < min_distance:
                min_distance = distance
                self.selected_fish = fish

    def select_follow_target(self, pos: Tuple[int, int]):
        """Select a follow target with right-click."""
        x, y = pos
        world_x, world_y = self.screen_to_world(x, y)

        # 最も近いFishを追従対象に設定
        min_distance = float('inf')
        target_fish = None

        for fish in self.fishes.values():
            distance = math.sqrt((fish.x - world_x)**2 + (fish.y - world_y)**2)
            if distance < fish.current_size + 20 and distance < min_distance:
                min_distance = distance
                target_fish = fish

        if target_fish:
            self.follow_target = target_fish
            self.auto_center = False
            print(f"追従対象: PID {target_fish.pid} ({target_fish.process_name})")
        else:
            self.follow_target = None
            print("追従対象を解除しました")

    def _highlight_communication_partners(self, fish):
        """Highlight communication partners of the given fish."""
        self.highlighted_partners = fish.talk_partners.copy()

    # Print partner information
        partner_names = []
        for partner_pid in fish.talk_partners:
            if partner_pid in self.fishes:
                partner_fish = self.fishes[partner_pid]
                partner_names.append(f"{partner_fish.name} (PID:{partner_pid})")

        if partner_names:
            print(f"プロセス {fish.name} (PID:{fish.pid}) の通信相手:")
            for name in partner_names:
                print(f"  -> {name}")
        else:
            print(f"プロセス {fish.name} (PID:{fish.pid}) の通信相手が見つかりません")

    def draw_ui(self):
        """UI情報の描画"""
        if self.headless:
            return  # ヘッドレスではUI描画をスキップ

        # UI表示モードの確認
        if not hasattr(self, 'ui_mode'):
            self.ui_mode = 0  # デフォルトはフル表示

        # 最小表示モード(2)の場合は何も描画しない
        if self.ui_mode == 2:
            return

        current_fps = self.clock.get_fps()

        # 統計情報（パフォーマンス情報を含む）
        if self.enable_adaptive_quality:
            quality_label = f"{self.render_quality} (自動)"
        else:
            quality_label = "full (固定)"

        # プロセス制限とソート情報を追加
        limit_str = "無制限" if self.process_limit is None else str(self.process_limit)

        if self.ui_mode == 0:  # フル表示
            stats_lines = [
                f"総プロセス数: {self.total_processes}",
                f"表示中の魚: {len(self.fishes)}",
                f"制限: {limit_str}",
                f"総メモリ使用率: {self.total_memory:.1f}%",
                f"平均CPU使用率: {self.avg_cpu:.2f}%",
                f"総スレッド数: {self.total_threads}",
                f"FPS: {current_fps:.1f}",
                f"描画品質: {quality_label}",
            ]
        else:  # 簡素表示
            stats_lines = [
                f"プロセス: {self.total_processes} | 魚: {len(self.fishes)}",
                f"FPS: {current_fps:.1f} | 制限: {limit_str}",
            ]

        if self.enable_adaptive_quality:
            reduced_threshold, minimal_threshold = self._quality_thresholds
            if reduced_threshold is not None and minimal_threshold is not None:
                stats_lines.append(f"品質閾値: 簡易≦{reduced_threshold:.1f}fps／最小≦{minimal_threshold:.1f}fps")

        field_names = {"cpu": "CPU", "memory": "メモリ", "name": "名前", "pid": "PID"}
        order_symbol = "↓" if self.sort_order == "desc" else "↑"
        stats_lines.append(f"ソート: {field_names.get(self.sort_by, self.sort_by)} {order_symbol}")

        # # Retinaディスプレイ情報
        # if hasattr(self, 'retina_info') and self.retina_info['is_retina']:
        #     stats_lines.append(f"Retina: {self.retina_info['scale_factor']:.1f}x")

        # Camera information
        stats_lines.append(f"カメラ座標: ({self.camera_x:.0f}, {self.camera_y:.0f})")
        stats_lines.append(f"カメラズーム: {self.zoom_level:.2f}x")
        if self.camera_mode == 0:
            stats_lines.append("モード: 自動センタリング")
        elif self.camera_mode == 1:
            if self.selected_fish:
                stats_lines.append(f"カメラモード: 追従 (PID {self.selected_fish.pid})")
            else:
                stats_lines.append("カメラモード: 追従 (魚未選択)")
        else:  # camera_mode == 2
            stats_lines.append("カメラモード: 手動制御")

    # Background panel
        panel_padding_x = 10
        panel_padding_y = 10
        font_linesize = self.small_font.get_linesize()
        line_height = max(int(font_linesize * 1.15), font_linesize)
        max_text_width = 0
        for line in stats_lines:
            text_width, _ = self.small_font.size(line)
            if text_width > max_text_width:
                max_text_width = text_width

        panel_width = max(280, max_text_width + panel_padding_x * 2)
        panel_height = len(stats_lines) * line_height + panel_padding_y * 2
        panel_surface = pygame.Surface((panel_width, panel_height), pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 128))
        panel_x, panel_y = 10, 10
        self.screen.blit(panel_surface, (panel_x, panel_y))

        # Statistics text
        for i, line in enumerate(stats_lines):
            color = (255, 100, 100) if current_fps < self.fps * 0.7 else (255, 255, 255)  # 低FPS時は赤
            text_surface = self._render_text(line, self.small_font, color)
            text_x = panel_x + panel_padding_x
            text_y = panel_y + panel_padding_y + i * line_height
            self.screen.blit(text_surface, (text_x, text_y))

        # Selected fish detail panel (same style as the top-left panel) - full UI mode only
        if self.selected_fish and self.ui_mode == 0:
            info_lines = [
                f"選択されたプロセス:",
                f"PID: {self.selected_fish.pid}",
                f"名前: {self.selected_fish.name}",
                f"メモリ: {self.selected_fish.memory_percent:.2f}%",
                f"CPU: {self.selected_fish.cpu_percent:.2f}%",
                f"スレッド数: {self.selected_fish.thread_count}",
                f"年齢: {self.selected_fish.age}フレーム"
            ]

            # Dynamic sizing using the same approach as the top-left panel
            info_padding_x = 10
            info_padding_y = 10
            info_line_height = max(int(font_linesize * 1.15), font_linesize)
            max_info_width = 0
            for line in info_lines:
                text_width, _ = self.small_font.size(line)
                if text_width > max_info_width:
                    max_info_width = text_width

            info_panel_width = max(250, max_info_width + info_padding_x * 2)
            info_panel_height = len(info_lines) * info_line_height + info_padding_y * 2
            info_panel_surface = pygame.Surface((info_panel_width, info_panel_height), pygame.SRCALPHA)
            info_panel_surface.fill((0, 50, 100, 180))

            # Position in the top-right
            info_panel_x = self.width - info_panel_width - 10
            info_panel_y = 10
            self.screen.blit(info_panel_surface, (info_panel_x, info_panel_y))

            # Detail text lines
            for i, line in enumerate(info_lines):
                color = (255, 255, 255) if i == 0 else (200, 200, 200)
                text_surface = self._render_text(line, self.small_font, color)
                text_x = info_panel_x + info_padding_x
                text_y = info_panel_y + info_padding_y + i * info_line_height
                self.screen.blit(text_surface, (text_x, text_y))        # Operation hints - full UI mode only
        if self.ui_mode == 0:
            help_lines = [
                "操作:",
                "クリック:選択 C:カメラ R:リセット",
                "ホイール:ズーム 右ドラッグ:パン",
                "D:デバッグ I:IPC F:フルスクリーン",
                "L:制限 S:ソート O:順序",
                "T:UI表示 Q:群れ強調 ESC:終了"
            ]
        else:
            # In compact UI mode show only basic controls
            help_lines = [
                "基本操作:",
                "T:UI Q:群れ強調 ESC:終了"
            ]

    # Help panel (dynamic sizing, same style as top-left panel)
        help_padding_x = 10
        help_padding_y = 10
        help_line_height = max(int(font_linesize * 1.15), font_linesize)
        max_help_width = 0
        for line in help_lines:
            text_width, _ = self.small_font.size(line)
            if text_width > max_help_width:
                max_help_width = text_width

        help_panel_width = max(200, max_help_width + help_padding_x * 2)
        help_panel_height = len(help_lines) * help_line_height + help_padding_y * 2
        help_panel_surface = pygame.Surface((help_panel_width, help_panel_height), pygame.SRCALPHA)
        help_panel_surface.fill((0, 0, 0, 128))

        # 左下に配置
        help_panel_x = 10
        help_panel_y = self.height - help_panel_height - 10
        self.screen.blit(help_panel_surface, (help_panel_x, help_panel_y))

        # ヘルプテキスト
        for i, line in enumerate(help_lines):
            color = (255, 255, 150) if i == 0 else (200, 200, 200)
            text_surface = self._render_text(line, self.small_font, color)
            text_x = help_panel_x + help_padding_x
            text_y = help_panel_y + help_padding_y + i * help_line_height
            self.screen.blit(text_surface, (text_x, text_y))

    def draw_parent_child_connections(self):
        """親子関係の描画（淡い線で接続）"""
        for fish in self.fishes.values():
            if fish.parent_pid and fish.parent_pid in self.fishes:
                parent_fish = self.fishes[fish.parent_pid]

                # 可視判定（どちらかが画面内にある場合のみ描画）
                if self.is_visible(fish.x, fish.y, 50) or self.is_visible(parent_fish.x, parent_fish.y, 50):
                    # ワールド座標をスクリーン座標に変換
                    parent_screen_x, parent_screen_y = self.world_to_screen(parent_fish.x, parent_fish.y)
                    child_screen_x, child_screen_y = self.world_to_screen(fish.x, fish.y)

                    # 淡い線で接続
                    color = (100, 150, 200, 50)
                    temp_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
                    pygame.draw.line(temp_surface, color,
                                   (int(parent_screen_x), int(parent_screen_y)),
                                   (int(child_screen_x), int(child_screen_y)), 1)
                    self.screen.blit(temp_surface, (0, 0))

    def _update_ipc_connections(self):
        """IPC接続情報の更新"""
        self.ipc_update_timer += 1
        if self.ipc_update_timer >= self.ipc_update_interval:
            self.ipc_update_timer = 0
            self.ipc_connections = self.process_manager.detect_ipc_connections()

    def _apply_ipc_attraction(self):
        """IPC接続ペア間の吸引力を計算・適用"""
        # すべてのFishのIPC吸引力をリセット
        for fish in self.fishes.values():
            fish.ipc_attraction_x = 0.0
            fish.ipc_attraction_y = 0.0

        # IPC接続ペアに対して吸引力を適用
        for proc1, proc2 in self.ipc_connections:
            if proc1.pid in self.fishes and proc2.pid in self.fishes:
                fish1 = self.fishes[proc1.pid]
                fish2 = self.fishes[proc2.pid]

                # 距離を計算
                dx = fish2.x - fish1.x
                dy = fish2.y - fish1.y
                distance = math.sqrt(dx*dx + dy*dy)

                if distance > 5:  # 極端に近い場合は無視
                    # 吸引力の強さを距離に応じて調整（強化版）
                    attraction_strength = 0.008  # 基本の吸引力を4倍に増加
                    if distance < 80:  # 近い場合は適度に弱く
                        attraction_strength *= 0.6
                    elif distance > 250:  # 遠い場合はより強く
                        attraction_strength *= 3.0
                    elif distance > 150:  # 中距離も強化
                        attraction_strength *= 1.5

                    # 正規化された方向ベクトル
                    force_x = (dx / distance) * attraction_strength
                    force_y = (dy / distance) * attraction_strength

                    # 両方の魚に吸引力を適用
                    fish1.ipc_attraction_x += force_x
                    fish1.ipc_attraction_y += force_y
                    fish2.ipc_attraction_x -= force_x
                    fish2.ipc_attraction_y -= force_y

                    # 近距離で会話フラグをセット（距離を拡大）
                    if distance < 120:  # 120ピクセル以内で会話（範囲拡大）
                        fish1.is_talking = True
                        fish1.talk_timer = 60  # 1秒間会話
                        fish1.talk_message = "通信中..."
                        fish1.talk_partners = [proc2.pid]  # 通信相手を記録
                        fish2.is_talking = True
                        fish2.talk_timer = 60
                        fish2.talk_message = "データ送信"
                        fish2.talk_partners = [proc1.pid]  # 通信相手を記録

    def _update_communication_history(self):
        """通信履歴を更新し、履歴ベースの群れ形成を行う"""
        current_time = time.time()

        # 現在のIPC接続を履歴に追加
        for proc1, proc2 in self.ipc_connections:
            key = (min(proc1.pid, proc2.pid), max(proc1.pid, proc2.pid))
            if key not in self.communication_history:
                self.communication_history[key] = []
            self.communication_history[key].append(current_time)

        # 履歴のクリーンアップ
        self.history_cleanup_timer += 1
        if self.history_cleanup_timer >= self.history_cleanup_interval:
            self.history_cleanup_timer = 0
            cutoff_time = current_time - self.communication_window

            for key in list(self.communication_history.keys()):
                # 古いタイムスタンプを削除
                self.communication_history[key] = [
                    t for t in self.communication_history[key] if t > cutoff_time
                ]
                # Remove empty entries
                if not self.communication_history[key]:
                    del self.communication_history[key]

    # Promote frequently communicating process pairs into schools
        self._form_communication_based_schools(current_time)

    def _form_communication_based_schools(self, current_time: float):
        """Dynamically form schools based on communication history."""
        cutoff_time = current_time - self.communication_window

        for (pid1, pid2), timestamps in self.communication_history.items():
            recent_communications = [t for t in timestamps if t > cutoff_time]

            # Consider a school relationship if 3+ communications occurred in the past window
            if len(recent_communications) >= 3:
                if pid1 in self.fishes and pid2 in self.fishes:
                    fish1, fish2 = self.fishes[pid1], self.fishes[pid2]

                    # 既存の群れがない場合のみ新しい群れを形成
                    if not fish1.school_members and not fish2.school_members:
                        # 小さな通信ベースの群れを形成
                        comm_group = [pid1, pid2]
                        fish1.set_school_members(comm_group, is_leader=True)
                        fish2.set_school_members(comm_group, is_leader=False)

    def draw_ipc_connections(self):
        """Draw IPC connections as pulsing network-like lines."""
        if self.headless or not self.show_ipc:
            return

        connection_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        for proc1, proc2 in self.ipc_connections:
            if proc1.pid in self.fishes and proc2.pid in self.fishes:
                fish1 = self.fishes[proc1.pid]
                fish2 = self.fishes[proc2.pid]

                # Visibility check: draw only if either fish is on-screen
                if self.is_visible(fish1.x, fish1.y, 100) or self.is_visible(fish2.x, fish2.y, 100):
                    # ワールド座標での距離チェック
                    distance = math.sqrt((fish1.x - fish2.x)**2 + (fish1.y - fish2.y)**2)
                    if distance < 400 / self.zoom_level:  # Adjust distance threshold by zoom level
                        # Pulsing line effect
                        pulse = math.sin(time.time() * 3) * 0.3 + 0.7
                        alpha = int(80 * pulse)

                        # Change line color according to CPU usage
                        cpu_intensity = (fish1.cpu_percent + fish2.cpu_percent) / 200.0
                        red = int(100 + cpu_intensity * 155)
                        green = int(150 - cpu_intensity * 50)
                        blue = int(200 - cpu_intensity * 100)

                        # 値の範囲を確実に0-255に制限
                        red = max(0, min(255, red))
                        green = max(0, min(255, green))
                        blue = max(0, min(255, blue))

                        color = (red, green, blue)  # pygame.draw.linesは3要素のRGBのみサポート

                        # Compute a midpoint in world coordinates to curve the line
                        mid_world_x = (fish1.x + fish2.x) / 2 + math.sin(time.time() * 2) * 20
                        mid_world_y = (fish1.y + fish2.y) / 2 + math.cos(time.time() * 2) * 20

                        # Calculate quadratic bezier in world coordinates then convert to screen
                        steps = 10
                        points = []
                        for i in range(steps + 1):
                            t = i / steps
                            # 二次ベジェ曲線（ワールド座標）
                            world_x = (1-t)**2 * fish1.x + 2*(1-t)*t * mid_world_x + t**2 * fish2.x
                            world_y = (1-t)**2 * fish1.y + 2*(1-t)*t * mid_world_y + t**2 * fish2.y
                            # スクリーン座標に変換
                            screen_x, screen_y = self.world_to_screen(world_x, world_y)
                            points.append((screen_x, screen_y))

                        if len(points) > 1:
                            # アルファ効果を適用するため、一時的なサーフェスを使用
                            temp_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
                            pygame.draw.lines(temp_surface, (*color, alpha), False, points, 2)
                            connection_surface.blit(temp_surface, (0, 0))

        self.screen.blit(connection_surface, (0, 0))

    def handle_events(self):
        """Process input and window events."""
        if self.headless:
            return
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif self.use_gpu and self._windowevent_type and event.type == self._windowevent_type:
                if event.event in tuple(x for x in (self._windowevent_size_changed, self._windowevent_resized) if x is not None):
                    new_width, new_height = event.data1, event.data2
                    if (new_width, new_height) != (self.width, self.height):
                        self.width, self.height = new_width, new_height
                        self._update_gpu_render_size(self.width, self.height)
                        self._after_display_resize()
                        if not self.fullscreen:
                            self._windowed_size = (self.width, self.height)
                        print(f"🪟 GPUウィンドウサイズ変更: {self.width}x{self.height}")
                elif self._windowevent_close is not None and event.event == self._windowevent_close:
                    self.running = False
            elif self.use_gpu and event.type == pygame.VIDEORESIZE and not self._windowevent_type:
                # pygame-ce without WINDOWEVENT constants may still emit legacy VIDEORESIZE events
                new_width, new_height = event.w, event.h
                if (new_width, new_height) != (self.width, self.height):
                    self.width, self.height = new_width, new_height
                    self._update_gpu_render_size(self.width, self.height)
                    self._after_display_resize()
                    if not self.fullscreen:
                        self._windowed_size = (self.width, self.height)
                    print(f"🪟 GPUウィンドウサイズ変更(VIDEORESIZE): {self.width}x{self.height}")
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_d:
                    self.show_debug = not self.show_debug
                elif event.key == pygame.K_i:
                    self.show_ipc = not self.show_ipc
                    # Toggle IPC visualization (developer log)
                    print(f"IPC可視化: {'オン' if self.show_ipc else 'オフ'}")
                elif event.key == pygame.K_t:
                    # Toggle UI display (T key)
                    self._toggle_ui_display()
                elif event.key == pygame.K_q:
                    # Toggle highlight schools (Q key)
                    self.highlight_schools = not self.highlight_schools
                    # Developer log for school highlighting
                    print(f"🐠 群れ強調表示: {'オン (孤立プロセス半透明)' if self.highlight_schools else 'オフ'}")
                elif event.key == pygame.K_f or event.key == pygame.K_F11:
                    self.toggle_fullscreen()
                elif event.key == pygame.K_l:
                    # プロセス制限の切り替え
                    self._cycle_process_limit()
                elif event.key == pygame.K_s:
                    # ソートフィールドの切り替え
                    self._cycle_sort_field()
                elif event.key == pygame.K_o:
                    # ソート順序の切り替え
                    self._toggle_sort_order()
                elif event.key == pygame.K_c:
                    # Cycle camera mode
                    self.camera_mode = (self.camera_mode + 1) % 3
                    if self.camera_mode == 0:
                        print("📹 カメラモード: 自動センタリング")
                    elif self.camera_mode == 1:
                        if self.selected_fish:
                            print(f"📹 カメラモード: 選択魚追従 (PID {self.selected_fish.pid} - {self.selected_fish.process_name})")
                        else:
                            print("📹 カメラモード: 選択魚追従 (魚未選択)")
                    else:  # camera_mode == 2
                        print("📹 カメラモード: 手動制御")
                elif event.key == pygame.K_r:
                    # カメラリセット
                    self.camera_x = 0.0
                    self.camera_y = 0.0
                    self.zoom_level = 1.0
                    self.follow_target = None
                    self.camera_mode = 0  # reset to auto-centering mode
                    print("カメラをリセットしました（自動センタリングモード）")
            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # 左クリック
                    self.is_dragging = True
                    self.drag_start_x, self.drag_start_y = event.pos
                    self.last_mouse_x, self.last_mouse_y = event.pos
                    # 魚の選択も行う
                    self.handle_mouse_click(event.pos)
                elif event.button == 3:  # 右クリック - 追従対象選択
                    self.select_follow_target(event.pos)
            elif event.type == pygame.MOUSEBUTTONUP:
                if event.button == 1:  # 左クリック解除
                    self.is_dragging = False
            elif event.type == pygame.MOUSEMOTION:
                if self.is_dragging:
                    # ドラッグによるカメラ移動
                    dx = event.pos[0] - self.last_mouse_x
                    dy = event.pos[1] - self.last_mouse_y
                    self.camera_x -= dx / self.zoom_level
                    self.camera_y -= dy / self.zoom_level
                    self.last_mouse_x, self.last_mouse_y = event.pos
                    # ドラッグ中は追従を無効化
                    self.follow_target = None
                    self.auto_center = False
            elif event.type == pygame.MOUSEWHEEL:
                # マウスホイールによるズーム
                zoom_factor = 1.1 if event.y > 0 else 0.9
                old_zoom = self.zoom_level
                self.zoom_level = max(self.min_zoom, min(self.max_zoom, self.zoom_level * zoom_factor))

                # ズーム中心をマウス位置に設定
                mouse_x, mouse_y = pygame.mouse.get_pos()
                world_x, world_y = self.screen_to_world(mouse_x, mouse_y)
                # ズーム後に同じワールド座標がマウス位置に来るようにカメラを調整
                new_screen_x, new_screen_y = self.world_to_screen(world_x, world_y)
                self.camera_x += (new_screen_x - mouse_x) / self.zoom_level
                self.camera_y += (new_screen_y - mouse_y) / self.zoom_level

    def toggle_fullscreen(self):
        """フルスクリーンモードの切り替え"""
        target_state = not self.fullscreen
        previous_state = self.fullscreen
        if target_state:
            self._windowed_size = (self.width, self.height)
        self.fullscreen = target_state

        if self.use_gpu and self.gpu_window is not None:
            if not self._apply_gpu_fullscreen_state(target_state):
                self.fullscreen = previous_state
            return

        if self.fullscreen:
            # フルスクリーンモードに切り替え
            try:
                # 最適な解像度を取得
                self.width, self.height = self.get_best_fullscreen_resolution()
                print(f"📱 選択された解像度: {self.width}x{self.height}")

                # フルスクリーンモードを設定
                self.screen = pygame.display.set_mode((self.width, self.height), pygame.FULLSCREEN)

                # 実際に設定されたサイズを確認・更新
                actual_width = self.screen.get_width()
                actual_height = self.screen.get_height()

                if actual_width != self.width or actual_height != self.height:
                    print(f"⚠️ 解像度が調整されました: {self.width}x{self.height} → {actual_width}x{actual_height}")
                    self.width = actual_width
                    self.height = actual_height

                print(f"🖥️ フルスクリーンモード適用: {self.width}x{self.height}")

            except Exception as e:
                print(f"❌ フルスクリーン設定エラー: {e}")
                # エラー時は(0,0)指定でシステムに任せる
                self.screen = pygame.display.set_mode((0, 0), pygame.FULLSCREEN)
                self.width = self.screen.get_width()
                self.height = self.screen.get_height()
                print(f"🖥️ フォールバック解像度: {self.width}x{self.height}")
        else:
            # ウィンドウモードに戻す
            restore_width, restore_height = self._windowed_size or (self.base_width, self.base_height)
            self.width, self.height = restore_width, restore_height
            self.screen = pygame.display.set_mode((self.width, self.height))
            print(f"🪟 ウィンドウモード: {self.width}x{self.height}")

        self._after_display_resize()
        print(f"📐 現在の画面サイズ: {self.screen.get_width()}x{self.screen.get_height()}")

    def _apply_gpu_fullscreen_state(self, enable: bool) -> bool:
        """GPUレンダラ用ウィンドウのフルスクリーン切り替えを実施"""
        if not self.use_gpu or self.gpu_window is None:
            return False

        desktop_size: Optional[Tuple[int, int]] = None
        restore_size: Optional[Tuple[int, int]] = None

        try:
            if enable:
                desktop_size = self._get_gpu_desktop_size()
                if desktop_size:
                    try:
                        self.gpu_window.size = desktop_size
                    except Exception as size_err:
                        print(f"⚠️ GPUフルスクリーン用サイズ設定失敗: {size_err}")
                try:
                    # pygame-ce 2.5.x provides set_fullscreen(desktop=False)
                    self.gpu_window.set_fullscreen(desktop=True)
                except TypeError:
                    try:
                        self.gpu_window.set_fullscreen(True)
                    except TypeError:
                        self.gpu_window.set_fullscreen()
                except Exception as flag_err:
                    print(f"❌ GPUフルスクリーン切替失敗: {flag_err}")
                    return False
            else:
                try:
                    if hasattr(self.gpu_window, "set_windowed"):
                        self.gpu_window.set_windowed()
                    else:
                        self.gpu_window.set_fullscreen(False)
                except Exception as flag_err:
                    print(f"⚠️ GPUフルスクリーン解除失敗: {flag_err}")
                restore_size = self._windowed_size or self.original_size
                try:
                    self.gpu_window.size = restore_size
                except Exception as size_err:
                    print(f"⚠️ GPUウィンドウサイズ復元失敗: {size_err}")

            pygame.event.pump()
            updated_size = getattr(self.gpu_window, "size", None)
            if isinstance(updated_size, tuple) and len(updated_size) == 2:
                self.width, self.height = updated_size
            elif enable and desktop_size:
                self.width, self.height = desktop_size
            elif not enable and restore_size:
                self.width, self.height = restore_size

            self._update_gpu_render_size(self.width, self.height)
            self._after_display_resize()
            print(f"🖥️ GPUフルスクリーン{'ON' if enable else 'OFF'}: {self.width}x{self.height}")
            return True
        except Exception as e:
            print(f"❌ GPUフルスクリーン切替失敗: {e}")
            return False

    def _get_gpu_desktop_size(self) -> Optional[Tuple[int, int]]:
        """現在のディスプレイにおけるデスクトップ解像度を取得"""
        try:
            sizes = pygame.display.get_desktop_sizes()
            if sizes:
                index = getattr(self.gpu_window, "display_index", 0) or 0
                index = max(0, min(index, len(sizes) - 1))
                return sizes[index]
        except Exception as e:
            print(f"⚠️ デスクトップ解像度取得失敗: {e}")
        return None

    def adjust_fish_positions_for_screen_resize(self):
        """画面サイズ変更時に魚の位置を調整"""
        for fish in self.fishes.values():
            # 魚が画面外にいる場合は画面内に移動
            if fish.x >= self.width:
                fish.x = self.width - 50
                fish.target_x = fish.x
            if fish.y >= self.height:
                fish.y = self.height - 50
                fish.target_y = fish.y

            # 新しい画面サイズに合わせて目標位置も調整
            if fish.target_x >= self.width:
                fish.target_x = random.uniform(50, self.width - 50)
            if fish.target_y >= self.height:
                fish.target_y = random.uniform(50, self.height - 50)

    def _cycle_process_limit(self):
        """プロセス制限を切り替え"""
        limits = [None, 10, 20, 50, 100, 200, 400]
        current_index = limits.index(self.process_limit) if self.process_limit in limits else 0
        next_index = (current_index + 1) % len(limits)
        self.process_limit = limits[next_index]
        self.process_manager.set_process_limit(self.process_limit)
        limit_str = "無制限" if self.process_limit is None else str(self.process_limit)
        print(f"🔢 プロセス制限: {limit_str}")

        # ワールドサイズの動的更新
        self._update_world_size(self.process_limit)

    def _cycle_sort_field(self):
        """ソートフィールドを切り替え"""
        fields = ["cpu", "memory", "name", "pid"]
        current_index = fields.index(self.sort_by) if self.sort_by in fields else 0
        next_index = (current_index + 1) % len(fields)
        self.sort_by = fields[next_index]
        self.process_manager.set_sort_config(self.sort_by, self.sort_order)
        field_names = {"cpu": "CPU使用率", "memory": "メモリ使用率", "name": "プロセス名", "pid": "PID"}
        print(f"📊 ソート: {field_names[self.sort_by]}")

    def _toggle_sort_order(self):
        """ソート順序を切り替え"""
        self.sort_order = "asc" if self.sort_order == "desc" else "desc"
        self.process_manager.set_sort_config(self.sort_by, self.sort_order)
        order_name = "昇順" if self.sort_order == "asc" else "降順"
        print(f"🔄 ソート順序: {order_name}")

    def _cycle_display_modes(self):
        """表示モードを循環切り替え (M key)"""
        # デバッグとIPCの組み合わせを循環
        if not self.show_debug and self.show_ipc:
            # 通常モード → デバッグオンリー
            self.show_debug = True
            self.show_ipc = False
            print("📋 表示モード: デバッグのみ")
        elif self.show_debug and not self.show_ipc:
            # デバッグオンリー → 両方オン
            self.show_debug = True
            self.show_ipc = True
            print("📋 表示モード: デバッグ + IPC")
        elif self.show_debug and self.show_ipc:
            # 両方オン → IPCオンリー
            self.show_debug = False
            self.show_ipc = True
            print("📋 表示モード: IPCのみ")
        else:
            # IPCオンリー or すべてオフ → 通常モード
            self.show_debug = False
            self.show_ipc = True
            print("📋 表示モード: 通常")

    def _toggle_ui_display(self):
        """UI表示の簡素化切り替え (T key)"""
        if not hasattr(self, 'ui_mode'):
            self.ui_mode = 0  # 0: フル表示, 1: 簡素表示, 2: 最小表示

        self.ui_mode = (self.ui_mode + 1) % 3

        if self.ui_mode == 0:
            print("🎛️ UI表示: フル")
        elif self.ui_mode == 1:
            print("🎛️ UI表示: 簡素")
        else:  # ui_mode == 2
            print("🎛️ UI表示: 最小")

    def _configure_quality_thresholds(self):
        """FPSベースの品質閾値を設定"""
        if not self.enable_adaptive_quality:
            self._quality_thresholds = (None, None)
            return

        target_fps = float(self.fps or 30)
        reduced_default = max(target_fps * 0.75, target_fps - 5.0)
        minimal_default = max(target_fps * 0.5, target_fps - 12.0)

        reduced_env = os.environ.get("AQUARIUM_QUALITY_REDUCED_FPS")
        minimal_env = os.environ.get("AQUARIUM_QUALITY_MINIMAL_FPS")

        reduced_threshold = self._parse_fps_threshold(reduced_env, reduced_default, target_fps)
        minimal_threshold = self._parse_fps_threshold(minimal_env, minimal_default, target_fps)

        if minimal_threshold >= reduced_threshold:
            minimal_threshold = max(1.0, min(reduced_threshold - 2.0, reduced_threshold * 0.7))
        reduced_threshold = max(minimal_threshold + 1.0, reduced_threshold)

        self._quality_thresholds = (reduced_threshold, minimal_threshold)

    def _parse_fps_threshold(self, value: Optional[str], default: float, target_fps: float) -> float:
        if not value:
            return default
        try:
            threshold = float(value)
            if 0 < threshold <= 1.0:
                threshold = target_fps * threshold
        except ValueError:
            return default
        return max(1.0, threshold)

    def _adjust_performance(self):
        """動的パフォーマンス調整"""
        if not self.performance_monitor['fps_history']:
            return

        avg_fps = sum(self.performance_monitor['fps_history']) / len(self.performance_monitor['fps_history'])
        avg_fish_count = sum(self.performance_monitor['fish_count_history']) / len(self.performance_monitor['fish_count_history'])

        # FPSが低い場合の調整
        if avg_fps < self.fps * 0.7:  # 目標FPSの70%以下
            # パーティクル数を減らす
            if self.performance_monitor['adaptive_particle_count'] > 20:
                self.performance_monitor['adaptive_particle_count'] -= 5
                print(f"🐌 パフォーマンス調整: パーティクル数を{self.performance_monitor['adaptive_particle_count']}に減少")

            # 魚の更新間隔を増やす
            if self.performance_monitor['adaptive_fish_update_interval'] < 3:
                self.performance_monitor['adaptive_fish_update_interval'] += 1
                print(f"🐌 パフォーマンス調整: 魚更新間隔を{self.performance_monitor['adaptive_fish_update_interval']}に増加")

        # FPSが十分高い場合は品質を向上
        elif avg_fps > self.fps * 0.9 and avg_fish_count < 80:
            # パーティクル数を増やす
            if self.performance_monitor['adaptive_particle_count'] < 100:
                self.performance_monitor['adaptive_particle_count'] += 5
                print(f"🚀 パフォーマンス調整: パーティクル数を{self.performance_monitor['adaptive_particle_count']}に増加")

            # 魚の更新間隔を減らす
            if self.performance_monitor['adaptive_fish_update_interval'] > 1:
                self.performance_monitor['adaptive_fish_update_interval'] -= 1
                print(f"🚀 パフォーマンス調整: 魚更新間隔を{self.performance_monitor['adaptive_fish_update_interval']}に減少")

    def _update_render_quality(self):
        """描画品質の自動調整（必要な場合のみ）"""
        if not self.enable_adaptive_quality:
            if self.render_quality != "full":
                self.render_quality = "full"
                self._suppress_spawn_logs = False
            return

        reduced_threshold, minimal_threshold = self._quality_thresholds
        if reduced_threshold is None or minimal_threshold is None:
            return

        fps_samples = self.performance_monitor['fps_history'][-60:]
        if len(fps_samples) < 15:
            return

        avg_fps = sum(fps_samples) / len(fps_samples)
        previous = self.render_quality

        quality = "full"
        if avg_fps <= minimal_threshold:
            quality = "minimal"
        elif avg_fps <= reduced_threshold:
            quality = "reduced"

        margin = self._quality_recovery_margin
        if quality == "full":
            if previous == "minimal" and avg_fps < minimal_threshold + margin:
                quality = "minimal"
            elif previous == "reduced" and avg_fps < reduced_threshold + margin:
                quality = "reduced"
        elif quality == "reduced" and previous == "minimal" and avg_fps < minimal_threshold + margin:
            quality = "minimal"

        if quality == previous:
            return

        self.render_quality = quality
        if quality == "full":
            self._suppress_spawn_logs = False
            if "quality_full" not in self._quality_message_shown:
                print(f"🎨 描画品質: フル品質に復帰しました (平均FPS {avg_fps:.1f} > {reduced_threshold + margin:.1f})。")
                self._quality_message_shown.add("quality_full")
            self._quality_message_shown.discard("quality_reduced")
            self._quality_message_shown.discard("quality_minimal")
        elif quality == "reduced":
            self._suppress_spawn_logs = True
            self.performance_monitor['adaptive_particle_count'] = min(self.performance_monitor['adaptive_particle_count'], 35)
            self.performance_monitor['adaptive_fish_update_interval'] = max(self.performance_monitor['adaptive_fish_update_interval'], 2)
            if "quality_reduced" not in self._quality_message_shown:
                print(f"🎨 描画品質: FPS低下のため簡易品質に切り替えました (平均FPS {avg_fps:.1f} ≤ {reduced_threshold:.1f})。")
                print("   → 波紋・雷エフェクトを削減し、群れ演算を軽量化します。")
                self._quality_message_shown.add("quality_reduced")
            self._quality_message_shown.discard("quality_minimal")
        else:  # minimal
            self._suppress_spawn_logs = True
            self.performance_monitor['adaptive_particle_count'] = min(self.performance_monitor['adaptive_particle_count'], 20)
            self.performance_monitor['adaptive_fish_update_interval'] = max(self.performance_monitor['adaptive_fish_update_interval'], 3)
            if "quality_minimal" not in self._quality_message_shown:
                print(f"🎨 描画品質: FPSが大きく低下したため超過密モードに切り替えました (平均FPS {avg_fps:.1f} ≤ {minimal_threshold:.1f})。")
                print("   → 群れ行動や装飾エフェクトを停止してパフォーマンスを確保します。")
                self._quality_message_shown.add("quality_minimal")

    def _cleanup_caches(self):
        """キャッシュクリーンアップ"""
        # サーフェスキャッシュをクリア
        old_cache_size = len(self.surface_cache)
        self.surface_cache.clear()

        # 背景キャッシュをクリア
        self.background_cache = None

        # print(f"🧹 キャッシュクリーンアップ完了 (削除: {old_cache_size}アイテム)")

        # ガベージコレクションを明示的に実行
        import gc
        gc.collect()

    def update(self):
        """フレーム更新"""
        if self.headless:
            # 描画を行わないので最小限の更新のみ
            self.update_process_data()
            return
        current_time = time.time()

        # カメラシステムの更新
        self.update_camera()

        # パフォーマンス監視
        current_fps = self.clock.get_fps()
        self.performance_monitor['fps_history'].append(current_fps)
        self.performance_monitor['fish_count_history'].append(len(self.fishes))

        # 履歴を最新100フレームに制限
        if len(self.performance_monitor['fps_history']) > 100:
            self.performance_monitor['fps_history'] = self.performance_monitor['fps_history'][-100:]
            self.performance_monitor['fish_count_history'] = self.performance_monitor['fish_count_history'][-100:]

        # 動的パフォーマンス調整（5秒ごと）
        if current_time - self.performance_monitor['last_adjustment'] > 5.0:
            self._adjust_performance()
            self.performance_monitor['last_adjustment'] = current_time

        # プロセスデータの更新
        self.update_process_data()
        self._update_render_quality()

        # 背景パーティクルの更新
        self.update_background_particles()

        # Fishの位置更新（適応的更新間隔）
        fish_list = list(self.fishes.values())
        update_interval = self.performance_monitor['adaptive_fish_update_interval']

        dying_fish_updated = 0
        total_fish_updated = 0
        enable_nearby_search = (self.render_quality == "full")
        spatial_grid = None
        cell_size = self._neighbor_cell_size
        if enable_nearby_search and fish_list:
            spatial_grid = {}
            for fish in fish_list:
                cell_key = (int(fish.x // cell_size), int(fish.y // cell_size))
                spatial_grid.setdefault(cell_key, []).append(fish)

        for i, fish in enumerate(fish_list):
            # 適応的更新：魚の数が多い場合は一部の魚のみ更新
            # ただし、死亡中の魚は常に更新して削除処理を確実に行う
            should_update = fish.is_dying or len(fish_list) <= 50 or i % update_interval == (int(current_time * 10) % update_interval)
            if not should_update:
                continue

            if fish.is_dying:
                dying_fish_updated += 1
            total_fish_updated += 1

            # 近くの魚を検索（最適化：距離の事前チェック）
            nearby_fish = []
            if enable_nearby_search and spatial_grid is not None:
                cell_x = int(fish.x // cell_size)
                cell_y = int(fish.y // cell_size)
                visited = set()
                for dx_cell in (-1, 0, 1):
                    for dy_cell in (-1, 0, 1):
                        candidate_cell = (cell_x + dx_cell, cell_y + dy_cell)
                        for other_fish in spatial_grid.get(candidate_cell, []):
                            if other_fish.pid == fish.pid or other_fish.pid in visited:
                                continue
                            dx = fish.x - other_fish.x
                            dy = fish.y - other_fish.y
                            if abs(dx) < 100 and abs(dy) < 100:
                                distance_sq = dx * dx + dy * dy
                                if distance_sq < 10000:
                                    nearby_fish.append(other_fish)
                                    visited.add(other_fish.pid)
                                    if len(nearby_fish) >= 16:
                                        break
                        if len(nearby_fish) >= 16:
                            break
                    if len(nearby_fish) >= 16:
                        break

            fish.update_position(self.width, self.height, nearby_fish)

        # 魚の更新統計をログ出力（デバッグ用）
        # if dying_fish_updated > 0 or total_fish_updated < len(fish_list):
        #     print(f"🔄 魚更新統計: 総数{len(fish_list)}, 更新数{total_fish_updated}, 死亡中更新数{dying_fish_updated}")

        # 定期的なキャッシュクリーンアップ
        if current_time - self.last_cache_cleanup > self.cache_cleanup_interval:
            self._cleanup_caches()
            self.last_cache_cleanup = current_time

    def draw(self):
        """描画処理"""
        if self.headless:
            return  # 完全スキップ
        # 背景
        self.draw_background()

        # 親子関係の線
        if self.show_debug:
            self.draw_parent_child_connections()

        # IPC接続の線
        self.draw_ipc_connections()

        # 全てのFishを描画（カメラシステム対応）
        for fish in self.fishes.values():
            # 可視判定（画面内にある魚のみ描画）
            if self.is_visible(fish.x, fish.y, fish.current_size + 50):
                # 魚の座標をカメラ座標系に変換
                screen_x, screen_y = self.world_to_screen(fish.x, fish.y)

                # 一時的に魚の位置をスクリーン座標に設定
                original_x, original_y = fish.x, fish.y
                fish.x, fish.y = screen_x, screen_y

                # 魚を描画（ズームレベルと群れ強調表示を渡す）
                fish.draw(self.screen, self.bubble_font, quality=self.render_quality,
                          text_renderer=self._render_text, zoom_level=self.zoom_level,
                          highlight_schools=self.highlight_schools)

                # 元の座標に戻す
                fish.x, fish.y = original_x, original_y

        # 選択されたFishのハイライト
        if self.selected_fish and self.is_visible(self.selected_fish.x, self.selected_fish.y):
            highlight_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            screen_x, screen_y = self.world_to_screen(self.selected_fish.x, self.selected_fish.y)
            pygame.draw.circle(highlight_surface, (255, 255, 255, 100),
                             (int(screen_x), int(screen_y)),
                             int(self.selected_fish.current_size * self.zoom_level + 10), 2)
            self.screen.blit(highlight_surface, (0, 0))

        # 通信相手のハイライト表示
        if self.highlighted_partners:
            partner_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            for partner_pid in self.highlighted_partners:
                if partner_pid in self.fishes:
                    partner_fish = self.fishes[partner_pid]
                    if self.is_visible(partner_fish.x, partner_fish.y):
                        screen_x, screen_y = self.world_to_screen(partner_fish.x, partner_fish.y)
                        # 緑色の点滅ハイライト
                        pulse = math.sin(time.time() * 8) * 0.5 + 0.5
                        alpha = int(150 * pulse + 50)
                        pygame.draw.circle(partner_surface, (0, 255, 0, alpha),
                                         (int(screen_x), int(screen_y)),
                                         int(partner_fish.current_size * self.zoom_level + 15), 3)
            self.screen.blit(partner_surface, (0, 0))

        # UI描画
        self.draw_ui()

        # 画面更新
        if self.use_gpu:
            self._present_gpu_frame()
        else:
            pygame.display.flip()

    def run(self):
        """メインループ"""
        if not self.headless:
            print("=== Process Aquariumを開始します ===")
            print("🐠 プロセスがプロセスとして水族館に現れるまでお待ちください...")
            print("💡 ヒント: プロセス名によって色が決まり、CPU使用時に光ります")
            while self.running:
                self.handle_events()
                self.update()
                self.draw()
                self.clock.tick(self.fps)
            pygame.quit()
            print("🌙 水族館を閉館しました。お疲れさまでした！")
            return

        # ヘッドレスループ
        last_print = 0.0
        try:
            while self.running:
                start = time.time()
                self.process_manager.update()
                stats = self.process_manager.get_process_statistics()
                now = time.time()
                if now - last_print >= self.headless_interval:
                    last_print = now
                    data_source = stats.get('data_source', 'unknown')
                    base_stats = f"procs={stats['total_processes']} new={stats['new_processes']} dying={stats['dying_processes']} mem={stats['total_memory_percent']:.2f}% cpu_avg={stats['average_cpu_percent']:.2f}% threads={stats['total_threads']}"

                    # eBPFの場合はイベント統計も表示
                    if 'ebpf_events' in stats:
                        print(f"[stats|{data_source}] {base_stats} events=[{stats['ebpf_events']}]")
                    else:
                        print(f"[stats|{data_source}] {base_stats}")
                # シンプルスリープ（イベント駆動化は今後 eBPF 実装時に検討）
                elapsed = time.time() - start
                remaining = self.headless_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            print("[Headless] 中断されました。終了します。")
        finally:
            pygame.quit()

    def _print_display_info(self):
        """ディスプレイ情報をデバッグ表示"""
        try:
            # 利用可能な解像度モードを取得
            modes = pygame.display.list_modes()
            print("🖥️ 利用可能な解像度モード:")
            if modes == -1:
                print("  - 全ての解像度が利用可能")
            elif modes:
                for mode in modes[:5]:  # 最初の5つを表示
                    print(f"  - {mode[0]}x{mode[1]}")
                if len(modes) > 5:
                    print(f"  - ...他 {len(modes)-5} モード")
                max_mode = max(modes, key=lambda x: x[0] * x[1])
                print(f"  - 最大解像度: {max_mode}")
            else:
                print("  - 利用可能なモードが見つかりません")

            # 現在のディスプレイ情報
            info = pygame.display.Info()
            print(f"📱 現在のディスプレイ情報:")
            print(f"  - 現在のサイズ: {info.current_w}x{info.current_h}")
            print(f"  - ビット深度: {info.bitsize}")

            # Retinaスケールファクターを推定
            if modes and modes != -1:
                max_mode = max(modes, key=lambda x: x[0] * x[1])
                logical_width = info.current_w
                physical_width = max_mode[0]

                if physical_width > logical_width:
                    self.scale_factor = physical_width / logical_width
                    print(f"🔍 Retinaスケールファクター検出: {self.scale_factor:.1f}x")
                    print(f"  - 物理解像度: {physical_width}x{max_mode[1]}")
                    print(f"  - 論理解像度: {logical_width}x{info.current_h}")
                else:
                    self.scale_factor = 1.0
                    print("🔍 標準ディスプレイ (スケールファクター: 1.0x)")

        except Exception as e:
            print(f"❌ ディスプレイ情報取得エラー: {e}")
            self.scale_factor = 1.0

    def get_best_fullscreen_resolution(self):
        """フルスクリーン用の最適解像度を取得（常に論理解像度を使用）"""
        try:
            # 現在のディスプレイ情報を取得
            info = pygame.display.Info()
            logical_width = info.current_w
            logical_height = info.current_h

            print(f"🖥️ 論理解像度を使用: {logical_width}x{logical_height}")

            # Retinaディスプレイでも論理解像度を返す
            return logical_width, logical_height

        except Exception as e:
            print(f"❌ 解像度取得エラー: {e}")
            # フォールバック解像度
            return 1920, 1080

    def _update_font_scale(self):
        """画面サイズに基づいてフォントスケールを更新"""
        self.font_scale = min(self.width / self.base_width, self.height / self.base_height)
        # 最小スケールを設定（読みやすさを保証）
        self.font_scale = max(0.5, min(2.0, self.font_scale))

    def _determine_bubble_font_size(self) -> int:
        """IPC吹き出し用フォントサイズを計算"""
        base_size = 14
        scaled_size = int(base_size * self.font_scale)
        return max(12, min(24, scaled_size))

    def _validate_japanese_font(self, font: pygame.font.Font, test_texts: list, font_name: str) -> bool:
        """Validate whether a font can properly render Japanese characters."""
        try:
            fallback_surfaces = {}

            for test_text in test_texts:
                if not test_text:
                    continue

                contains_non_ascii = any(ord(ch) > 127 for ch in test_text)
                try:
                    test_surface = font.render(test_text, True, (255, 255, 255))
                except Exception:
                    continue

                if test_surface.get_width() <= 0 or test_surface.get_height() <= 0:
                    continue

                bounding = test_surface.get_bounding_rect()
                if bounding.width == 0 or bounding.height == 0:
                    continue

                metrics_valid = False
                try:
                    metrics = font.metrics(test_text)
                except Exception:
                    metrics = None

                if metrics:
                    for metric in metrics:
                        if metric and len(metric) >= 5:
                            advance = metric[4]
                            if isinstance(advance, (int, float)) and advance > 0:
                                metrics_valid = True
                                break

                if not metrics_valid:
                    identical_to_fallback = False
                    for fallback_char in ("?", "□"):
                        key = (fallback_char, font.size(fallback_char * len(test_text)))
                        if key not in fallback_surfaces:
                            try:
                                fallback_surfaces[key] = font.render(fallback_char * len(test_text), True, (255, 255, 255))
                            except Exception:
                                fallback_surfaces[key] = None
                        fallback_surface = fallback_surfaces.get(key)
                        if fallback_surface is None:
                            continue
                        if fallback_surface.get_size() == test_surface.get_size():
                            try:
                                if pygame.image.tostring(test_surface, "RGBA") == pygame.image.tostring(fallback_surface, "RGBA"):
                                    identical_to_fallback = True
                                    break
                            except Exception:
                                pass
                    if identical_to_fallback:
                        continue

                if contains_non_ascii:
                    return True

            return False

        except Exception:
            return False

    def _get_japanese_font(self, size: int) -> pygame.font.Font:
        """Obtain a Japanese-capable font (cross-platform fallback logic)."""
        cached = self._font_cache.get(size)
        if cached:
            return cached

        import platform
        system = platform.system()

        candidate_specs: List[Tuple[str, str]] = []
        seen_candidates: set[Tuple[str, str]] = set()

        def add_candidate(kind: str, identifier: Optional[str]) -> None:
            if not identifier:
                return
            if kind == "path" and not os.path.exists(identifier):
                return
            key = (kind, identifier)
            if key in seen_candidates:
                return
            candidate_specs.append(key)
            seen_candidates.add(key)

        # ユーザー指定または以前成功したフォントを最優先
        add_candidate("path", os.environ.get("AQUARIUM_FONT_PATH"))
        add_candidate("sysfont", os.environ.get("AQUARIUM_FONT_NAME"))
        add_candidate("path", getattr(self, "_preferred_font_path", None))
        add_candidate("sysfont", getattr(self, "_preferred_font_name", None))

        # プラットフォーム固有のフォント候補
        if system == "Darwin":
            name_aliases = [
                "hiragino", "hiraginokakugothic", "hiraginomarugothic",
                "sfpro", "sfcompact", "applegothic", "osaka",
                "noto", "arialunicodems"
            ]
            path_candidates = [
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
                "/System/Library/Fonts/ヒラギノ丸ゴ ProN W4.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/System/Library/Fonts/Apple Color Emoji.ttc",
                "/Library/Fonts/Arial Unicode.ttf",
            ]
            fallback_names = [
                "SF Pro Display", "SF Pro Text", "Hiragino Sans",
                "Hiragino Kaku Gothic ProN", "Hiragino Kaku Gothic Pro",
                "Hiragino Maru Gothic ProN", "Arial Unicode MS",
                "Helvetica Neue", "Arial"
            ]
        elif system == "Linux":
            name_aliases = [
                "notosanscjk", "notoserifcjk", "vlgothic", "migu", "takao",
                "ipamg", "ipag", "ipamincho", "ume", "sazanami"
            ]
            path_candidates = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
                "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Medium.otf",
                "/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf",
                "/usr/share/fonts/truetype/ipafont/ipag.ttf",
                "/usr/share/fonts/truetype/ipafont/ipam.ttf",
            ]
            fallback_names = [
                "Noto Sans CJK JP", "Noto Serif CJK JP", "Noto Sans CJK SC",
                "VL Gothic", "IPAGothic", "IPAMincho",
                "DejaVu Sans", "Liberation Sans", "Arial"
            ]
        elif system == "Windows":
            name_aliases = [
                "yugoth", "meiryo", "msgothic", "mspgothic",
                "msmincho", "mspmincho", "malgungothic", "mingliu"
            ]
            path_candidates = [
                "C:/Windows/Fonts/yugothic.ttf",
                "C:/Windows/Fonts/yu-gothic.ttf",
                "C:/Windows/Fonts/meiryo.ttc",
                "C:/Windows/Fonts/msgothic.ttc",
                "C:/Windows/Fonts/msmincho.ttc",
                "C:/Windows/Fonts/arialuni.ttf",
            ]
            fallback_names = [
                "Yu Gothic UI", "Yu Gothic", "Meiryo UI", "Meiryo",
                "MS Gothic", "MS PGothic", "MS Mincho", "MS PMincho",
                "Arial Unicode MS", "Segoe UI", "Arial"
            ]
        else:
            name_aliases = ["noto", "dejavu", "liberation", "arialunicodems"]
            path_candidates = []
            fallback_names = [
                "Arial Unicode MS", "DejaVu Sans", "Liberation Sans", "Arial"
            ]

        # 直接パス候補
        for font_path in path_candidates:
            add_candidate("path", font_path)

        # pygameが認識しているフォント名からエイリアスに一致するものを追加
        available_fonts = pygame.font.get_fonts()
        for alias in name_aliases:
            alias_lower = alias.lower()
            for registered_name in available_fonts:
                if alias_lower in registered_name:
                    matched_path = pygame.font.match_font(registered_name, bold=False, italic=False)
                    add_candidate("path", matched_path)

        # フォールバックとして明示的なフォント名も登録
            for font_name in fallback_names:
                add_candidate("sysfont", font_name)

            test_texts = ["あいう", "アイウ", "日本語", "テスト", "通信中...", "データ送信"]

            for kind, identifier in candidate_specs:
                try:
                    if kind == "sysfont":
                        font = pygame.font.SysFont(identifier, size)
                    else:
                        font = pygame.font.Font(identifier, size)

                    if self._validate_japanese_font(font, test_texts, identifier):
                        self._font_cache[size] = font
                        if kind == "sysfont":
                            self._preferred_font_name = identifier
                            print(f"✅ 日本語フォント '{identifier}' を使用します (サイズ: {size}) - {system}")
                        else:
                            self._preferred_font_path = identifier
                            print(f"✅ フォントファイル '{identifier}' を使用します (サイズ: {size})")
                        return font
                except Exception as e:
                    print(f"❌ フォント '{identifier}' の読み込みに失敗: {e}")
                    continue

        try:
            default_font_path = pygame.font.get_default_font()
            fallback_font = pygame.font.Font(default_font_path, size)
            print(f"⚠️  デフォルトフォント '{default_font_path}' を使用します（日本語表示不可）")
        except Exception:
            print("❌ フォント読み込み完全失敗。Noneフォントを使用します")
            fallback_font = pygame.font.Font(None, size)

        return fallback_font

    def _render_text(self, text: str, font: pygame.font.Font, color: Tuple[int, int, int]) -> pygame.Surface:
        """Safely render text (supports Japanese where possible)."""
        try:
            # UTF-8エンコーディングを確実にする
            if isinstance(text, bytes):
                text = text.decode('utf-8')

            # 文字列の正規化
            import unicodedata
            text = unicodedata.normalize('NFC', text)

            # レンダリング試行
            surface = font.render(text, True, color)

            # レンダリング結果の検証
            if surface.get_width() > 0 and surface.get_height() > 0:
                return surface
            else:
                # 空のサーフェスの場合、ASCII変換を試行
                raise Exception("Empty surface rendered")

        except Exception as e:
            print(f"⚠️  テキストレンダリングエラー '{text}': {e}")
            try:
                # ASCII文字のみに変換
                safe_text = text.encode('ascii', 'replace').decode('ascii')
                return font.render(safe_text, True, color)
            except:
                # 最終的なフォールバック
                fallback_text = "[TEXT_ERROR]"
                return font.render(fallback_text, True, color)

    def detect_retina_scaling(self):
        """Retinaスケールファクターを検出"""
        try:
            # 利用可能な最大物理解像度を取得
            modes = pygame.display.list_modes()
            if modes and modes != -1:
                max_physical = max(modes, key=lambda x: x[0] * x[1])
            else:
                max_physical = (1920, 1080)  # フォールバック

            # 現在の論理解像度を取得
            info = pygame.display.Info()
            logical = (info.current_w, info.current_h)

            # スケールファクターを計算
            scale_x = max_physical[0] / logical[0] if logical[0] > 0 else 1.0
            scale_y = max_physical[1] / logical[1] if logical[1] > 0 else 1.0
            scale_factor = max(scale_x, scale_y)

            print(f"🔍 Retina解析:")
            print(f"  - 物理解像度: {max_physical[0]}x{max_physical[1]}")
            print(f"  - 論理解像度: {logical[0]}x{logical[1]}")
            print(f"  - スケールファクター: {scale_factor:.2f}x")

            return {
                'physical': max_physical,
                'logical': logical,
                'scale_factor': scale_factor,
                'is_retina': scale_factor >= 1.5
            }

        except Exception as e:
            print(f"❌ Retina検出エラー: {e}")
            return {
                'physical': (1920, 1080),
                'logical': (1920, 1080),
                'scale_factor': 1.0,
                'is_retina': False
            }

    def _env_flag(self, name: str, default: bool = False) -> bool:
        value = os.environ.get(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _init_gpu_renderer(self, width: int, height: int):
        try:
            from pygame._sdl2.video import Window, Renderer, Texture

            self.gpu_window = Window("Process Aquarium - プロセス水族館 (GPUモード)",
                                     size=(width, height), resizable=True)
            vsync_enabled = self._env_flag("AQUARIUM_VSYNC", True)
            self.gpu_renderer = Renderer(self.gpu_window, -1, True, vsync_enabled)
            if hasattr(self.gpu_renderer, "logical_size"):
                self.gpu_renderer.logical_size = (width, height)
            self._gpu_texture_type = Texture
            self.screen = pygame.Surface((width, height), flags=pygame.SRCALPHA, depth=32)
            self.gpu_texture = None
            self.use_gpu = True
            print("[GPU] SDL2アクセラレータを有効化しました (vsync={}).".format(vsync_enabled))
        except Exception as exc:
            print(f"[GPU] アクセラレータ初期化に失敗しました: {exc}\n       ソフトウェアモードにフォールバックします。")
            self.use_gpu = False
            self.gpu_renderer = None
            self.gpu_window = None
            self.gpu_texture = None

    def _present_gpu_frame(self):
        if not self.use_gpu or self.gpu_renderer is None:
            return
        try:
            if self.gpu_texture is None or getattr(self.gpu_texture, "size", None) != (self.width, self.height):
                self.gpu_texture = self._gpu_texture_type.from_surface(self.gpu_renderer, self.screen)
            else:
                self.gpu_texture.update(self.screen)
            self.gpu_renderer.draw_color = (0, 0, 0, 255)
            self.gpu_renderer.clear()
            # pygame-ce 2.5.x exposes texture drawing via Texture.draw()
            self.gpu_texture.draw()
            self.gpu_renderer.present()
        except Exception as exc:
            print(f"[GPU] 描画更新でエラーが発生したためフォールバックします: {exc}")
            self.use_gpu = False
            self.gpu_renderer = None
            self.gpu_window = None
            pygame.display.set_caption("Process Aquarium - プロセス水族館")
            self.screen = pygame.display.set_mode((self.width, self.height))

    def _update_gpu_render_size(self, width: int, height: int):
        if not self.use_gpu:
            return
        self.screen = pygame.Surface((width, height), flags=pygame.SRCALPHA, depth=32)
        if self.gpu_renderer is not None and hasattr(self.gpu_renderer, "logical_size"):
            self.gpu_renderer.logical_size = (width, height)
        self.gpu_texture = None

    def _after_display_resize(self):
        """画面サイズ変更後の共通処理"""
        self.init_background_particles()
        self.adjust_fish_positions_for_screen_resize()
        self._update_font_scale()
        base_font_size = 20  # より小さく：24→20
        small_font_size = 14  # より小さく：18→14
        self.font = self._get_japanese_font(int(base_font_size * self.font_scale))
        self.small_font = self._get_japanese_font(int(small_font_size * self.font_scale))
        self.bubble_font = self._get_japanese_font(self._determine_bubble_font_size())

def main():
    """メイン関数"""
    aquarium = Aquarium()
    aquarium.run()

if __name__ == "__main__":
    main()
