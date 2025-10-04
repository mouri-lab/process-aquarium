"""
fish_pyglet.py

このファイルは `fish_pygame.py` をほぼそのままコピーした上で、pygame 依存コードをコメントアウトし、
pyglet で段階的に置き換えていくための雛形です。

方針 / POLICY:
 1. ロジック・パラメータ・プロパティ計算は pygame 版と同一を維持（順序/式変更なし）
 2. pygame 描画(API: pygame.draw / Surface / font 等) は行単位でコメントアウトし、直後に TODO: の形で pyglet 移植メモを残す
 3. 仮描画は簡易な circle だけ（shapes.Circle）で最小限の可視化を確保
 4. メソッドシグネチャは draw(surface, font) -> draw(batch, font=None) に暫定変更
 5. 将来 tail / fins / speech bubble / lightning などは pyglet.graphics / shapes / text.Label / custom vertex list で復元予定

移植完了後に残るべき # TODO: ラベル例:
  - TODO[draw-shape]: 本来の複雑な魚形状を再構築
  - TODO[speech-bubble]: 吹き出しを pyglet.text.Label + 背景矩形で実装
  - TODO[effect-lightning]: 稲妻エフェクトのポリライン描画

現状の制限 / CURRENT LIMITATIONS:
  - 透明度(alpha) は shapes.Circle.opacity のみで簡易適用
  - サテライト(スレッド衛星) も簡易 circle
  - すべての pygame 由来コードはコメント保持（git diff で比較容易）

この段階では「動くが見た目は簡易」ことを優先し、正確な描画再現は後続コミットで行います。
"""

import math
import random
import time
from typing import Tuple, Optional, List

try:
	import pyglet
	from pyglet import shapes
except Exception:  # pragma: no cover
	pyglet = None  # type: ignore
	shapes = None  # type: ignore

# 新規: 共通描画ユーティリティ (Task#2 完了分) を利用
try:
	from .pyglet_draw_utils import (
		draw_ellipse,
		draw_polygon,
		draw_ripples,
		draw_lightning_polyline,
		draw_speech_bubble,
	)
except Exception:  # pragma: no cover
	# 依存失敗時は None をセットし後続でガード
	draw_ellipse = draw_polygon = draw_ripples = draw_lightning_polyline = draw_speech_bubble = None  # type: ignore


class Fish:
	"""pygame 版 Fish クラスのロジックを保持したまま pyglet 描画へ段階移行するクラス"""

	def __init__(self, pid: int, name: str, x: float, y: float):
		# ==== (以下、元 pygame 版ロジックをそのまま維持) ==== #
		self.pid = pid
		self.name = name
		self.process_name = name
		self.parent_pid: Optional[int] = None
		self.creation_time = time.time()

		self.x = x
		self.y = y
		self.vx = random.uniform(-1, 1)
		self.vy = random.uniform(-1, 1)
		self.target_x = x
		self.target_y = y

		self.angle = 0.0
		self.tail_swing = 0.0
		self.swim_cycle = 0.0
		self.fish_shape = self._determine_fish_shape(name)

		self.school_members: List[int] = []
		self.is_leader = False
		self.flocking_strength = 0.8
		self.separation_distance = 30.0
		self.alignment_distance = 50.0
		self.cohesion_distance = 70.0

		self.ipc_attraction_x = 0.0
		self.ipc_attraction_y = 0.0

		self.base_size = 10
		self.current_size = self.base_size
		self.color = self._generate_color()
		self.alpha = 255
		self.glow_intensity = 0
		self.is_memory_giant = False
		self.pulsation_phase = 0.0

		self.memory_percent = 0.0
		self.cpu_percent = 0.0
		self.thread_count = 1
		self.age = 0

		self.is_spawning = True
		self.spawn_progress = 0.0
		self.is_dying = False
		self.death_progress = 0.0

		self.recently_forked = False
		self.fork_glow_timer = 0
		self.exec_transition = False
		self.exec_timer = 0

		self.is_talking = False
		self.talk_timer = 0
		self.talk_message = ""
		self.talk_partners: List[int] = []
		self.bubble_rect = None

	# ----------------------------------------------------------------------------------
	# Utility / attribute computation (unchanged)
	# ----------------------------------------------------------------------------------
	def _generate_color(self) -> Tuple[int, int, int]:
		hash_value = hash(self.name) % 360
		saturation = 0.7
		value = 0.9
		h = hash_value / 360.0
		s = saturation
		v = value
		if s == 0.0:
			r = g = b = v
		else:
			i = int(h * 6.0)
			f = (h * 6.0) - i
			p = v * (1.0 - s)
			q = v * (1.0 - s * f)
			t = v * (1.0 - s * (1.0 - f))
			if i % 6 == 0:
				r, g, b = v, t, p
			elif i % 6 == 1:
				r, g, b = q, v, p
			elif i % 6 == 2:
				r, g, b = p, v, t
			elif i % 6 == 3:
				r, g, b = p, q, v
			elif i % 6 == 4:
				r, g, b = t, p, v
			else:
				r, g, b = v, p, q
		return (int(r * 255), int(g * 255), int(b * 255))

	def _determine_fish_shape(self, process_name: str) -> str:
		name_lower = process_name.lower()
		if any(browser in name_lower for browser in ['chrome', 'firefox', 'safari', 'edge']):
			return 'shark'
		elif any(dev in name_lower for dev in ['code', 'vscode', 'atom', 'sublime', 'vim']):
			return 'tropical'
		elif any(sys in name_lower for sys in ['kernel', 'system', 'daemon', 'service']):
			return 'ray'
		elif any(comm in name_lower for comm in ['zoom', 'slack', 'discord', 'teams']):
			return 'dolphin'
		elif any(heavy in name_lower for heavy in ['photoshop', 'docker', 'virtualbox']):
			return 'whale'
		elif any(term in name_lower for term in ['terminal', 'bash', 'zsh', 'cmd']):
			return 'eel'
		else:
			return 'fish'

	# ----------------------------------------------------------------------------------
	# Process related data update (unchanged logic)
	# ----------------------------------------------------------------------------------
	def update_process_data(self, memory_percent: float, cpu_percent: float, thread_count: int, parent_pid: Optional[int] = None):
		self.memory_percent = memory_percent
		self.cpu_percent = cpu_percent
		self.thread_count = thread_count
		self.parent_pid = parent_pid
		memory_normalized = memory_percent / 100.0
		if memory_normalized > 0:
			raw_factor = math.exp(8 * memory_normalized)
			memory_factor = min(raw_factor, 60.0)
		else:
			memory_factor = 1.0
		self.current_size = self.base_size * memory_factor
		self.is_memory_giant = memory_percent >= 5.0 or memory_factor >= 5.0
		cpu_normalized = cpu_percent / 100.0
		glow_factor = (math.exp(3 * cpu_normalized) - 1) / (math.exp(3) - 1)
		self.glow_intensity = min(glow_factor * 255, 255)
		speed_factor = 1.0 + (math.exp(4 * cpu_normalized) - 1) / (math.exp(4) - 1) * 6.0
		max_speed = 2.0 * min(speed_factor, 8.0)
		self.vx = max(min(self.vx, max_speed), -max_speed)
		self.vy = max(min(self.vy, max_speed), -max_speed)

	# ----------------------------------------------------------------------------------
	# Event flags
	# ----------------------------------------------------------------------------------
	def set_fork_event(self):
		self.recently_forked = True
		self.fork_glow_timer = 60

	def set_exec_event(self):
		self.exec_transition = True
		self.exec_timer = 30
		self.color = self._generate_color()

	def set_death_event(self):
		if not self.is_dying:
			self.is_dying = True
			self.death_progress = 0.0

	# ----------------------------------------------------------------------------------
	# Motion & flocking
	# ----------------------------------------------------------------------------------
	def update_position(self, screen_width: int, screen_height: int, nearby_fish: List['Fish'] = None):
		self.age += 1
		if self.is_memory_giant:
			self.pulsation_phase += 0.15
			if self.pulsation_phase > 2 * math.pi:
				self.pulsation_phase -= 2 * math.pi
		if self.is_spawning:
			self.spawn_progress += 0.05
			if self.spawn_progress >= 1.0:
				self.is_spawning = False
				self.spawn_progress = 1.0
		if self.is_dying:
			self.death_progress += 0.03
			return self.death_progress < 1.0
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
			if self.talk_timer == 0:
				self.is_talking = False
				self.talk_message = ""
				self.bubble_rect = None
		flocking_force_x = 0.0
		flocking_force_y = 0.0
		if nearby_fish and self.school_members:
			school_fish = [f for f in nearby_fish if f.pid in self.school_members]
			if school_fish:
				flocking_force_x, flocking_force_y = self.calculate_flocking_forces(school_fish)
		if not self.school_members and random.random() < 0.01:
			self.target_x = random.uniform(50, screen_width - 50)
			self.target_y = random.uniform(50, screen_height - 50)
		if self.school_members:
			self.vx += flocking_force_x * self.flocking_strength
			self.vy += flocking_force_y * self.flocking_strength
		else:
			dx = self.target_x - self.x
			dy = self.target_y - self.y
			distance = math.sqrt(dx*dx + dy*dy)
			if distance > 5:
				self.vx += dx * 0.001
				self.vy += dy * 0.001
		self.vx *= 0.98
		self.vy *= 0.98
		self.vx += self.ipc_attraction_x
		self.vy += self.ipc_attraction_y
		self.x += self.vx
		self.y += self.vy
		if self.x <= self.current_size or self.x >= screen_width - self.current_size:
			self.vx *= -0.8
			self.x = max(self.current_size, min(screen_width - self.current_size, self.x))
		if self.y <= self.current_size or self.y >= screen_height - self.current_size:
			self.vy *= -0.8
			self.y = max(self.current_size, min(screen_height - self.current_size, self.y))
		return True

	# ----------------------------------------------------------------------------------
	# Display attribute calculations
	# ----------------------------------------------------------------------------------
	def get_display_color(self) -> Tuple[int, int, int]:
		r, g, b = self.color
		if self.is_memory_giant:
			red_boost = int(50 * (1.0 + 0.5 * math.sin(self.pulsation_phase)))
			r = min(255, r + red_boost)
			b = max(0, b - 20)
		if self.recently_forked:
			glow_factor = self.fork_glow_timer / 60.0
			r = int(r + (255 - r) * glow_factor)
			g = int(g + (255 - g) * glow_factor)
			b = int(b + (255 - b) * glow_factor)
		if self.glow_intensity > 0:
			intensity = self.glow_intensity / 255.0
			glow_boost = (math.exp(3 * intensity) - 1) / (math.exp(3) - 1) * 150
			r = min(255, int(r + glow_boost))
			g = min(255, int(g + glow_boost))
			b = min(255, int(b + glow_boost))
		if self.exec_transition:
			transition_factor = 1.0 - (self.exec_timer / 30.0)
			rainbow_shift = int(transition_factor * 180)
			r = (r + rainbow_shift) % 255
			g = (g + rainbow_shift) % 255
			b = (b + rainbow_shift) % 255
		return (r, g, b)

	def get_display_alpha(self) -> int:
		alpha = self.alpha
		if self.is_spawning:
			alpha = int(255 * self.spawn_progress)
		if self.is_dying:
			alpha = int(255 * (1.0 - self.death_progress))
		return alpha

	def get_display_size(self) -> float:
		size = self.current_size
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

	# ----------------------------------------------------------------------------------
	# Satellites (threads) simplified placeholder
	# ----------------------------------------------------------------------------------
	def get_thread_satellites(self) -> list:
		satellites = []
		if self.thread_count > 1:
			thread_normalized = min(self.thread_count / 16.0, 1.0)
			satellite_factor = (math.exp(2 * thread_normalized) - 1) / (math.exp(2) - 1)
			satellite_count = max(1, min(int((self.thread_count - 1) * (1 + satellite_factor)), 16))
			for i in range(satellite_count):
				angle = (2 * math.pi * i) / satellite_count + self.age * 0.02
				radius_multiplier = 1.5 + (self.thread_count / 16.0) * 2.0
				radius = self.current_size * radius_multiplier
				sat_x = self.x + math.cos(angle) * radius
				sat_y = self.y + math.sin(angle) * radius
				satellites.append((sat_x, sat_y))
		return satellites

	# ----------------------------------------------------------------------------------
	# Flocking helpers (unchanged logic)
	# ----------------------------------------------------------------------------------
	def set_school_members(self, member_pids: List[int], is_leader: bool = False):
		self.school_members = member_pids
		self.is_leader = is_leader

	def calculate_flocking_forces(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
		if not nearby_fish:
			return 0.0, 0.0
		sep_x, sep_y = self._calculate_separation(nearby_fish)
		ali_x, ali_y = self._calculate_alignment(nearby_fish)
		coh_x, coh_y = self._calculate_cohesion(nearby_fish)
		separation_weight = 2.0
		alignment_weight = 1.0
		cohesion_weight = 1.0
		force_x = (sep_x * separation_weight + ali_x * alignment_weight + coh_x * cohesion_weight)
		force_y = (sep_y * separation_weight + ali_y * alignment_weight + coh_y * cohesion_weight)
		max_force = 0.5
		force_magnitude = math.sqrt(force_x**2 + force_y**2)
		if force_magnitude > max_force:
			force_x = (force_x / force_magnitude) * max_force
			force_y = (force_y / force_magnitude) * max_force
		return force_x, force_y

	def _calculate_separation(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
		force_x = 0.0
		force_y = 0.0
		count = 0
		for fish in nearby_fish:
			distance = math.sqrt((self.x - fish.x)**2 + (self.y - fish.y)**2)
			if 0 < distance < self.separation_distance:
				diff_x = self.x - fish.x
				diff_y = self.y - fish.y
				weight = self.separation_distance / distance
				force_x += diff_x * weight
				force_y += diff_y * weight
				count += 1
		if count > 0:
			force_x /= count
			force_y /= count
		return force_x, force_y

	def _calculate_alignment(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
		avg_vx = 0.0
		avg_vy = 0.0
		count = 0
		for fish in nearby_fish:
			distance = math.sqrt((self.x - fish.x)**2 + (self.y - fish.y)**2)
			if 0 < distance < self.alignment_distance:
				avg_vx += fish.vx
				avg_vy += fish.vy
				count += 1
		if count > 0:
			avg_vx /= count
			avg_vy /= count
			force_x = avg_vx - self.vx
			force_y = avg_vy - self.vy
			return force_x, force_y
		return 0.0, 0.0

	def _calculate_cohesion(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
		center_x = 0.0
		center_y = 0.0
		count = 0
		for fish in nearby_fish:
			distance = math.sqrt((self.x - fish.x)**2 + (self.y - fish.y)**2)
			if 0 < distance < self.cohesion_distance:
				center_x += fish.x
				center_y += fish.y
				count += 1
		if count > 0:
			center_x /= count
			center_y /= count
			force_x = (center_x - self.x) * 0.01
			force_y = (center_y - self.y) * 0.01
			return force_x, force_y
		return 0.0, 0.0

	# ----------------------------------------------------------------------------------
	# Drawing (pygame code commented, placeholder pyglet drawing provided)
	# ----------------------------------------------------------------------------------
	def draw(self, batch, font=None):  # font kept for interface parity (unused now)
		"""忠実描画: pygame版 Fish.draw のロジックを pyglet に移植 (Task#3)。"""
		if self.death_progress >= 1.0:
			return
		size = self.get_display_size()
		if size < 2:
			return
		color = self.get_display_color()
		alpha = self.get_display_alpha()
		if not (pyglet and draw_ellipse and draw_polygon):
			return  # pyglet 利用不可時は描画スキップ

		# 角度更新 (pygame版 _draw_fish_shape 冒頭と同等)
		if abs(self.vx) > 0.1 or abs(self.vy) > 0.1:
			target_angle = math.atan2(self.vy, self.vx)
			angle_diff = target_angle - self.angle
			if angle_diff > math.pi:
				angle_diff -= 2 * math.pi
			elif angle_diff < -math.pi:
				angle_diff += 2 * math.pi
			self.angle += angle_diff * 0.1

		# 泳ぎアニメーション (元ロジック)
		speed = math.sqrt(self.vx**2 + self.vy**2)
		cpu_factor = 1.0
		if hasattr(self, 'cpu_percent'):
			cpu_normalized = self.cpu_percent / 100.0
			cpu_factor = 1.0 + (math.exp(2 * cpu_normalized) - 1) / (math.exp(2) - 1) * 4.0
		swim_speed = (0.1 + speed * 0.1) * cpu_factor
		self.swim_cycle += swim_speed
		tail_intensity = (0.2 + speed * 0.1) * cpu_factor
		self.tail_swing = math.sin(self.swim_cycle) * min(tail_intensity, 1.0)

		# メモリ巨大魚エフェクト (Task#4 で微調整予定)
		if self.is_memory_giant and alpha > 20:
			# pygame _draw_memory_giant_effects に近い波紋：4枚, 半径: size*(3.0 + i*1.2)*(1+0.5*sin(phase+i*pi/4))
			if draw_ripples:
				for i in range(4):
					phase = self.pulsation_phase + i * (math.pi/4)
					radius = self.current_size * (3.0 + i * 1.2) * (1.0 + 0.5 * math.sin(phase))
					layer_alpha = max(8, int((alpha // 8) * (1.0 - i * 0.2)))
					# 個別にアウトライン円 (draw_ripples の汎用ではなく ellipse_outline 相当)
					if radius > 0 and layer_alpha > 0 and draw_ellipse:
						# アウトライン -> 近似: 薄い線; outline専用が無いので外周ポリゴン+低alpha
						# 極細リング再現は後続最適化; まず1px相当で塗りつぶし半透明近似
						draw_ellipse(self.x, self.y, radius, radius, (255, 100, 100, layer_alpha))
			# 雷: 30フレーム周期 or ランダム (≈元条件)
			if self.memory_percent >= 20.0 and draw_lightning_polyline:
				if not hasattr(self, '_lightning_timer'):
					self._lightning_timer = 0
				self._lightning_timer += 1
				if (self._lightning_timer % 30 == 0) or (random.random() < 0.1):
						# --- Lightning bolts ---
						bolts = random.randint(3, 5)
						for _ in range(bolts):
							angle = random.uniform(0, 2 * math.pi)
							start_radius = self.current_size * 0.8
							end_radius = self.current_size * 2.5
							cx = self.x + math.cos(angle) * start_radius
							cy = self.y + math.sin(angle) * start_radius
							length = end_radius - start_radius
							seg_alpha = max(100, alpha // 2)
							segments = 4
							pts = []
							for s in range(segments + 1):
								t = s / segments
								r = length * t
								mid_x = cx + math.cos(angle) * r
								mid_y = cy + math.sin(angle) * r
								if 0 < s < segments:
									mid_x += random.uniform(-20, 20)
									mid_y += random.uniform(-20, 20)
								pts.extend([mid_x, mid_y])
							try:
								pyglet.graphics.draw(len(pts)//2, pyglet.gl.GL_LINE_STRIP,
									('v2f', pts),
									('c4B', (255, 255, 150, seg_alpha) * (len(pts)//2)))
							except Exception:
								pass

		body_length = size * 1.8
		body_width = size * 0.9
		if self.fish_shape == 'shark':
			self._draw_shark(color, alpha, body_length, body_width)
		elif self.fish_shape == 'tropical':
			self._draw_tropical_fish(color, alpha, body_length, body_width)
		elif self.fish_shape == 'ray':
			self._draw_ray(color, alpha, body_length * 1.2, body_width * 1.5)
		elif self.fish_shape == 'dolphin':
			self._draw_dolphin(color, alpha, body_length, body_width)
		elif self.fish_shape == 'whale':
			self._draw_whale(color, alpha, body_length * 1.3, body_width * 1.2)
		elif self.fish_shape == 'eel':
			self._draw_eel(color, alpha, body_length * 2.0, body_width * 0.4)
		else:
			self._draw_generic_fish(color, alpha, body_length, body_width)

		if self.thread_count > 1 and size > 5 and shapes:
			satellites = self.get_thread_satellites()
			max_display = min(len(satellites), max(4, self.thread_count // 2))
			for idx, (sat_x, sat_y) in enumerate(satellites[:max_display]):
				# pygame版 _draw_small_fish のスケーリングロジックに合わせる
				thread_size_factor = 1.0 + (self.thread_count / 16.0) * 1.5
				sat_size = max(2, size * 0.2 * thread_size_factor)
				self._draw_thread_satellite_fish(sat_x, sat_y, sat_size, color, alpha//2)

		if self.is_talking and self.talk_message and alpha > 50 and pyglet and draw_speech_bubble:
			# 簡易テキスト折り返し：最大幅 ~ 160px 相当 (文字幅6px換算)
			max_chars_line = 26
			words = []
			text_src = self.talk_message[:120]
			for i in range(0, len(text_src), max_chars_line):
				words.append(text_src[i:i+max_chars_line])
			lines = words[:3]  # 最大3行（pygameは短文想定）
			line_height = 12
			bubble_w = max(40, min(180, max(len(l) for l in lines) * 6 + 12))
			bubble_h = len(lines) * line_height + 10
			bubble_x = self.x - bubble_w / 2
			bubble_y = self.y + size + 20  # pygame基準: 魚上に +20
			# 画面境界補正 (Window サイズ不明のため負側のみ最低限)
			if bubble_x < 4:
				bubble_x = 4
			# 二層＋テール
			draw_speech_bubble(bubble_x, bubble_y, bubble_w, bubble_h, bubble_x + bubble_w/2, 10,
						   (0, 0, 0, 180), (255, 255, 255, 220), batch, inner=True)
			if hasattr(pyglet, 'text'):
				for idx, line in enumerate(lines):
					pyglet.text.Label(line, font_size=10, x=bubble_x + 5, y=bubble_y + bubble_h - 5 - idx * line_height,
							  anchor_y='top', color=(0, 0, 0, 255), batch=batch)
			self.bubble_rect = (bubble_x, bubble_y, bubble_w, bubble_h)

		# === Original pygame drawing logic (commented) ===
		# (保持理由: 差分比較 & TODO の参照)
		# def draw(self, screen: pygame.Surface, font: pygame.font.Font = None):
		#     if self.death_progress >= 1.0: return
		#     color = self.get_display_color()
		#     alpha = self.get_display_alpha()
		#     size = self.get_display_size()
		#     if size < 2: return
		#     if self.is_memory_giant and hasattr(self, 'memory_percent'):
		#         if self.memory_percent >= 5.0:
		#             self._draw_memory_giant_effects(screen, alpha)  # TODO[effect-ripple]
		#         if self.memory_percent >= 20.0:
		#             self._draw_lightning_effects(screen, alpha)     # TODO[effect-lightning]
		#     if alpha > 20:
		#         self._draw_fish_shape(screen, color, alpha, size)  # TODO[draw-shape]
		#     if self.thread_count > 1 and size > 5:
		#         for sat_x, sat_y in self.get_thread_satellites():
		#             pass  # TODO[draw-satellites]
		#     if self.is_talking and self.talk_message:
		#         self._draw_speech_bubble(screen, self.talk_message, font)  # TODO[speech-bubble]

	# (以下の pygame 個別描画メソッドは完全コメントアウト: 後で段階移植)
	# TODO[effect-ripple]: _draw_memory_giant_effects を pyglet port
	# TODO[effect-lightning]: _draw_lightning_effects を pyglet port
	# TODO[draw-shape]: 各 _draw_* 魚形状関数を pyglet port (一部実装済 Task#3)
	# TODO[speech-bubble]: _draw_speech_bubble を pyglet port

	# 例: オリジナル関数ヘッダのみ保持
	# def _draw_memory_giant_effects(...): pass
	# def _draw_lightning_effects(...): pass
	# def _draw_small_fish(...): pass
	# def _draw_shark(...): pass
	# def _draw_tropical_fish(...): pass
	# def _draw_ray(...): pass
	# def _draw_dolphin(...): pass
	# def _draw_whale(...): pass
	# def _draw_eel(...): pass
	# def _draw_generic_fish(...): pass
	# def _draw_speech_bubble(...): pass

	# ----------------------------------------------------------------------------------
	# Conversation / talking placeholders
	# ----------------------------------------------------------------------------------
	def start_talking(self, message: str, partner_pid: int):
		self.is_talking = True
		self.talk_message = message
		self.talk_timer = 60
		self.talk_partners = [partner_pid]

	# ----------------------------------------------------------------------------------
	# Pyglet drawing helpers (new)
	# ----------------------------------------------------------------------------------
	def _draw_generic_with_tail(self, batch, color, alpha, body_length, body_width, tail_scale=0.7, thin=False):
		if not shapes:
			return
		# Body (ellipse approximation => multiple overlapping circles for softness)
		segments = 3 if not thin else 2
		for i in range(segments):
			t = i / max(1, segments - 1)
			w = body_width * (0.9 - 0.4 * abs(t - 0.5))
			cx = self.x + (t - 0.5) * body_length * math.cos(self.angle)
			cy = self.y + (t - 0.5) * body_length * math.sin(self.angle)
			c = shapes.Circle(cx, cy, max(2, w / 2), color=color, batch=batch)
			c.opacity = alpha
		# Tail (triangle pair)
		tail_len = body_length * tail_scale
		cos_a = math.cos(self.angle)
		sin_a = math.sin(self.angle)
		base_x = self.x - 0.4 * body_length * cos_a
		base_y = self.y - 0.4 * body_length * sin_a
		swing = self.tail_swing
		spread = body_width * (0.6 if not thin else 0.4)
		tip_x = base_x - tail_len * cos_a + swing * spread * sin_a
		tip_y = base_y - tail_len * sin_a - swing * spread * cos_a
		left_x = base_x - tail_len * 0.6 * cos_a + spread * sin_a
		left_y = base_y - tail_len * 0.6 * sin_a - spread * cos_a
		right_x = base_x - tail_len * 0.6 * cos_a - spread * sin_a
		right_y = base_y - tail_len * 0.6 * sin_a + spread * cos_a
		# Two triangles to emulate split tail
		verts1 = [base_x, base_y, left_x, left_y, tip_x, tip_y]
		verts2 = [base_x, base_y, right_x, right_y, tip_x, tip_y]
		# pyglet.draw は vertex count を最初の引数に取る
		pyglet.graphics.draw(3, pyglet.gl.GL_TRIANGLES, ('v2f', verts1), ('c3B', color * 3))
		pyglet.graphics.draw(3, pyglet.gl.GL_TRIANGLES, ('v2f', verts2), ('c3B', color * 3))

	# ----------------------------------------------------------------------------------
	# Faithful shape ports (pygame -> pyglet)
	# ----------------------------------------------------------------------------------
	def _draw_shark(self, color, alpha, body_length, body_width):
		# Body ellipse (axis-aligned like pygame)
		draw_ellipse(self.x, self.y, body_length/2, body_width/2, color + (alpha,))
		tail_length = body_length * 0.7
		tail_angle = self.angle + math.pi / 2 + self.tail_swing
		px2 = self.x + math.cos(tail_angle) * tail_length
		py2 = self.y + math.sin(tail_angle) * tail_length
		px3 = self.x + math.cos(tail_angle) * tail_length * 0.8
		py3 = self.y + math.sin(tail_angle) * tail_length * 0.8
		draw_polygon([(self.x, self.y), (px2, py2), (px3, py3)], color + (alpha,))

	def _draw_tropical_fish(self, color, alpha, body_length, body_width):
		draw_ellipse(self.x, self.y, body_length/2, body_width/2, color + (alpha,))
		tail_length = body_length * 0.6
		tail_angle = self.angle + math.pi / 2 + self.tail_swing
		px2 = self.x + math.cos(tail_angle) * tail_length
		py2 = self.y + math.sin(tail_angle) * tail_length
		px3 = self.x + math.cos(tail_angle) * tail_length * 0.7
		py3 = self.y + math.sin(tail_angle) * tail_length * 0.7
		draw_polygon([(self.x, self.y), (px2, py2), (px3, py3)], color + (alpha,))
		# dorsal/fin (simple adaptation of tropical fin from pygame)
		fin_length = body_length * 0.4
		fin_angle = self.angle - math.pi / 2 + self.tail_swing
		fx2 = self.x + math.cos(fin_angle) * fin_length
		fy2 = self.y + math.sin(fin_angle) * fin_length
		fx3 = self.x + math.cos(fin_angle) * fin_length * 0.8
		fy3 = self.y + math.sin(fin_angle) * fin_length * 0.8
		draw_polygon([(self.x, self.y), (fx2, fy2), (fx3, fy3)], color + (alpha,))

	def _draw_ray(self, color, alpha, body_length, body_width):
		# Ray body
		draw_ellipse(self.x, self.y, body_length/2, body_width/2, color + (alpha,))
		tail_length = body_length * 0.8
		tail_angle = self.angle + math.pi + self.tail_swing
		px2 = self.x + math.cos(tail_angle) * tail_length
		py2 = self.y + math.sin(tail_angle) * tail_length
		px3 = self.x + math.cos(tail_angle) * tail_length * 0.9
		py3 = self.y + math.sin(tail_angle) * tail_length * 0.9
		draw_polygon([(self.x, self.y), (px2, py2), (px3, py3)], color + (alpha,))

	def _draw_dolphin(self, color, alpha, body_length, body_width):
		self._draw_tropical_fish(color, alpha, body_length, body_width)  # shares structure with extra fin length
		# Adjust fin length difference already minor; treat same for first pass.

	def _draw_whale(self, color, alpha, body_length, body_width):
		draw_ellipse(self.x, self.y, body_length/2, body_width/2, color + (alpha,))
		tail_length = body_length * 0.9
		tail_angle = self.angle + math.pi / 2 + self.tail_swing
		px2 = self.x + math.cos(tail_angle) * tail_length
		py2 = self.y + math.sin(tail_angle) * tail_length
		px3 = self.x + math.cos(tail_angle) * tail_length * 0.8
		py3 = self.y + math.sin(tail_angle) * tail_length * 0.8
		draw_polygon([(self.x, self.y), (px2, py2), (px3, py3)], color + (alpha,))

	def _draw_eel(self, color, alpha, body_length, body_width):
		draw_ellipse(self.x, self.y, body_length/2, body_width/2, color + (alpha,))
		tail_length = body_length * 0.5
		tail_angle = self.angle + math.pi / 2 + self.tail_swing
		px2 = self.x + math.cos(tail_angle) * tail_length
		py2 = self.y + math.sin(tail_angle) * tail_length
		px3 = self.x + math.cos(tail_angle) * tail_length * 0.7
		py3 = self.y + math.sin(tail_angle) * tail_length * 0.7
		draw_polygon([(self.x, self.y), (px2, py2), (px3, py3)], color + (alpha,))

	def _draw_generic_fish(self, color, alpha, body_length, body_width):
		# main body ellipse (0.8 * length portion like pygame main_body_rect width)
		main_len = body_length * 0.8
		draw_ellipse(self.x - body_length*0.1, self.y, main_len/2, body_width/2, color + (alpha,))
		# head (0.3 length *0.6 width) positioned forward
		head_len = body_length * 0.3
		head_w = body_width * 0.6
		draw_ellipse(self.x + body_length*0.35, self.y, head_len/2, head_w/2, color + (alpha,))
		# Tail split triangles replicating pygame generic
		cos_a = math.cos(self.angle)
		sin_a = math.sin(self.angle)
		tail_x = self.x - cos_a * body_length * 0.4
		tail_y = self.y - sin_a * body_length * 0.4
		tail_size = body_width * 0.5
		swing = self.tail_swing
		upper = [
			(tail_x, tail_y),
			(tail_x - cos_a * tail_size * 1.2 + sin_a * tail_size * 0.3 * swing,
			 tail_y - sin_a * tail_size * 1.2 - cos_a * tail_size * 0.3 * swing),
			(tail_x - cos_a * tail_size * 0.8, tail_y - sin_a * tail_size * 0.8)
		]
		lower = [
			(tail_x, tail_y),
			(tail_x - cos_a * tail_size * 1.2 - sin_a * tail_size * 0.3 * swing,
			 tail_y - sin_a * tail_size * 1.2 + cos_a * tail_size * 0.3 * swing),
			(tail_x - cos_a * tail_size * 0.8, tail_y - sin_a * tail_size * 0.8)
		]
		draw_polygon(upper, color + (alpha,))
		draw_polygon(lower, color + (alpha,))
		# dorsal fin (approx)
		dorsal_x = self.x - cos_a * body_length * 0.1
		dorsal_y = self.y - sin_a * body_length * 0.1
		dorsal_size = body_width * 0.3
		dorsal = [
			(dorsal_x, dorsal_y),
			(dorsal_x + sin_a * dorsal_size * 0.8, dorsal_y - cos_a * dorsal_size * 0.8),
			(dorsal_x + sin_a * dorsal_size * 0.5, dorsal_y - cos_a * dorsal_size * 0.5)
		]
		draw_polygon(dorsal, color + (alpha,))

	def _draw_thread_satellite_fish(self, x, y, size, color, alpha):
		"""pygame版 _draw_small_fish に近い衛星小魚描画"""
		if size < 2 or not draw_ellipse or not draw_polygon:
			return
		# 体 (ellipse width: 1.5*size height: size)
		body_w = size * 1.5
		body_h = size
		# draw_ellipse は中心+半径指定なので調整: 半径 = w/2, h/2
		draw_ellipse(x + (body_w*0.25), y, body_w/2, body_h/2, color + (alpha,))
		# 尾 (三角形)
		tail_points = [
			(x - size * 0.25, y),
			(x - size * 0.75, y - size/3),
			(x - size * 0.75, y + size/3)
		]
		draw_polygon(tail_points, color + (alpha,))


__all__ = ["Fish"]

