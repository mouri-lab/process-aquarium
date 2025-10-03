"""
Digital Life Aquarium - Main Aquarium Visualization
メインの水族館描画とインタラクション管理
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
    # eBPF ソースが実装された際に差し替え可能な拡張ポイント
    from ..core.sources import EbpfProcessSource
except Exception:  # pragma: no cover - 安全なフォールバック
    EbpfProcessSource = None  # type: ignore
from .fish import Fish

# 文字エンコーディングの設定
import locale
try:
    locale.setlocale(locale.LC_ALL, 'ja_JP.UTF-8')
except:
    try:
        locale.setlocale(locale.LC_ALL, 'C.UTF-8')
    except:
        pass  # ロケール設定に失敗しても続行

class Aquarium:
    """
    デジタル生命の水族館メインクラス
    プロセス監視とビジュアライゼーションを統合管理
    """

    def __init__(self, width: int = 1200, height: int = 800, headless: bool = False, headless_interval: float = 1.0):
        # Pygameの初期化
        self.headless = headless
        self.headless_interval = headless_interval
        if self.headless:
            # ダミードライバでウィンドウ生成を抑制
            os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        pygame.init()
        try:
            pygame.mixer.init()
        except pygame.error:
            # オーディオデバイスが利用できない場合は無視
            print("⚠️  オーディオデバイスが利用できません。音声なしで継続します。")
            pass

        # macOS Retina対応の環境変数設定
        os.environ['SDL_VIDEO_HIGHDPI_DISABLED'] = '0'  # 高DPI有効化

        # 環境変数から設定を読み取り（制限を大幅に緩和）
        max_processes = int(os.environ.get('AQUARIUM_MAX_PROCESSES', '500'))  # 100から500に増加
        target_fps = int(os.environ.get('AQUARIUM_FPS', '30'))

        # 画面設定
        self.base_width = width
        self.base_height = height
        self.width = width
        self.height = height
        self.fullscreen = False
        self.scale_factor = 1.0  # Retina scaling factor

        # 利用可能な解像度情報を表示（デバッグ用）
        self._print_display_info()

        # Retinaスケール情報を取得
        self.retina_info = self.detect_retina_scaling()

        if not self.headless:
            self.screen = pygame.display.set_mode((width, height))
            pygame.display.set_caption("Digital Life Aquarium - デジタル生命の水族館")
        else:
            # ヘッドレス時は描画用のダミーサーフェスを用意
            self.screen = pygame.Surface((width, height))

        # 時計とFPS
        self.clock = pygame.time.Clock()
        self.fps = target_fps if not self.headless else int(1.0 / max(headless_interval, 0.001))

        # プロセス管理
        # 将来的に eBPF を有効化する場合は、起動パラメータや環境変数で
        # EbpfProcessSource を注入できるようにする予定。
        # 例: if os.environ.get("AQUARIUM_SOURCE") == "ebpf": source = EbpfProcessSource()
        source = None
        chosen = os.environ.get("AQUARIUM_SOURCE", "psutil").lower()
        if chosen == "ebpf":
            try:
                from ..core.sources import EbpfProcessSource
                eb = EbpfProcessSource()
                if getattr(eb, 'available', False):
                    source = eb
                    print("[eBPF] EbpfProcessSource 有効化")
                else:
                    print("[eBPF] 利用不可のため psutil にフォールバック")
            except Exception as e:
                print(f"[eBPF] 初期化失敗: {e} -> psutil フォールバック")
        self.process_manager = ProcessManager(max_processes=max_processes, source=source)
        self.fishes: Dict[int, Fish] = {}  # PID -> Fish

        # パフォーマンス最適化（制限緩和）
        self.surface_cache = {}  # 描画キャッシュ
        self.background_cache = None  # 背景キャッシュ
        self.last_process_update = 0
        self.process_update_interval = 1.0  # プロセス更新を1秒間隔に短縮（2秒から1秒へ）
        self.last_cache_cleanup = time.time()
        self.cache_cleanup_interval = 60.0  # キャッシュクリーンアップを1分間隔に延長

        # 動的パフォーマンス調整
        self.performance_monitor = {
            'fps_history': [],
            'fish_count_history': [],
            'last_adjustment': 0,
            'adaptive_particle_count': 50,
            'adaptive_fish_update_interval': 1
        }

        # UI状態
        self.selected_fish: Optional[Fish] = None

        # 動的フォントスケーリング
        self.font_scale = 1.0
        self._update_font_scale()
        self.font = self._get_japanese_font(int(24 * self.font_scale))
        self.small_font = self._get_japanese_font(int(18 * self.font_scale))
        self.bubble_font = self._get_japanese_font(10)  # IPC会話吹き出し用の小さなフォント

        # 背景とエフェクト（動的パーティクル数）
        self.background_particles = []
        self.particle_count = self.performance_monitor['adaptive_particle_count']
        if not self.headless:
            self.init_background_particles()

        # プロセス関連統計
        self.total_processes = 0
        self.total_memory = 0.0
        self.avg_cpu = 0.0
        self.total_threads = 0

        # IPC接続情報
        self.ipc_connections = []
        self.ipc_update_timer = 0
        self.ipc_update_interval = 60  # 1秒間隔でIPC更新

        # デバッグ情報表示
        self.show_debug = False  # デフォルトでデバッグ表示をオフ
        self.show_ipc = True    # IPC可視化をオン
        self.debug_text_lines = []
        
        # 通信相手のハイライト
        self.highlighted_partners = []  # ハイライトする通信相手のPIDリスト

        # フルスクリーン管理
        self.original_size = (width, height)

        # 実行状態
        self.running = True
        if self.headless:
            print("[Headless] モードで起動しました。統計情報のみを出力します。Ctrl+Cで終了。")

    def init_background_particles(self):
        """背景の水泡パーティクルを初期化（適応的）"""
        self.background_particles = []  # 既存のパーティクルをクリア

        # 適応的パーティクル数を使用
        base_count = min(100, int(self.width * self.height / 15000))  # 画面サイズに応じた基本数
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

        # 背景キャッシュをクリア（サイズ変更に対応）
        self.background_cache = None

    def update_background_particles(self):
        """背景パーティクルの更新"""
        for particle in self.background_particles:
            particle['y'] -= particle['speed']

            # 画面上部を超えたら下から再登場
            if particle['y'] < -10:
                particle['y'] = self.height + 10
                particle['x'] = random.uniform(0, self.width)

    def draw_background(self):
        """背景の描画（キャッシュ最適化版）"""
        # 背景キャッシュがない場合は作成
        if self.background_cache is None or self.background_cache.get_size() != (self.width, self.height):
            self._create_background_cache()

        # キャッシュされた背景を描画
        self.screen.blit(self.background_cache, (0, 0))

        # 動的な水泡パーティクル（適応的な数）
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

    def _create_background_cache(self):
        """背景キャッシュを作成"""
        self.background_cache = pygame.Surface((self.width, self.height))

        # 深海のグラデーション背景
        for y in range(self.height):
            # 上部は濃い青、下部は黒に近い青
            intensity = 1.0 - (y / self.height)
            blue_intensity = int(20 + intensity * 30)
            color = (0, 0, blue_intensity)
            pygame.draw.line(self.background_cache, color, (0, y), (self.width, y))

    def update_process_data(self):
        """プロセス情報の更新"""
        current_time = time.time()

        # プロセス更新間隔制御
        if current_time - self.last_process_update < self.process_update_interval:
            return

        self.last_process_update = current_time

        # ProcessManagerのupdateを呼び出してデータを最新に
        self.process_manager.update()

        # プロセス辞書を取得
        process_data = self.process_manager.processes

        # 統計情報の更新
        self.total_processes = len(process_data)
        self.total_memory = sum(proc.memory_percent for proc in process_data.values())
        self.avg_cpu = sum(proc.cpu_percent for proc in process_data.values()) / max(1, len(process_data))
        self.total_threads = sum(proc.num_threads for proc in process_data.values())

        # 新規プロセス用のFish作成（制限解除）
        for pid, proc in process_data.items():
            if pid not in self.fishes:
                # 制限を一時的に解除 - すべてのプロセスを表示
                # max_fish = min(self.process_manager.max_processes, 150)  # 最大150匹
                # if len(self.fishes) >= max_fish:
                #     self._remove_oldest_fish()

                # ランダムな初期位置
                x = random.uniform(50, self.width - 50)
                y = random.uniform(50, self.height - 50)

                fish = Fish(pid, proc.name, x, y)
                self.fishes[pid] = fish

                # 親子関係があれば分裂エフェクト
                if proc.ppid in self.fishes:
                    parent_fish = self.fishes[proc.ppid]
                    parent_fish.set_fork_event()
                    # 子プロセスは親の近くに配置
                    fish.x = parent_fish.x + random.uniform(-50, 50)
                    fish.y = parent_fish.y + random.uniform(-50, 50)

        # exec検出とエフェクト
        exec_processes = self.process_manager.detect_exec()
        for proc in exec_processes:
            if proc.pid in self.fishes:
                self.fishes[proc.pid].set_exec_event()

        # 群れ行動の設定
        self._update_schooling_behavior()

        # IPC接続の更新
        self._update_ipc_connections()
        
        # IPC吸引力の適用
        self._apply_ipc_attraction()

        # 既存のFishデータ更新
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
                # プロセスが消滅した場合
                fish.set_death_event()

        # 死んだFishの除去
        dead_pids = []
        for pid, fish in self.fishes.items():
            if fish.is_dying and fish.death_progress >= 1.0:
                dead_pids.append(pid)

        for pid in dead_pids:
            del self.fishes[pid]

    def _remove_oldest_fish(self):
        """最も古い魚を削除してパフォーマンスを維持"""
        if not self.fishes:
            return

        # 作成時刻でソートして最も古い魚を特定
        oldest_fish = min(self.fishes.values(), key=lambda f: f.creation_time)
        print(f"🗑️ 古い魚を削除: PID {oldest_fish.pid} ({oldest_fish.process_name})")
        del self.fishes[oldest_fish.pid]

    def _update_schooling_behavior(self):
        """群れ行動の更新"""
        # 関連プロセス群を取得して群れを形成
        processed_pids = set()

        for pid, fish in self.fishes.items():
            if pid in processed_pids:
                continue

            # 関連プロセスを取得
            related_processes = self.process_manager.get_related_processes(pid, max_distance=2)
            related_pids = [p.pid for p in related_processes if p.pid in self.fishes]

            if len(related_pids) > 1:
                # 群れを形成
                # 最も古いプロセスまたは親プロセスをリーダーに
                leader_pid = min(related_pids)  # 単純にPIDが小さいものをリーダーに

                for related_pid in related_pids:
                    if related_pid in self.fishes:
                        is_leader = (related_pid == leader_pid)
                        self.fishes[related_pid].set_school_members(related_pids, is_leader)
                        processed_pids.add(related_pid)

    def handle_mouse_click(self, pos: Tuple[int, int]):
        """マウスクリックによるFish選択と吹き出しクリック処理"""
        x, y = pos
        
        # まず吹き出しのクリック判定をチェック
        for fish in self.fishes.values():
            if fish.bubble_rect and fish.is_talking:
                bx, by, bw, bh = fish.bubble_rect
                if bx <= x <= bx + bw and by <= y <= by + bh:
                    # 吹き出しがクリックされた場合、通信相手をハイライト
                    self._highlight_communication_partners(fish)
                    return
        
        # 吹き出しがクリックされなかった場合、通常のFish選択
        self.selected_fish = None
        self.highlighted_partners = []  # 通信相手のハイライトをクリア

        # 最も近いFishを選択
        min_distance = float('inf')
        for fish in self.fishes.values():
            distance = math.sqrt((fish.x - x)**2 + (fish.y - y)**2)
            if distance < fish.current_size + 10 and distance < min_distance:
                min_distance = distance
                self.selected_fish = fish

    def _highlight_communication_partners(self, fish):
        """通信相手をハイライト表示"""
        self.highlighted_partners = fish.talk_partners.copy()
        
        # 通信相手の情報を表示
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
        current_fps = self.clock.get_fps()

        # 統計情報（パフォーマンス情報を含む）
        stats_lines = [
            f"総プロセス数: {self.total_processes}",
            f"表示中の魚: {len(self.fishes)}",
            f"総メモリ使用率: {self.total_memory:.1f}%",
            f"平均CPU使用率: {self.avg_cpu:.2f}%",
            f"総スレッド数: {self.total_threads}",
            f"FPS: {current_fps:.1f}",
            f"パーティクル数: {self.performance_monitor['adaptive_particle_count']}",
        ]

        # Retinaディスプレイ情報
        if hasattr(self, 'retina_info') and self.retina_info['is_retina']:
            stats_lines.append(f"Retina: {self.retina_info['scale_factor']:.1f}x")

        # 背景パネル
        panel_height = len(stats_lines) * 25 + 10
        panel_surface = pygame.Surface((280, panel_height), pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 128))
        self.screen.blit(panel_surface, (10, 10))

        # 統計テキスト
        for i, line in enumerate(stats_lines):
            color = (255, 100, 100) if current_fps < self.fps * 0.7 else (255, 255, 255)  # 低FPS時は赤
            text_surface = self._render_text(line, self.small_font, color)
            self.screen.blit(text_surface, (15, 15 + i * 25))

        # 選択されたFishの詳細情報
        if self.selected_fish:
            info_lines = [
                f"選択された生命体:",
                f"PID: {self.selected_fish.pid}",
                f"名前: {self.selected_fish.name}",
                f"メモリ: {self.selected_fish.memory_percent:.2f}%",
                f"CPU: {self.selected_fish.cpu_percent:.2f}%",
                f"スレッド数: {self.selected_fish.thread_count}",
                f"年齢: {self.selected_fish.age}フレーム"
            ]

            info_height = len(info_lines) * 22 + 10
            info_surface = pygame.Surface((250, info_height), pygame.SRCALPHA)
            info_surface.fill((0, 50, 100, 180))
            self.screen.blit(info_surface, (self.width - 260, 10))

            for i, line in enumerate(info_lines):
                color = (255, 255, 255) if i == 0 else (200, 200, 200)
                text_surface = self._render_text(line, self.small_font, color)
                self.screen.blit(text_surface, (self.width - 250, 15 + i * 22))

        # 操作説明
        help_lines = [
            "操作方法:",
            "クリック: 生命体を選択",
            "ESC: 終了",
            "D: デバッグ表示切替",
            "I: IPC接続表示切替",
            "F/F11: フルスクリーン切替"
        ]

        help_height = len(help_lines) * 20 + 10
        help_surface = pygame.Surface((200, help_height), pygame.SRCALPHA)
        help_surface.fill((0, 0, 0, 100))
        self.screen.blit(help_surface, (10, self.height - help_height - 10))

        for i, line in enumerate(help_lines):
            color = (255, 255, 150) if i == 0 else (200, 200, 200)
            text_surface = self._render_text(line, self.small_font, color)
            self.screen.blit(text_surface, (15, self.height - help_height - 5 + i * 20))

    def draw_parent_child_connections(self):
        """親子関係の描画（淡い線で接続）"""
        for fish in self.fishes.values():
            if fish.parent_pid and fish.parent_pid in self.fishes:
                parent_fish = self.fishes[fish.parent_pid]

                # 淡い線で接続
                color = (100, 150, 200, 50)
                temp_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
                pygame.draw.line(temp_surface, color,
                               (int(parent_fish.x), int(parent_fish.y)),
                               (int(fish.x), int(fish.y)), 1)
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
                    # 吸引力の強さを距離に応じて調整
                    attraction_strength = 0.002  # 基本の吸引力
                    if distance < 100:  # 近い場合は弱く
                        attraction_strength *= 0.5
                    elif distance > 300:  # 遠い場合は強く
                        attraction_strength *= 2.0
                    
                    # 正規化された方向ベクトル
                    force_x = (dx / distance) * attraction_strength
                    force_y = (dy / distance) * attraction_strength
                    
                    # 両方の魚に吸引力を適用
                    fish1.ipc_attraction_x += force_x
                    fish1.ipc_attraction_y += force_y
                    fish2.ipc_attraction_x -= force_x
                    fish2.ipc_attraction_y -= force_y
                    
                    # 近距離で会話フラグをセット
                    if distance < 80:  # 80ピクセル以内で会話
                        fish1.is_talking = True
                        fish1.talk_timer = 60  # 1秒間会話
                        fish1.talk_message = "通信中..."
                        fish1.talk_partners = [proc2.pid]  # 通信相手を記録
                        fish2.is_talking = True
                        fish2.talk_timer = 60
                        fish2.talk_message = "データ送信"
                        fish2.talk_partners = [proc1.pid]  # 通信相手を記録

    def draw_ipc_connections(self):
        """IPC接続の描画（デジタル神経網のような線で）"""
        if self.headless or not self.show_ipc:
            return

        connection_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)

        for proc1, proc2 in self.ipc_connections:
            if proc1.pid in self.fishes and proc2.pid in self.fishes:
                fish1 = self.fishes[proc1.pid]
                fish2 = self.fishes[proc2.pid]

                # 距離チェック（画面上でも近い場合のみ描画）
                distance = math.sqrt((fish1.x - fish2.x)**2 + (fish1.y - fish2.y)**2)
                if distance < 200:  # 200ピクセル以内の場合のみ
                    # 脈動する線の効果
                    pulse = math.sin(time.time() * 3) * 0.3 + 0.7
                    alpha = int(80 * pulse)

                    # CPU使用率に応じて線の色を変更
                    cpu_intensity = (fish1.cpu_percent + fish2.cpu_percent) / 200.0
                    red = int(100 + cpu_intensity * 155)
                    green = int(150 - cpu_intensity * 50)
                    blue = int(200 - cpu_intensity * 100)

                    color = (red, green, blue, alpha)

                    # 少し曲がった線を描画（より有機的に）
                    mid_x = (fish1.x + fish2.x) / 2 + math.sin(time.time() * 2) * 10
                    mid_y = (fish1.y + fish2.y) / 2 + math.cos(time.time() * 2) * 10

                    # ベジェ曲線風の描画
                    steps = 10
                    points = []
                    for i in range(steps + 1):
                        t = i / steps
                        # 二次ベジェ曲線
                        x = (1-t)**2 * fish1.x + 2*(1-t)*t * mid_x + t**2 * fish2.x
                        y = (1-t)**2 * fish1.y + 2*(1-t)*t * mid_y + t**2 * fish2.y
                        points.append((x, y))

                    if len(points) > 1:
                        pygame.draw.lines(connection_surface, color, False, points, 2)

        self.screen.blit(connection_surface, (0, 0))

    def handle_events(self):
        """イベント処理"""
        if self.headless:
            return
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                self.running = False
            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    self.running = False
                elif event.key == pygame.K_d:
                    self.show_debug = not self.show_debug
                elif event.key == pygame.K_i:
                    self.show_ipc = not self.show_ipc
                    print(f"IPC可視化: {'オン' if self.show_ipc else 'オフ'}")
                elif event.key == pygame.K_f or event.key == pygame.K_F11:
                    self.toggle_fullscreen()
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.handle_mouse_click(event.pos)

    def toggle_fullscreen(self):
        """フルスクリーンモードの切り替え"""
        self.fullscreen = not self.fullscreen

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
            self.width = self.base_width
            self.height = self.base_height
            self.screen = pygame.display.set_mode((self.width, self.height))
            print(f"🪟 ウィンドウモード: {self.width}x{self.height}")

        print(f"📐 現在の画面サイズ: {self.screen.get_width()}x{self.screen.get_height()}")

        # 背景パーティクルを新しいサイズに合わせて再初期化
        self.init_background_particles()

        # 魚の位置を新しい画面サイズに合わせて調整
        self.adjust_fish_positions_for_screen_resize()

        # フォントサイズも画面サイズに合わせて調整
        font_scale = min(self.width / self.base_width, self.height / self.base_height)
        base_font_size = 24
        small_font_size = 18

        self.font = self._get_japanese_font(int(base_font_size * font_scale))
        self.small_font = self._get_japanese_font(int(small_font_size * font_scale))
        self.bubble_font = self._get_japanese_font(10)  # IPC会話吹き出し用は固定サイズ

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

    def _cleanup_caches(self):
        """キャッシュクリーンアップ"""
        # サーフェスキャッシュをクリア
        old_cache_size = len(self.surface_cache)
        self.surface_cache.clear()

        # 背景キャッシュをクリア
        self.background_cache = None

        print(f"🧹 キャッシュクリーンアップ完了 (削除: {old_cache_size}アイテム)")

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

        # 背景パーティクルの更新
        self.update_background_particles()

        # Fishの位置更新（適応的更新間隔）
        fish_list = list(self.fishes.values())
        update_interval = self.performance_monitor['adaptive_fish_update_interval']

        for i, fish in enumerate(fish_list):
            # 適応的更新：魚の数が多い場合は一部の魚のみ更新
            if len(fish_list) > 50 and i % update_interval != (int(current_time * 10) % update_interval):
                continue

            # 近くの魚を検索（最適化：距離の事前チェック）
            nearby_fish = []
            for other_fish in fish_list:
                if other_fish.pid != fish.pid:
                    dx = fish.x - other_fish.x
                    dy = fish.y - other_fish.y
                    if abs(dx) < 100 and abs(dy) < 100:  # 事前チェック
                        distance_sq = dx * dx + dy * dy
                        if distance_sq < 10000:  # 100^2
                            nearby_fish.append(other_fish)

            fish.update_position(self.width, self.height, nearby_fish)

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

        # 全てのFishを描画
        for fish in self.fishes.values():
            fish.draw(self.screen, self.bubble_font)

        # 選択されたFishのハイライト
        if self.selected_fish:
            highlight_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            pygame.draw.circle(highlight_surface, (255, 255, 255, 100),
                             (int(self.selected_fish.x), int(self.selected_fish.y)),
                             int(self.selected_fish.current_size + 10), 2)
            self.screen.blit(highlight_surface, (0, 0))

        # 通信相手のハイライト表示
        if self.highlighted_partners:
            partner_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            for partner_pid in self.highlighted_partners:
                if partner_pid in self.fishes:
                    partner_fish = self.fishes[partner_pid]
                    # 緑色の点滅ハイライト
                    pulse = math.sin(time.time() * 8) * 0.5 + 0.5
                    alpha = int(150 * pulse + 50)
                    pygame.draw.circle(partner_surface, (0, 255, 0, alpha),
                                     (int(partner_fish.x), int(partner_fish.y)),
                                     int(partner_fish.current_size + 15), 3)
            self.screen.blit(partner_surface, (0, 0))

        # UI描画
        self.draw_ui()

        # 画面更新
        pygame.display.flip()

    def run(self):
        """メインループ"""
        if not self.headless:
            print("=== Digital Life Aquarium を開始します ===")
            print("🐠 プロセスが生命体として水族館に現れるまでお待ちください...")
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
                    print(f"[stats] procs={stats['total_processes']} new={stats['new_processes']} dying={stats['dying_processes']} mem={stats['total_memory_percent']:.2f}% cpu_avg={stats['average_cpu_percent']:.2f}% threads={stats['total_threads']}")
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

    def _validate_japanese_font(self, font: pygame.font.Font, test_texts: list, font_name: str) -> bool:
        """フォントが日本語文字を正しく描画できるかを検証"""
        try:
            for test_text in test_texts:
                try:
                    test_surface = font.render(test_text, True, (255, 255, 255))
                    
                    # 基本的な描画チェック
                    if test_surface.get_width() == 0 or test_surface.get_height() == 0:
                        continue
                    
                    # 文字数と幅の関係をチェック（日本語文字は一定の幅を持つべき）
                    expected_min_width = len(test_text) * (font.get_height() * 0.5)  # 文字数 × フォント高さの半分
                    if test_surface.get_width() < expected_min_width:
                        continue  # 幅が小さすぎる = 文字が適切に描画されていない
                    
                    # 少なくとも1つのテキストで有効な描画ができた
                    return True
                        
                except Exception:
                    continue
            
            # すべてのテストテキストで失敗
            return False
            
        except Exception:
            return False

    def _get_japanese_font(self, size: int) -> pygame.font.Font:
        """日本語対応フォントを取得（クロスプラットフォーム対応）"""
        import platform
        system = platform.system()
        
        # プラットフォーム別の日本語フォントリスト（優先順）
        if system == "Darwin":  # macOS
            japanese_fonts = [
                # macOS Monterey以降
                "SF Pro Display",
                "SF Pro Text",
                # macOS標準の日本語フォント
                "Hiragino Sans",
                "Hiragino Kaku Gothic ProN",
                "Hiragino Kaku Gothic Pro",
                # バックアップフォント
                "Arial Unicode MS",
                "Helvetica Neue",
                "Arial",
            ]
            font_paths = [
                "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
                "/System/Library/Fonts/Hiragino Sans GB.ttc",
                "/Library/Fonts/Arial Unicode.ttf",
                "/System/Library/Fonts/Arial.ttf",
            ]
        elif system == "Linux":  # Linux
            japanese_fonts = [
                # Noto CJK フォント（推奨）
                "Noto Sans CJK JP",
                "Noto Serif CJK JP",
                "Noto Sans CJK SC",
                # DejaVu フォント
                "DejaVu Sans",
                # その他のLinux標準フォント
                "Liberation Sans",
                "FreeSans",
                "Arial",
            ]
            font_paths = [
                "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/opentype/noto/NotoSerifCJK-Regular.ttc",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
                "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
            ]
        elif system == "Windows":  # Windows
            japanese_fonts = [
                # Windows標準日本語フォント
                "Yu Gothic UI",
                "Yu Gothic",
                "Meiryo UI",
                "Meiryo",
                "MS Gothic",
                "MS PGothic",
                # Unicode対応フォント
                "Arial Unicode MS",
                "Segoe UI",
                "Arial",
            ]
            font_paths = [
                "C:/Windows/Fonts/yugothic.ttf",
                "C:/Windows/Fonts/meiryo.ttc",
                "C:/Windows/Fonts/msgothic.ttc",
                "C:/Windows/Fonts/arialuni.ttf",
                "C:/Windows/Fonts/segoeui.ttf",
            ]
        else:  # その他のOS用フォールバック
            japanese_fonts = [
                "Arial Unicode MS",
                "DejaVu Sans",
                "Liberation Sans",
                "Arial",
            ]
            font_paths = []

        # まずシステムフォントを試行
        for font_name in japanese_fonts:
            try:
                font = pygame.font.SysFont(font_name, size)
                # 日本語文字でテスト（ひらがな、カタカナ、漢字）
                test_texts = ["あいう", "アイウ", "日本語", "テスト"]
                
                # フォントが日本語文字を正しく描画できるかテスト
                valid_font = self._validate_japanese_font(font, test_texts, font_name)
                if valid_font:
                    print(f"✅ 日本語フォント '{font_name}' を使用します (サイズ: {size}) - {system}")
                    return font
                    
            except Exception as e:
                print(f"❌ フォント '{font_name}' の読み込みに失敗: {e}")
                continue

        # 次にフォントファイルパスを試行
        for font_path in font_paths:
            try:
                if os.path.exists(font_path):
                    font = pygame.font.Font(font_path, size)
                    # 簡単なテスト
                    if self._validate_japanese_font(font, ["テスト"], font_path):
                        print(f"✅ フォントファイル '{font_path}' を使用します")
                        return font
            except Exception as e:
                print(f"❌ フォントファイル '{font_path}' の読み込みに失敗: {e}")
                continue

        # 最終的なフォールバック: pygame.font.get_default_font()
        try:
            default_font_path = pygame.font.get_default_font()
            font = pygame.font.Font(default_font_path, size)
            print(f"⚠️  デフォルトフォント '{default_font_path}' を使用します（日本語表示不可）")
            return font
        except:
            # 最後の手段: Noneフォント
            print("❌ フォント読み込み完全失敗。Noneフォントを使用します")
            return pygame.font.Font(None, size)

    def _render_text(self, text: str, font: pygame.font.Font, color: Tuple[int, int, int]) -> pygame.Surface:
        """日本語テキストを安全にレンダリング"""
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

def main():
    """メイン関数"""
    aquarium = Aquarium()
    aquarium.run()

if __name__ == "__main__":
    main()
