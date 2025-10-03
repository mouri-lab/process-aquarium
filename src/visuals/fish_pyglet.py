"""
Digital Life Aquarium - Fish Entity (Pyglet GPU-accelerated version)
Simplified but complete implementation with GPU acceleration
"""

import pyglet
from pyglet import gl
import math
import random
import time
from typing import Tuple, Optional, List

class Fish:
    """GPU-accelerated fish using Pyglet/OpenGL"""
    
    def __init__(self, pid: int, name: str, x: float, y: float):
        self.pid = pid
        self.name = name
        self.process_name = name
        self.parent_pid: Optional[int] = None
        self.creation_time = time.time()
        
        # Position and movement
        self.x = x
        self.y = y
        self.vx = random.uniform(-1, 1)
        self.vy = random.uniform(-1, 1)
        self.target_x = x
        self.target_y = y
        
        # Visual attributes
        self.angle = 0.0
        self.swim_cycle = 0.0
        self.fish_shape = self._determine_fish_shape(name)
        
        # Flocking behavior
        self.school_members: List[int] = []
        self.is_leader = False
        self.separation_distance = 30.0
        self.alignment_distance = 50.0
        self.cohesion_distance = 70.0
        
        # IPC attraction
        self.ipc_attraction_x = 0.0
        self.ipc_attraction_y = 0.0
        
        # Visual state
        self.base_size = 10
        self.current_size = self.base_size
        self.color = self._generate_color()
        self.alpha = 255
        self.glow_intensity = 0
        self.is_memory_giant = False
        self.pulsation_phase = 0.0
        
        # Process metrics
        self.memory_percent = 0.0
        self.cpu_percent = 0.0
        self.thread_count = 1
        self.age = 0
        
        # Animation state
        self.is_spawning = True
        self.spawn_progress = 0.0
        self.is_dying = False
        self.death_progress = 0.0
        
        # Special events
        self.recently_forked = False
        self.fork_glow_timer = 0
        self.exec_transition = False
        self.exec_timer = 0
        
        # IPC talk state
        self.is_talking = False
        self.talk_timer = 0
        self.talk_message = ""
        self.talk_partners = []
        self.bubble_rect = None
        
        # Batch for efficient rendering (only in GUI mode)
        self.batch = None
        
    def _generate_color(self) -> Tuple[int, int, int]:
        """Generate unique color based on process name"""
        hash_value = hash(self.name) % 360
        h = hash_value / 360.0
        s, v = 0.7, 0.9
        
        i = int(h * 6.0)
        f = (h * 6.0) - i
        p = v * (1.0 - s)
        q = v * (1.0 - s * f)
        t = v * (1.0 - s * (1.0 - f))
        i = i % 6
        
        if i == 0: r, g, b = v, t, p
        elif i == 1: r, g, b = q, v, p
        elif i == 2: r, g, b = p, v, t
        elif i == 3: r, g, b = p, q, v
        elif i == 4: r, g, b = t, p, v
        else: r, g, b = v, p, q
        
        return (int(r * 255), int(g * 255), int(b * 255))
    
    def _determine_fish_shape(self, process_name: str) -> str:
        """Determine fish shape from process name"""
        name_lower = process_name.lower()
        
        if any(x in name_lower for x in ['chrome', 'firefox', 'safari', 'edge']):
            return 'shark'
        elif any(x in name_lower for x in ['code', 'vscode', 'atom', 'sublime', 'vim']):
            return 'tropical'
        elif any(x in name_lower for x in ['kernel', 'system', 'daemon', 'service']):
            return 'ray'
        elif any(x in name_lower for x in ['zoom', 'slack', 'discord', 'teams']):
            return 'dolphin'
        elif any(x in name_lower for x in ['photoshop', 'docker', 'virtualbox']):
            return 'whale'
        elif any(x in name_lower for x in ['terminal', 'bash', 'zsh', 'cmd']):
            return 'eel'
        else:
            return 'fish'
    
    def start_dying(self):
        """Start death animation"""
        if not self.is_dying:
            self.is_dying = True
            self.death_progress = 0.0
    
    def update_process_data(self, memory_percent: float, cpu_percent: float,
                           thread_count: int, parent_pid: Optional[int] = None):
        """Update process metrics"""
        self.memory_percent = memory_percent
        self.cpu_percent = cpu_percent
        self.thread_count = thread_count
        self.parent_pid = parent_pid
        
        # Size based on memory (exponential)
        memory_normalized = memory_percent / 100.0
        if memory_normalized > 0:
            raw_factor = math.exp(8 * memory_normalized)
            memory_factor = min(raw_factor, 60.0)
        else:
            memory_factor = 1.0
        self.current_size = self.base_size * memory_factor
        
        self.is_memory_giant = memory_percent >= 5.0 or memory_factor >= 5.0
        
        # Glow based on CPU
        cpu_normalized = cpu_percent / 100.0
        glow_factor = (math.exp(3 * cpu_normalized) - 1) / (math.exp(3) - 1)
        self.glow_intensity = min(glow_factor * 255, 255)
        
        # Speed based on CPU
        speed_factor = 1.0 + (math.exp(4 * cpu_normalized) - 1) / (math.exp(4) - 1) * 6.0
        max_speed = 2.0 * min(speed_factor, 8.0)
        self.vx = max(min(self.vx, max_speed), -max_speed)
        self.vy = max(min(self.vy, max_speed), -max_speed)
    
    def set_fork_event(self):
        """Set fork event"""
        self.recently_forked = True
        self.fork_glow_timer = 60
    
    def set_exec_event(self):
        """Set exec event"""
        self.exec_transition = True
        self.exec_timer = 60
    
    def set_talk_state(self, is_talking: bool, message: str = "", partners: List[int] = None):
        """Set IPC talk state"""
        self.is_talking = is_talking
        self.talk_message = message if is_talking else ""
        self.talk_partners = partners if partners else []
        if is_talking:
            self.talk_timer = 180
    
    def get_display_color(self) -> Tuple[int, int, int]:
        """Get current display color with effects"""
        r, g, b = self.color
        
        # Fork glow
        if self.recently_forked and self.fork_glow_timer > 0:
            glow_factor = self.fork_glow_timer / 60.0
            r = int(r + (255 - r) * glow_factor)
            g = int(g + (255 - g) * glow_factor)
            b = int(b + (255 - b) * glow_factor)
        
        # CPU glow
        if self.glow_intensity > 0:
            intensity = self.glow_intensity / 255.0
            glow_boost = (math.exp(3 * intensity) - 1) / (math.exp(3) - 1) * 150
            r = min(255, int(r + glow_boost))
            g = min(255, int(g + glow_boost))
            b = min(255, int(b + glow_boost))
        
        return (r, g, b)
    
    def get_display_alpha(self) -> int:
        """Get current alpha with fade effects"""
        alpha = self.alpha
        
        if self.is_spawning:
            alpha = int(255 * self.spawn_progress)
        
        if self.is_dying:
            alpha = int(255 * (1.0 - self.death_progress))
        
        return alpha
    
    def get_display_size(self) -> float:
        """Get current display size with effects"""
        size = self.current_size
        
        # Pulsation for memory giants
        if self.is_memory_giant:
            pulsation = 1.0 + 0.3 * math.sin(self.pulsation_phase)
            size *= pulsation
        
        if self.is_spawning:
            spawn_scale = 0.1 + 0.9 * self.spawn_progress
            size *= spawn_scale
        
        if self.is_dying:
            death_scale = 1.0 - self.death_progress
            size *= death_scale
        
        if self.recently_forked:
            fork_scale = 1.0 + (self.fork_glow_timer / 60.0) * 0.3
            size *= fork_scale
        
        return size
    
    def update_position(self, screen_width: int, screen_height: int, nearby_fish: List['Fish']):
        """Update position with flocking behavior"""
        self.age += 1
        
        # Spawn animation
        if self.is_spawning:
            self.spawn_progress += 0.02
            if self.spawn_progress >= 1.0:
                self.is_spawning = False
                self.spawn_progress = 1.0
        
        # Death animation
        if self.is_dying:
            self.death_progress += 0.02
            self.vy += 0.5  # Sink
        
        # Timers
        if self.fork_glow_timer > 0:
            self.fork_glow_timer -= 1
            if self.fork_glow_timer == 0:
                self.recently_forked = False
        
        if self.exec_timer > 0:
            self.exec_timer -= 1
            if self.exec_timer == 0:
                self.exec_transition = False
        
        if self.talk_timer > 0:
            self.talk_timer -= 1
        
        self.pulsation_phase += 0.05
        
        # Flocking behavior
        if len(nearby_fish) > 0:
            sep_x, sep_y = self._calculate_separation(nearby_fish)
            align_x, align_y = self._calculate_alignment(nearby_fish)
            coh_x, coh_y = self._calculate_cohesion(nearby_fish)
            
            self.vx += sep_x * 0.05 + align_x * 0.03 + coh_x * 0.02
            self.vy += sep_y * 0.05 + align_y * 0.03 + coh_y * 0.02
        
        # IPC attraction
        self.vx += self.ipc_attraction_x
        self.vy += self.ipc_attraction_y
        
        # Speed limit
        speed = math.sqrt(self.vx**2 + self.vy**2)
        max_speed = 3.0
        if speed > max_speed:
            self.vx = (self.vx / speed) * max_speed
            self.vy = (self.vy / speed) * max_speed
        
        # Update position
        self.x += self.vx
        self.y += self.vy
        
        # Screen bounds
        margin = 20
        if self.x < margin:
            self.x = margin
            self.vx = abs(self.vx)
        elif self.x > screen_width - margin:
            self.x = screen_width - margin
            self.vx = -abs(self.vx)
        
        if self.y < margin:
            self.y = margin
            self.vy = abs(self.vy)
        elif self.y > screen_height - margin:
            self.y = screen_height - margin
            self.vy = -abs(self.vy)
        
        # Update angle
        if abs(self.vx) > 0.1 or abs(self.vy) > 0.1:
            self.angle = math.atan2(self.vy, self.vx)
    
    def _calculate_separation(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
        """Calculate separation force"""
        steer_x = steer_y = count = 0
        
        for other in nearby_fish:
            dx = self.x - other.x
            dy = self.y - other.y
            distance = math.sqrt(dx*dx + dy*dy)
            
            if 0 < distance < self.separation_distance:
                steer_x += dx / distance
                steer_y += dy / distance
                count += 1
        
        if count > 0:
            steer_x /= count
            steer_y /= count
        
        return steer_x, steer_y
    
    def _calculate_alignment(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
        """Calculate alignment force"""
        avg_vx = avg_vy = count = 0
        
        for other in nearby_fish:
            dx = self.x - other.x
            dy = self.y - other.y
            distance = math.sqrt(dx*dx + dy*dy)
            
            if distance < self.alignment_distance:
                avg_vx += other.vx
                avg_vy += other.vy
                count += 1
        
        if count > 0:
            avg_vx /= count
            avg_vy /= count
            return avg_vx - self.vx, avg_vy - self.vy
        
        return 0.0, 0.0
    
    def _calculate_cohesion(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
        """Calculate cohesion force"""
        center_x = center_y = count = 0
        
        for other in nearby_fish:
            dx = self.x - other.x
            dy = self.y - other.y
            distance = math.sqrt(dx*dx + dy*dy)
            
            if distance < self.cohesion_distance:
                center_x += other.x
                center_y += other.y
                count += 1
        
        if count > 0:
            center_x /= count
            center_y /= count
            return center_x - self.x, center_y - self.y
        
        return 0.0, 0.0
    
    def draw(self, font=None):
        """Draw fish using GPU-accelerated OpenGL"""
        color = self.get_display_color()
        alpha = self.get_display_alpha()
        size = self.get_display_size()
        
        # Swim animation
        speed = math.sqrt(self.vx**2 + self.vy**2)
        cpu_factor = 1.0
        if self.cpu_percent > 0:
            cpu_normalized = self.cpu_percent / 100.0
            cpu_factor = 1.0 + (math.exp(2 * cpu_normalized) - 1) / (math.exp(2) - 1) * 4.0
        
        swim_speed = (0.1 + speed * 0.1) * cpu_factor
        self.swim_cycle += swim_speed
        
        # Draw fish shape
        self._draw_fish_shape(color, alpha, size)
        
        # Draw speech bubble if talking
        if self.is_talking and self.talk_timer > 0 and font:
            self._draw_speech_bubble(font)
    
    def _draw_fish_shape(self, color: Tuple[int, int, int], alpha: int, size: float):
        """Draw fish using OpenGL"""
        gl.glPushMatrix()
        gl.glTranslatef(self.x, self.y, 0)
        gl.glRotatef(math.degrees(self.angle), 0, 0, 1)
        
        # Body (ellipse)
        segments = 20
        vertices = []
        for i in range(segments):
            angle = 2.0 * math.pi * i / segments
            rx = size * 1.2
            ry = size * 0.6
            vertices.extend([rx * math.cos(angle), ry * math.sin(angle)])
        
        gl.glColor4ub(*color, alpha)
        pyglet.graphics.draw(segments, gl.GL_TRIANGLE_FAN,
                           ('v2f', vertices))
        
        # Tail
        tail_swing = math.sin(self.swim_cycle) * 0.3
        tail_vertices = [
            -size * 0.8, 0,
            -size * 1.5, size * 0.5 * (1 + tail_swing),
            -size * 1.5, -size * 0.5 * (1 + tail_swing),
        ]
        pyglet.graphics.draw(3, gl.GL_TRIANGLES,
                           ('v2f', tail_vertices))
        
        gl.glPopMatrix()
    
    def _draw_speech_bubble(self, font):
        """Draw speech bubble (simplified)"""
        if not self.talk_message:
            return
        
        # Simplified bubble - just show text above fish
        label = pyglet.text.Label(
            self.talk_message[:30],  # Limit length
            font_name='Arial',
            font_size=10,
            x=self.x,
            y=self.y + self.current_size + 15,
            anchor_x='center',
            anchor_y='bottom',
            color=(255, 255, 255, 200)
        )
        label.draw()
