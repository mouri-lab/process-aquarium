"""
Digital Life Aquarium - Pyglet GPU-accelerated version
完全なGPUアクセラレーション対応版
"""

import sys
import time
import random
import math
import os
from typing import Dict, List, Optional, Tuple
from ..core.process_manager import ProcessManager

try:
    from ..core.sources import EbpfProcessSource
except Exception:
    EbpfProcessSource = None

from .fish_pyglet import Fish

# 文字エンコーディング設定
import locale
try:
    locale.setlocale(locale.LC_ALL, 'ja_JP.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except:
        pass

# Lazy import pyglet to support headless mode
_pyglet_loaded = False
pyglet = None
gl = None

def _load_pyglet():
    """Load pyglet modules (lazy loading)"""
    global _pyglet_loaded, pyglet, gl
    if not _pyglet_loaded:
        import pyglet as _pyglet
        from pyglet import gl as _gl
        pyglet = _pyglet
        gl = _gl
        _pyglet_loaded = True


class Aquarium:
    """デジタル生命の水族館 - Pyglet GPU-accelerated"""
    
    def __init__(self, width: int = 1200, height: int = 800, headless: bool = False, headless_interval: float = 1.0):
        self.headless = headless
        self.headless_interval = headless_interval
        self.running = True
        
        self.width = width
        self.height = height
        self.base_width = width
        self.base_height = height
        self._fullscreen = False
        
        target_fps = int(os.environ.get('AQUARIUM_FPS', '30'))
        self.fps = target_fps if not headless else int(1.0 / max(headless_interval, 0.001))
        
        # Initialize window if not headless
        self.window = None
        if not headless:
            _load_pyglet()
            self.window = pyglet.window.Window(width, height,
                                              "Digital Life Aquarium - デジタル生命の水族館",
                                              resizable=False, vsync=True)
            # OpenGL setup for GPU acceleration
            gl.glEnable(gl.GL_BLEND)
            gl.glBlendFunc(gl.GL_SRC_ALPHA, gl.GL_ONE_MINUS_SRC_ALPHA)
            gl.glEnable(gl.GL_LINE_SMOOTH)
            gl.glHint(gl.GL_LINE_SMOOTH_HINT, gl.GL_NICEST)
            
            # Event handlers
            self.window.on_draw = self.on_draw
            self.window.on_key_press = self.on_key_press
            self.window.on_mouse_press = self.on_mouse_press
            
            # Schedule updates
            pyglet.clock.schedule_interval(self.update, 1.0/self.fps)
        else:
            print("[Headless] モードで起動しました。統計情報のみを出力します。Ctrl+Cで終了。")
        
        # Process manager
        self._init_process_manager()
        
        # Fish dictionary
        self.fishes: Dict[int, Fish] = {}
        
        # UI state
        self.show_debug = False
        self.show_ipc = True
        self.selected_fish: Optional[Fish] = None
        self.highlighted_partners: List[int] = []
        
        # IPC tracking
        self.ipc_connections: Dict[int, List[Tuple[int, str]]] = {}
        self.last_ipc_update = 0
        
        # Background particles
        self.background_particles = []
        self.performance_monitor = {
            'background_particle_limit': 100,
            'fps_history': [],
            'fish_count_history': [],
            'last_adjustment': time.time(),
            'adaptive_fish_update_interval': 1,
        }
        self.init_background_particles()
        
        # Font sizes
        self.ui_font_size = 14
        self.small_font_size = 12
        self.bubble_font_size = 11
        
        # Cache management
        self.last_cache_cleanup = time.time()
        self.cache_cleanup_interval = 30.0
    
    def _init_process_manager(self):
        """Initialize process manager"""
        source = None
        chosen = os.environ.get("AQUARIUM_SOURCE", "psutil").lower()
        if chosen == "ebpf":
            try:
                from ..core.sources import EbpfProcessSource
                eb = EbpfProcessSource(enable=True, hybrid_mode=True)
                if getattr(eb, 'available', False):
                    source = eb
                    print("[eBPF] EbpfProcessSource 有効化")
            except:
                print("[eBPF] psutilにフォールバック")
        
        self.process_manager = ProcessManager(source=source)
        
        # Default limit and sort settings
        default_limit = os.environ.get('AQUARIUM_LIMIT', None)
        if default_limit and default_limit.lower() != 'none':
            try:
                self.process_manager.set_process_limit(int(default_limit))
            except:
                pass
        
        sort_by = os.environ.get('AQUARIUM_SORT_BY', 'cpu')
        sort_order = os.environ.get('AQUARIUM_SORT_ORDER', 'desc')
        self.process_manager.set_sort_config(sort_by, sort_order)
    
    def init_background_particles(self):
        """Initialize background particles"""
        limit = self.performance_monitor['background_particle_limit']
        self.background_particles = []
        for _ in range(limit):
            self.background_particles.append({
                'x': random.uniform(0, self.width),
                'y': random.uniform(0, self.height),
                'vx': random.uniform(-0.5, 0.5),
                'vy': random.uniform(-0.5, 0.5),
                'size': random.uniform(1, 3),
                'alpha': random.uniform(50, 150)
            })
    
    def update_background_particles(self):
        """Update background particles"""
        for p in self.background_particles:
            p['x'] += p['vx']
            p['y'] += p['vy']
            
            if p['x'] < 0 or p['x'] > self.width:
                p['vx'] *= -1
                p['x'] = max(0, min(p['x'], self.width))
            if p['y'] < 0 or p['y'] > self.height:
                p['vy'] *= -1
                p['y'] = max(0, min(p['y'], self.height))
    
    def update_process_data(self):
        """Update process data"""
        self.process_manager.update()
        
        # Add new processes as fish
        for proc in self.process_manager.get_new_processes():
            if proc.pid not in self.fishes:
                x = random.uniform(50, self.width - 50)
                y = random.uniform(50, self.height - 50)
                fish = Fish(proc.pid, proc.name, x, y)
                fish.update_process_data(proc.memory_percent, proc.cpu_percent,
                                        proc.num_threads, proc.ppid)
                self.fishes[proc.pid] = fish
        
        # Mark dying processes
        for proc in self.process_manager.get_dying_processes():
            if proc.pid in self.fishes:
                self.fishes[proc.pid].start_dying()
        
        # Update existing fish
        for pid, fish in list(self.fishes.items()):
            if pid in self.process_manager.processes:
                proc = self.process_manager.processes[pid]
                fish.update_process_data(proc.memory_percent, proc.cpu_percent,
                                        proc.num_threads, proc.ppid)
            
            # Remove completed death animations
            if fish.is_dying and fish.death_progress >= 1.0:
                del self.fishes[pid]
        
        # Update IPC connections
        current_time = time.time()
        if current_time - self.last_ipc_update > 2.0:
            self._update_ipc_connections()
            self._apply_ipc_attraction()
            self.last_ipc_update = current_time
        
        # Update schooling behavior
        self._update_schooling_behavior()
    
    def _update_schooling_behavior(self):
        """Update schooling behavior"""
        groups = {}
        for fish in self.fishes.values():
            if fish.process_name not in groups:
                groups[fish.process_name] = []
            groups[fish.process_name].append(fish.pid)
        
        for fish in self.fishes.values():
            if fish.process_name in groups:
                fish.school_members = [p for p in groups[fish.process_name] if p != fish.pid]
    
    def _update_ipc_connections(self):
        """Update IPC connections"""
        try:
            conns = self.process_manager.detect_ipc_connections()
            self.ipc_connections.clear()
            for src, tgt, ctype in conns:
                if src not in self.ipc_connections:
                    self.ipc_connections[src] = []
                self.ipc_connections[src].append((tgt, ctype))
        except:
            pass
    
    def _apply_ipc_attraction(self):
        """Apply IPC attraction forces"""
        for src_pid, conns in self.ipc_connections.items():
            if src_pid not in self.fishes:
                continue
            src_fish = self.fishes[src_pid]
            
            for tgt_pid, _ in conns:
                if tgt_pid not in self.fishes:
                    continue
                tgt_fish = self.fishes[tgt_pid]
                
                dx = tgt_fish.x - src_fish.x
                dy = tgt_fish.y - src_fish.y
                dist = math.sqrt(dx*dx + dy*dy)
                
                if dist > 1:
                    force = 0.02
                    src_fish.ipc_attraction_x = dx / dist * force
                    src_fish.ipc_attraction_y = dy / dist * force
    
    def update(self, dt=None):
        """Update frame (Pyglet callback)"""
        if self.headless:
            self.update_process_data()
            return
        
        self.update_process_data()
        self.update_background_particles()
        
        # Update fish positions
        fish_list = list(self.fishes.values())
        for fish in fish_list:
            nearby = []
            for other in fish_list:
                if other.pid != fish.pid:
                    dx = fish.x - other.x
                    dy = fish.y - other.y
                    if abs(dx) < 100 and abs(dy) < 100:
                        if dx*dx + dy*dy < 10000:
                            nearby.append(other)
            fish.update_position(self.width, self.height, nearby)
    
    def on_draw(self):
        """Draw frame (Pyglet callback - GPU accelerated)"""
        self.window.clear()
        self.draw_background()
        
        if self.show_ipc:
            self.draw_ipc_connections()
        
        if self.show_debug:
            self.draw_parent_child_connections()
        
        # Draw fish
        for fish in self.fishes.values():
            fish.draw()
        
        # Highlight selected fish
        if self.selected_fish and self.selected_fish.pid in self.fishes:
            self._draw_circle(self.selected_fish.x, self.selected_fish.y,
                            self.selected_fish.current_size + 10, (255, 255, 255, 100))
        
        self.draw_ui()
    
    def draw_background(self):
        """Draw background (GPU accelerated)"""
        gl.glClearColor(0.05, 0.1, 0.2, 1.0)
        
        for p in self.background_particles:
            color = (100, 150, 200, int(p['alpha']))
            self._draw_circle(p['x'], p['y'], p['size'], color)
    
    def _draw_circle(self, x: float, y: float, r: float, color: Tuple[int, int, int, int]):
        """Draw circle (GPU accelerated)"""
        segs = 16
        verts = []
        for i in range(segs):
            angle = 2.0 * math.pi * i / segs
            verts.extend([x + r * math.cos(angle), y + r * math.sin(angle)])
        
        gl.glColor4ub(*color)
        pyglet.graphics.draw(segs, gl.GL_TRIANGLE_FAN, ('v2f', verts))
    
    def draw_parent_child_connections(self):
        """Draw parent-child relationships"""
        for fish in self.fishes.values():
            if fish.parent_pid and fish.parent_pid in self.fishes:
                parent = self.fishes[fish.parent_pid]
                gl.glColor4ub(100, 150, 200, 50)
                pyglet.graphics.draw(2, gl.GL_LINES,
                    ('v2f', [parent.x, parent.y, fish.x, fish.y]))
    
    def draw_ipc_connections(self):
        """Draw IPC connections"""
        for src_pid, conns in self.ipc_connections.items():
            if src_pid not in self.fishes:
                continue
            src = self.fishes[src_pid]
            
            for tgt_pid, ctype in conns:
                if tgt_pid not in self.fishes:
                    continue
                tgt = self.fishes[tgt_pid]
                
                if ctype == 'pipe':
                    color = (100, 255, 100, 150)
                elif ctype == 'socket':
                    color = (100, 100, 255, 150)
                else:
                    color = (255, 255, 100, 150)
                
                gl.glColor4ub(*color)
                pyglet.graphics.draw(2, gl.GL_LINES,
                    ('v2f', [src.x, src.y, tgt.x, tgt.y]))
    
    def draw_ui(self):
        """Draw UI"""
        stats = self.process_manager.get_process_statistics()
        
        # Stats (top right)
        lines = [
            f"🐠 生命体: {stats['total']}",
            f"🆕 新規: {stats['new']}",
            f"💀 終了: {stats['dying']}",
        ]
        
        limit = self.process_manager._process_limit
        if limit:
            lines.append(f"📊 制限: {limit}")
        lines.append(f"🔢 ソート: {self.process_manager._sort_by} ({self.process_manager._sort_order})")
        
        y = self.height - 30
        for line in lines:
            label = pyglet.text.Label(line, font_name='Arial', font_size=self.ui_font_size,
                                    x=self.width - 250, y=y, color=(255, 255, 255, 255))
            label.draw()
            y -= 25
        
        # Help (bottom left)
        help_lines = [
            "操作方法:", "クリック: 生命体を選択", "ESC: 終了",
            "D: デバッグ表示切替", "I: IPC接続表示切替", "F/F11: フルスクリーン切替",
            "L: プロセス制限切替", "S: ソートフィールド切替", "O: ソート順序切替",
        ]
        
        y = 30
        for line in help_lines:
            label = pyglet.text.Label(line, font_name='Arial', font_size=self.small_font_size,
                                    x=15, y=y, color=(200, 200, 200, 255))
            label.draw()
            y += 20
    
    def on_key_press(self, symbol, modifiers):
        """Handle key press"""
        if symbol == pyglet.window.key.ESCAPE:
            self.running = False
            self.window.close()
        elif symbol == pyglet.window.key.D:
            self.show_debug = not self.show_debug
            print(f"デバッグ表示: {'オン' if self.show_debug else 'オフ'}")
        elif symbol == pyglet.window.key.I:
            self.show_ipc = not self.show_ipc
            print(f"IPC可視化: {'オン' if self.show_ipc else 'オフ'}")
        elif symbol == pyglet.window.key.F or symbol == pyglet.window.key.F11:
            self.toggle_fullscreen()
        elif symbol == pyglet.window.key.L:
            self._cycle_process_limit()
        elif symbol == pyglet.window.key.S:
            self._cycle_sort_field()
        elif symbol == pyglet.window.key.O:
            self._toggle_sort_order()
    
    def _cycle_process_limit(self):
        """Cycle process limit"""
        limits = [None, 10, 20, 50, 100, 200]
        current = self.process_manager._process_limit
        try:
            idx = (limits.index(current) + 1) % len(limits)
        except:
            idx = 1
        self.process_manager.set_process_limit(limits[idx])
        print(f"プロセス制限: {limits[idx] or 'なし'}")
    
    def _cycle_sort_field(self):
        """Cycle sort field"""
        fields = ['cpu', 'memory', 'name', 'pid']
        try:
            idx = (fields.index(self.process_manager._sort_by) + 1) % len(fields)
        except:
            idx = 0
        self.process_manager.set_sort_config(fields[idx], self.process_manager._sort_order)
        print(f"ソートフィールド: {fields[idx]}")
    
    def _toggle_sort_order(self):
        """Toggle sort order"""
        order = 'asc' if self.process_manager._sort_order == 'desc' else 'desc'
        self.process_manager.set_sort_config(self.process_manager._sort_by, order)
        print(f"ソート順序: {order}")
    
    def on_mouse_press(self, x, y, button, modifiers):
        """Handle mouse press"""
        if button == pyglet.window.mouse.LEFT:
            for fish in self.fishes.values():
                dx, dy = x - fish.x, y - fish.y
                if math.sqrt(dx*dx + dy*dy) < fish.current_size + 5:
                    self.selected_fish = fish
                    print(f"選択: {fish.name} (PID: {fish.pid}, CPU: {fish.cpu_percent:.1f}%, Mem: {fish.memory_percent:.1f}%)")
                    
                    self.highlighted_partners = []
                    if fish.pid in self.ipc_connections:
                        for tgt, _ in self.ipc_connections[fish.pid]:
                            self.highlighted_partners.append(tgt)
                    return
            
            self.selected_fish = None
            self.highlighted_partners = []
    
    def toggle_fullscreen(self):
        """Toggle fullscreen"""
        self._fullscreen = not self._fullscreen
        self.window.set_fullscreen(self._fullscreen)
        print(f"フルスクリーン: {'オン' if self._fullscreen else 'オフ'}")
    
    def run(self):
        """Run main loop"""
        if self.headless:
            self.run_headless()
            return
        
        print("=== Digital Life Aquarium (Pyglet GPU-accelerated) ===")
        print("🐠 プロセスが生命体として水族館に現れるまでお待ちください...")
        print("💡 ヒント: プロセス名によって色が決まり、CPU使用時に光ります")
        print("🚀 GPU acceleration enabled!")
        pyglet.app.run()
        print("🌙 水族館を閉館しました。お疲れさまでした！")
    
    def run_headless(self):
        """Run headless loop"""
        last_print = 0.0
        try:
            while self.running:
                start = time.time()
                self.process_manager.update()
                stats = self.process_manager.get_process_statistics()
                now = time.time()
                if now - last_print >= self.headless_interval:
                    last_print = now
                    print(f"[{time.strftime('%H:%M:%S')}] プロセス: {stats['total']} (新規: {stats['new']}, 終了: {stats['dying']})")
                
                elapsed = time.time() - start
                remaining = self.headless_interval - elapsed
                if remaining > 0:
                    time.sleep(remaining)
        except KeyboardInterrupt:
            print("[Headless] 中断されました。終了します。")


def main():
    """Main function"""
    aquarium = Aquarium()
    aquarium.run()


if __name__ == "__main__":
    main()
