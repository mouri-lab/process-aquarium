"""
aquarium_pyglet.py

`aquarium_pygame.py` をソースそのまま基準に、まずロジック層（ProcessManager 連携 / 更新 / Flocking / IPC attraction）をコピーし、
pygame 依存描画・イベント処理を段階的に pyglet へ移植するための雛形ファイル。

方針:
 1. pygame 版の関数構造・名前・ロジック順序を可能な限り維持
 2. pygame 特有 API (pygame.display / event / Surface / draw / font 等) をコメントアウトし、対応する pyglet 代替の最小実装のみ提供
 3. 描画は現時点: 背景クリア + 各 Fish (簡易 circle) のみ
 4. UI / IPC 線 / 親子関係線 / 吹き出し / Retina / フルスクリーン / フォント適応 / パーティクル効果 などは TODO
 5. 進捗タグ: TODO[ui], TODO[ipc-lines], TODO[particles], TODO[fullscreen], TODO[font], TODO[parent-child]

制限:
  - フォント: 未実装（pyglet.text.Label への移行予定）
  - 背景グラデーション/パーティクル: 未実装
  - フルスクリーン: pyglet の window.set_fullscreen() を後で導入
  - IPC 線 / 曲線: 未実装（Batch + vertex_list 予定）

後続移植ステップ提案（別コミット予定）:
  step1: 背景グラデーション & パーティクル (pyglet.graphics + time で緩やか更新)
  step2: 魚形状詳細 (vertex_list で多角形 / fins / tail)
  step3: IPC 曲線 (二次/三次ベジェ: 補間点生成→LINE_STRIP)
  step4: 吹き出し (Label + rounded rectangle path)
  step5: 親子ライン + 選択ハイライト
  step6: Retina/スケール/フォント適応 & UI 情報パネル
  step7: パフォーマンス適応ロジック (今は保持 / 描画へ反映)

この段階では「ロジック更新」と「描画最小限」に留めます。
"""

from typing import Dict, Optional, List, Tuple
from array import array
import time
import random
import math
import os

try:
	import pyglet
	from pyglet import shapes
	from pyglet.window import key
except Exception:  # pragma: no cover
	pyglet = None  # type: ignore
	shapes = None  # type: ignore
	key = None  # type: ignore

from ..core.process_manager import ProcessManager
from .fish_pyglet import Fish


class Aquarium:
	"""pyglet 版仮実装: プロセス取得/更新ロジックは pygame 版を踏襲、描画は最小"""

	def __init__(self, width: int = 1200, height: int = 800, headless: bool = False, headless_interval: float = 1.0):
		self.headless = headless
		self.headless_interval = headless_interval
		self.width = width
		self.height = height
		self.base_width = width
		self.base_height = height
		self.fullscreen = False  # TODO[fullscreen]

		# Process / performance config (コピー)
		max_processes = int(os.environ.get('AQUARIUM_MAX_PROCESSES', '2000'))
		target_fps = int(os.environ.get('AQUARIUM_FPS', '30'))

		self.clock_target_fps = target_fps
		source = None  # eBPF 切替は後続で (psutil デフォルト)
		chosen = os.environ.get("AQUARIUM_SOURCE", "psutil").lower()
		if chosen == "ebpf":
			try:
				from ..core.sources import EbpfProcessSource
				eb = EbpfProcessSource(enable=True, hybrid_mode=True)
				if getattr(eb, 'available', False):
					source = eb
					print("[eBPF] EbpfProcessSource 有効化 (pyglet)" )
			except Exception as e:
				print(f"[eBPF] 初期化失敗 (pyglet fallback psutil): {e}")
		self.process_manager = ProcessManager(max_processes=max_processes, source=source)

		# Sorting / limiting (コピー)
		limit_str = os.environ.get("AQUARIUM_LIMIT")
		self.process_limit = int(limit_str) if limit_str else None
		self.sort_by = os.environ.get("AQUARIUM_SORT_BY", "cpu")
		self.sort_order = os.environ.get("AQUARIUM_SORT_ORDER", "desc")
		if self.process_limit is not None:
			self.process_manager.set_process_limit(self.process_limit)
		self.process_manager.set_sort_config(self.sort_by, self.sort_order)

		# Entities
		self.fishes: Dict[int, Fish] = {}
		self.selected_fish: Optional[Fish] = None
		self.highlighted_partners: List[int] = []

		# Stats
		self.total_processes = 0
		self.total_memory = 0.0
		self.avg_cpu = 0.0
		self.total_threads = 0

		# IPC
		self.ipc_connections = []
		self.ipc_update_timer = 0
		self.ipc_update_interval = 60  # frames.
		self.show_ipc = True  # TODO[ipc-lines]
		self.show_parent_lines = False

		# Performance monitor (ロジック保持)
		self.performance_monitor = {
			'fps_history': [],
			'fish_count_history': [],
			'last_adjustment': 0,
			'adaptive_particle_count': 50,
			'adaptive_fish_update_interval': 1
		}

		self.last_process_update = 0
		self.process_update_interval = 1.0
		self.last_cache_cleanup = time.time()
		self.cache_cleanup_interval = 60.0

		# pyglet window 初期化
		if not self.headless and pyglet:
			config = pyglet.gl.Config(double_buffer=True) if hasattr(pyglet.gl, 'Config') else None
			try:
				self.window = pyglet.window.Window(width=width, height=height, caption="Digital Life Aquarium (pyglet WIP)", config=config)
			except Exception:
				self.window = pyglet.window.Window(width=width, height=height, caption="Digital Life Aquarium (pyglet WIP)")
			self.window.push_handlers(self)  # on_draw / events
		else:
			self.window = None

		# Batch for drawing
		self.batch = pyglet.graphics.Batch() if (pyglet and not headless) else None
		self.bg_batch = pyglet.graphics.Batch() if (pyglet and not headless) else None

		# 背景パーティクル (上昇泡) 初期化
		self.background_particles = []  # dict: x,y,size,speed,alpha
		if not self.headless and pyglet:
			self._init_background_particles()

		self.running = True

		if not self.headless and pyglet:
			pyglet.clock.schedule_interval(self._scheduled_update, 1 / max(1, target_fps))
			print("=== Digital Life Aquarium (pyglet WIP) 起動 ===")
		elif self.headless:
			print("[Headless|pyglet] モード起動。Ctrl+C で終了")

	# ----------------------------------------------------------------------------------
	# pyglet イベント: 描画
	# ----------------------------------------------------------------------------------
	def on_draw(self):  # pyglet callback
		if self.headless or not self.window:
			return
		self.window.clear()
		# 背景グラデーション & パーティクル
		self._draw_background()
		# 親子ライン TODO[parent-child]
		# IPC ライン描画
		self._draw_ipc_connections()
		if self.batch:
			self.batch = pyglet.graphics.Batch()  # 再構築（簡易: その都度）
			for fish in self.fishes.values():
				fish.draw(self.batch)
			self.batch.draw()
		# 選択ハイライト
		if self.selected_fish:
			sf = self.selected_fish
			radius = max(8, sf.get_display_size() + 8)
			hl = shapes.Circle(sf.x, sf.y, radius, color=(255, 255, 255))
			hl.opacity = 40
			hl.draw()
		# 親子ライン
		self._draw_parent_child_lines()
		# UI TODO[ui]
		self._draw_ui()

	# ----------------------------------------------------------------------------------
	# pyglet イベント: マウス
	# ----------------------------------------------------------------------------------
	def on_mouse_press(self, x, y, button, modifiers):  # noqa: D401
		if self.headless:
			return
		# 左クリック: 最も近い fish を選択
		if button == 1:
			self._select_fish_at(x, y)

	def on_key_press(self, symbol, modifiers):
		if self.headless or not pyglet or key is None:
			return
		if symbol == key.ESCAPE:
			self.running = False
			if self.window:
				self.window.close()
		elif symbol == key.I:
			self.show_ipc = not self.show_ipc
			state = 'オン' if self.show_ipc else 'オフ'
			print(f"IPC可視化: {state}")
		elif symbol == key.P:
			self.show_parent_lines = not self.show_parent_lines
			state = 'オン' if self.show_parent_lines else 'オフ'
			print(f"親子ライン: {state}")
		elif symbol in (key.F, getattr(key, 'F11', None)):
			self.toggle_fullscreen()

	def _select_fish_at(self, x: float, y: float):
		self.selected_fish = None
		min_distance = float('inf')
		for fish in self.fishes.values():
			distance = math.sqrt((fish.x - x)**2 + (fish.y - y)**2)
			if distance < fish.current_size + 10 and distance < min_distance:
				min_distance = distance
				self.selected_fish = fish

	# ----------------------------------------------------------------------------------
	# 更新スケジュール (pyglet.clock から呼ばれる)
	# ----------------------------------------------------------------------------------
	def _scheduled_update(self, dt):  # dt は未使用（元ロジック 1秒間隔などで制御）
		if not self.running:
			return
		self.update()

	# ----------------------------------------------------------------------------------
	# メインループ（ヘッドレス用）
	# ----------------------------------------------------------------------------------
	def run(self):
		if self.headless:
			last_print = 0.0
			try:
				while self.running:
					start = time.time()
					self.process_manager.update()
					stats = self.process_manager.get_process_statistics()
					self._headless_process_to_fish()
					self._update_schooling_behavior()
					self._update_ipc_connections()
					self._apply_ipc_attraction()
					now = time.time()
					if now - last_print >= self.headless_interval:
						last_print = now
						print(f"[stats|{stats.get('data_source','psutil')}] procs={stats['total_processes']} mem={stats['total_memory_percent']:.2f}% cpu_avg={stats['average_cpu_percent']:.2f}%")
					elapsed = time.time() - start
					remaining = self.headless_interval - elapsed
					if remaining > 0:
						time.sleep(remaining)
			except KeyboardInterrupt:
				print("[Headless|pyglet] 終了要求")
			return
		else:
			if pyglet:
				pyglet.app.run()

	# ----------------------------------------------------------------------------------
	# Update frame (copy of pygame logic minus rendering specifics)
	# ----------------------------------------------------------------------------------
	def update(self):
		current_time = time.time()
		# FPS/performance history (pyglet 版は簡易)
		self.performance_monitor['fps_history'].append(self.clock_target_fps)  # Placeholder
		self.performance_monitor['fish_count_history'].append(len(self.fishes))
		if len(self.performance_monitor['fps_history']) > 100:
			self.performance_monitor['fps_history'] = self.performance_monitor['fps_history'][-100:]
			self.performance_monitor['fish_count_history'] = self.performance_monitor['fish_count_history'][-100:]
		if current_time - self.performance_monitor['last_adjustment'] > 5.0:
			self._adjust_performance()
			self.performance_monitor['last_adjustment'] = current_time
		self.update_process_data()
		# Fish position updates (adaptive interval logic retained)
		fish_list = list(self.fishes.values())
		update_interval = self.performance_monitor['adaptive_fish_update_interval']
		for i, fish in enumerate(fish_list):
			should_update = fish.is_dying or len(fish_list) <= 50 or i % update_interval == (int(current_time * 10) % update_interval)
			if not should_update:
				continue
			nearby_fish = []
			for other in fish_list:
				if other.pid != fish.pid:
					dx = fish.x - other.x
					dy = fish.y - other.y
					if abs(dx) < 100 and abs(dy) < 100:
						if dx * dx + dy * dy < 10000:
							nearby_fish.append(other)
			fish.update_position(self.width, self.height, nearby_fish)
		if current_time - self.last_cache_cleanup > self.cache_cleanup_interval:
			# TODO[cache]: surface_cache/background_cache 相当は未実装
			self.last_cache_cleanup = current_time
		# 背景パーティクル更新
		self._update_background_particles()

	# ----------------------------------------------------------------------------------
	# Process data synchronization (copy & adapt)
	# ----------------------------------------------------------------------------------
	def update_process_data(self):
		current_time = time.time()
		if current_time - self.last_process_update < self.process_update_interval:
			return
		self.last_process_update = current_time
		self.process_manager.update()
		process_data = self.process_manager.processes
		self.total_processes = len(process_data)
		self.total_memory = sum(p.memory_percent for p in process_data.values())
		self.avg_cpu = sum(p.cpu_percent for p in process_data.values()) / max(1, len(process_data))
		self.total_threads = sum(p.num_threads for p in process_data.values())
		# New fish
		for pid, proc in process_data.items():
			if pid not in self.fishes:
				x = random.uniform(50, self.width - 50)
				y = random.uniform(50, self.height - 50)
				fish = Fish(pid, proc.name, x, y)
				self.fishes[pid] = fish
				if proc.ppid in self.fishes:
					parent_fish = self.fishes[proc.ppid]
					parent_fish.set_fork_event()
					fish.x = parent_fish.x + random.uniform(-50, 50)
					fish.y = parent_fish.y + random.uniform(-50, 50)
		# exec detection
		exec_processes = self.process_manager.detect_exec()
		for proc in exec_processes:
			if proc.pid in self.fishes:
				self.fishes[proc.pid].set_exec_event()
		self._update_schooling_behavior()
		self._update_ipc_connections()
		self._apply_ipc_attraction()
		for pid, fish in list(self.fishes.items()):
			if pid in process_data:
				proc = process_data[pid]
				fish.update_process_data(proc.memory_percent, proc.cpu_percent, proc.num_threads, proc.ppid)
			else:
				fish.set_death_event()
			if fish.is_dying and fish.death_progress >= 1.0:
				del self.fishes[pid]

	def _headless_process_to_fish(self):  # ヘッドレスで update() 呼ばれない場合の補助
		process_data = self.process_manager.processes
		for pid, proc in process_data.items():
			if pid not in self.fishes:
				x = random.uniform(50, self.width - 50)
				y = random.uniform(50, self.height - 50)
				fish = Fish(pid, proc.name, x, y)
				self.fishes[pid] = fish

	# ----------------------------------------------------------------------------------
	# Schooling / IPC (copy logic)
	# ----------------------------------------------------------------------------------
	def _update_schooling_behavior(self):
		processed = set()
		for pid, fish in self.fishes.items():
			if pid in processed:
				continue
			related_processes = self.process_manager.get_related_processes(pid, max_distance=2)
			related_pids = [p.pid for p in related_processes if p.pid in self.fishes]
			if len(related_pids) > 1:
				leader_pid = min(related_pids)
				for rp in related_pids:
					if rp in self.fishes:
						self.fishes[rp].set_school_members(related_pids, rp == leader_pid)
						processed.add(rp)

	def _update_ipc_connections(self):
		self.ipc_update_timer += 1
		if self.ipc_update_timer >= self.ipc_update_interval:
			self.ipc_update_timer = 0
			self.ipc_connections = self.process_manager.detect_ipc_connections()

	def _apply_ipc_attraction(self):
		for fish in self.fishes.values():
			fish.ipc_attraction_x = 0.0
			fish.ipc_attraction_y = 0.0
		for proc1, proc2 in self.ipc_connections:
			if proc1.pid in self.fishes and proc2.pid in self.fishes:
				f1 = self.fishes[proc1.pid]
				f2 = self.fishes[proc2.pid]
				dx = f2.x - f1.x
				dy = f2.y - f1.y
				distance = math.sqrt(dx*dx + dy*dy)
				if distance > 5:
					attraction_strength = 0.002
					if distance < 100:
						attraction_strength *= 0.5
					elif distance > 300:
						attraction_strength *= 2.0
					force_x = (dx / distance) * attraction_strength
					force_y = (dy / distance) * attraction_strength
					f1.ipc_attraction_x += force_x
					f1.ipc_attraction_y += force_y
					f2.ipc_attraction_x -= force_x
					f2.ipc_attraction_y -= force_y
					if distance < 80:
						f1.start_talking("通信中...", proc2.pid)
						f2.start_talking("データ送信", proc1.pid)

	def _draw_ipc_connections(self):  # quadratic bezier lines
		if not (self.show_ipc and pyglet):
			return
		for proc1, proc2 in self.ipc_connections:
			if proc1.pid in self.fishes and proc2.pid in self.fishes:
				f1 = self.fishes[proc1.pid]
				f2 = self.fishes[proc2.pid]
				dx = f2.x - f1.x
				dy = f2.y - f1.y
				dist = math.sqrt(dx * dx + dy * dy)
				if dist >= 200:
					continue
				cpu_intensity = (f1.cpu_percent + f2.cpu_percent) / 200.0
				r = int(100 + cpu_intensity * 155)
				g = int(150 - cpu_intensity * 50)
				b = int(200 - cpu_intensity * 100)
				mid_x = (f1.x + f2.x) / 2 + math.sin(time.time() * 2) * 10
				mid_y = (f1.y + f2.y) / 2 + math.cos(time.time() * 2) * 10
				steps = 10
				pts: List[float] = []
				for i in range(steps + 1):
					t = i / steps
					x = (1 - t) ** 2 * f1.x + 2 * (1 - t) * t * mid_x + t ** 2 * f2.x
					y = (1 - t) ** 2 * f1.y + 2 * (1 - t) * t * mid_y + t ** 2 * f2.y
					pts.extend([x, y])
				pulse = math.sin(time.time() * 3) * 0.3 + 0.7
				alpha_line = int(80 * pulse)
				if shapes:
					for j in range(0, len(pts) - 2, 2):
						x1, y1 = pts[j], pts[j + 1]
						x2, y2 = pts[j + 2], pts[j + 3]
						line = shapes.Line(x1, y1, x2, y2, thickness=2, color=(r, g, b, alpha_line))
						line.draw()
				else:
					pyglet.gl.glLineWidth(2)
					vertex_count = len(pts) // 2
					positions: List[float] = []
					for k in range(0, len(pts), 2):
						positions.extend([pts[k], pts[k + 1], 0.0])
					color_data: List[float] = []
					for _ in range(vertex_count):
						color_data.extend([
							r / 255.0,
							g / 255.0,
							b / 255.0,
							alpha_line / 255.0,
						])
					positions_arr = array('f', positions)
					colors_arr = array('f', color_data)
					pyglet.graphics.draw(
						vertex_count,
						pyglet.gl.GL_LINE_STRIP,
						position=('f', positions_arr),
						colors=('f', colors_arr)
					)

	def _draw_parent_child_lines(self):
		if not pyglet or not self.show_parent_lines:
			return
		for fish in self.fishes.values():
			if fish.parent_pid and fish.parent_pid in self.fishes:
				parent = self.fishes[fish.parent_pid]
				col = (100, 150, 200, 50)
				if shapes:
					line = shapes.Line(parent.x, parent.y, fish.x, fish.y, thickness=1, color=col)
					line.draw()
				else:
					pyglet.gl.glLineWidth(1)
					positions = [parent.x, parent.y, 0.0,
							   fish.x, fish.y, 0.0]
					colors = []
					for _ in range(2):
						colors.extend([
							col[0] / 255.0,
							col[1] / 255.0,
							col[2] / 255.0,
							col[3] / 255.0,
						])
					positions_arr = array('f', positions)
					colors_arr = array('f', colors)
					pyglet.graphics.draw(
						2,
						pyglet.gl.GL_LINES,
						position=('f', positions_arr),
						colors=('f', colors_arr)
					)

	# ----------------------------------------------------------------------------------
	# UI panel (minimal)
	# ----------------------------------------------------------------------------------
	def _draw_ui(self):
		if not pyglet:
			return
		# 統計ラベル
		stats = [
			f"プロセス: {self.total_processes}",
			f"魚: {len(self.fishes)}",
			f"総メモリ: {self.total_memory:.1f}%",
			f"平均CPU: {self.avg_cpu:.2f}%",
			f"スレッド: {self.total_threads}",
			f"粒子: {self.performance_monitor['adaptive_particle_count']}",
		]
		base_x = 8
		base_y = self.height - 14
		for i, line in enumerate(stats):
			pyglet.text.Label(line, font_size=11, x=base_x, y=base_y - i * 14,
							  anchor_y='top', color=(255, 255, 255, 210))
		if self.selected_fish:
			sf = self.selected_fish
			info = [
				f"PID {sf.pid}",
				sf.name,
				f"Mem {sf.memory_percent:.2f}%",
				f"CPU {sf.cpu_percent:.2f}%",
				f"Threads {sf.thread_count}",
			]
			ix = self.width - 160
			iy = self.height - 14
			for i, line in enumerate(info):
				pyglet.text.Label(line, font_size=11, x=ix, y=iy - i * 14,
								  anchor_y='top', color=(200, 230, 255, 220))

	# ----------------------------------------------------------------------------------
	# Performance adjustment (logic retained / not yet reflected in rendering)
	# ----------------------------------------------------------------------------------
	def _adjust_performance(self):
		if not self.performance_monitor['fps_history']:
			return
		avg_fps = sum(self.performance_monitor['fps_history']) / len(self.performance_monitor['fps_history'])
		if avg_fps < self.clock_target_fps * 0.7:
			if self.performance_monitor['adaptive_particle_count'] > 20:
				self.performance_monitor['adaptive_particle_count'] -= 5
			if self.performance_monitor['adaptive_fish_update_interval'] < 3:
				self.performance_monitor['adaptive_fish_update_interval'] += 1
		elif avg_fps > self.clock_target_fps * 0.9:
			if self.performance_monitor['adaptive_particle_count'] < 100:
				self.performance_monitor['adaptive_particle_count'] += 5
			if self.performance_monitor['adaptive_fish_update_interval'] > 1:
				self.performance_monitor['adaptive_fish_update_interval'] -= 1
		# パーティクル数調整を即反映
		self._resize_background_particles()

	# ----------------------------------------------------------------------------------
	# Background / particles
	# ----------------------------------------------------------------------------------
	def _init_background_particles(self):
		target = self.performance_monitor['adaptive_particle_count']
		for _ in range(target):
			self.background_particles.append({
				'x': random.uniform(0, self.width),
				'y': random.uniform(0, self.height),
				'size': random.uniform(2, 7),
				'speed': random.uniform(10, 30),  # pixels/sec
				'alpha': random.randint(40, 110)
			})

	def _resize_background_particles(self):
		target = self.performance_monitor['adaptive_particle_count']
		cur = len(self.background_particles)
		if cur < target:
			for _ in range(target - cur):
				self.background_particles.append({
					'x': random.uniform(0, self.width),
					'y': -5,
					'size': random.uniform(2, 7),
					'speed': random.uniform(10, 30),
					'alpha': random.randint(40, 110)
				})
		elif cur > target:
			self.background_particles = self.background_particles[:target]

	def _update_background_particles(self):
		if not self.background_particles:
			return
		dt = 1.0 / max(1, self.clock_target_fps)
		for p in self.background_particles:
			p['y'] += p['speed'] * dt
			if p['y'] - p['size'] > self.height:
				p['y'] = -10
				p['x'] = random.uniform(0, self.width)
				p['size'] = random.uniform(2, 7)
				p['speed'] = random.uniform(10, 30)
				p['alpha'] = random.randint(40, 110)

	def _generate_background_cache(self):
		"""テクスチャキャッシュ生成 (内部で sprite も再構築)"""
		if not pyglet:
			return
		if hasattr(self, '_bg_cache_size') and getattr(self, '_bg_cache_size') == (self.width, self.height) \
			and getattr(self, '_bg_cache_sprite', None) is not None:
			return
		h = self.height
		w = self.width
		row_cache = []
		for y in range(h):
			t = y / max(1, h)
			b = int(40 - 30 * t)
			g = int(15 - 12 * t)
			r = 0
			row_cache.append(bytes([r, max(0, g), max(0, b), 255]) * w)
		raw = b''.join(row_cache)
		img = pyglet.image.ImageData(w, h, 'RGBA', raw, pitch=w*4)
		self._bg_cache_tex = img.get_texture()
		self._bg_cache_size = (w, h)
		# Sprite 化 (原点左下 → そのまま)
		self._bg_cache_sprite = pyglet.sprite.Sprite(self._bg_cache_tex, x=0, y=0)
		self._bg_cache_sprite.update(scale_x=1, scale_y=1)

	def _draw_background(self):
		if not pyglet:
			return
		self._generate_background_cache()
		if getattr(self, '_bg_cache_sprite', None) is not None:
			self._bg_cache_sprite.draw()
		if shapes:
			for p in self.background_particles[: self.performance_monitor['adaptive_particle_count']]:
				c = shapes.Circle(p['x'], p['y'], p['size'], color=(120, 170, 220))
				c.opacity = p['alpha']
				c.draw()

	# ----------------------------------------------------------------------------------
	# (Future) Fullscreen toggle placeholder
	# ----------------------------------------------------------------------------------
	def toggle_fullscreen(self):  # TODO[fullscreen]
		if not self.window:
			return
		self.fullscreen = not self.fullscreen
		self.window.set_fullscreen(self.fullscreen)
		# サイズ更新
		self.width, self.height = self.window.get_size()
		# 魚が画面外に出ないよう調整
		for f in self.fishes.values():
			f.x = max(30, min(self.width - 30, f.x))
			f.y = max(30, min(self.height - 30, f.y))
		# パーティクル再初期化
		self.background_particles.clear()
		self._init_background_particles()


def main():  # 手動実行用
	aq = Aquarium()
	aq.run()


if __name__ == "__main__":
	main()

