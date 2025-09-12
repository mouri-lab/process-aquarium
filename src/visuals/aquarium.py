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

    def __init__(self, width: int = 1200, height: int = 800):
        # Pygameの初期化
        pygame.init()
        pygame.mixer.init()

        # macOS Retina対応の環境変数設定
        import os
        os.environ['SDL_VIDEO_HIGHDPI_DISABLED'] = '0'  # 高DPI有効化

        # 環境変数から設定を読み取り
        max_processes = int(os.environ.get('AQUARIUM_MAX_PROCESSES', '100'))
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

        self.screen = pygame.display.set_mode((width, height))
        pygame.display.set_caption("Digital Life Aquarium - デジタル生命の水族館")

        # 時計とFPS
        self.clock = pygame.time.Clock()
        self.fps = target_fps

        # プロセス管理
        self.process_manager = ProcessManager(max_processes=max_processes)
        self.fishes: Dict[int, Fish] = {}  # PID -> Fish

        # 描画最適化
        self.surface_cache = {}  # 描画キャッシュ
        self.last_process_update = 0
        self.process_update_interval = 2.0  # プロセス更新を2秒間隔に

        # UI状態
        self.selected_fish: Optional[Fish] = None

        # 日本語対応フォントの設定
        self.font = self._get_japanese_font(24)
        self.small_font = self._get_japanese_font(18)

        # 背景とエフェクト
        self.background_particles = []
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

        # 実行状態
        self.running = True

    def init_background_particles(self):
        """背景の水泡パーティクルを初期化"""
        self.background_particles = []  # 既存のパーティクルをクリア
        particle_count = min(50, int(self.width * self.height / 20000))  # 画面サイズに応じてパーティクル数を調整
        for _ in range(particle_count):
            particle = {
                'x': random.uniform(0, self.width),
                'y': random.uniform(0, self.height),
                'size': random.uniform(2, 8),
                'speed': random.uniform(0.5, 2.0),
                'alpha': random.randint(30, 80)
            }
            self.background_particles.append(particle)

    def update_background_particles(self):
        """背景パーティクルの更新"""
        for particle in self.background_particles:
            particle['y'] -= particle['speed']

            # 画面上部を超えたら下から再登場
            if particle['y'] < -10:
                particle['y'] = self.height + 10
                particle['x'] = random.uniform(0, self.width)

    def draw_background(self):
        """背景の描画"""
        # 深海のグラデーション背景
        for y in range(self.height):
            # 上部は濃い青、下部は黒に近い青
            intensity = 1.0 - (y / self.height)
            blue_intensity = int(20 + intensity * 30)
            color = (0, 0, blue_intensity)
            pygame.draw.line(self.screen, color, (0, y), (self.width, y))

        # 水泡パーティクル
        for particle in self.background_particles:
            color = (100, 150, 200, particle['alpha'])
            temp_surface = pygame.Surface((particle['size'] * 2, particle['size'] * 2), pygame.SRCALPHA)
            pygame.draw.circle(temp_surface, color,
                             (particle['size'], particle['size']),
                             int(particle['size']))
            self.screen.blit(temp_surface,
                           (particle['x'] - particle['size'],
                            particle['y'] - particle['size']))

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

        # 新規プロセス用のFish作成
        for pid, proc in process_data.items():
            if pid not in self.fishes:
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
        """マウスクリックによるFish選択"""
        x, y = pos
        self.selected_fish = None

        # 最も近いFishを選択
        min_distance = float('inf')
        for fish in self.fishes.values():
            distance = math.sqrt((fish.x - x)**2 + (fish.y - y)**2)
            if distance < fish.current_size + 10 and distance < min_distance:
                min_distance = distance
                self.selected_fish = fish

    def draw_ui(self):
        """UI情報の描画"""
        # 統計情報
        stats_lines = [
            f"総プロセス数: {self.total_processes}",
            f"総メモリ使用率: {self.total_memory:.1f}%",
            f"平均CPU使用率: {self.avg_cpu:.2f}%",
            f"総スレッド数: {self.total_threads}",
            f"FPS: {self.clock.get_fps():.1f}",
        ]

        # 背景パネル
        panel_height = len(stats_lines) * 25 + 10
        panel_surface = pygame.Surface((220, panel_height), pygame.SRCALPHA)
        panel_surface.fill((0, 0, 0, 128))
        self.screen.blit(panel_surface, (10, 10))

        # 統計テキスト
        for i, line in enumerate(stats_lines):
            text_surface = self._render_text(line, self.small_font, (255, 255, 255))
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

    def draw_ipc_connections(self):
        """IPC接続の描画（デジタル神経網のような線で）"""
        if not self.show_ipc:
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

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # 左クリック
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

    def update(self):
        """フレーム更新"""
        # プロセスデータの更新
        self.update_process_data()

        # 背景パーティクルの更新
        self.update_background_particles()

        # Fishの位置更新（群れ行動対応）
        fish_list = list(self.fishes.values())
        for fish in fish_list:
            # 近くの魚を検索
            nearby_fish = []
            for other_fish in fish_list:
                if other_fish.pid != fish.pid:
                    distance = math.sqrt((fish.x - other_fish.x)**2 + (fish.y - other_fish.y)**2)
                    if distance < 100:  # 100ピクセル以内の魚
                        nearby_fish.append(other_fish)

            fish.update_position(self.width, self.height, nearby_fish)

    def draw(self):
        """描画処理"""
        # 背景
        self.draw_background()

        # 親子関係の線
        if self.show_debug:
            self.draw_parent_child_connections()

        # IPC接続の線
        self.draw_ipc_connections()

        # 全てのFishを描画
        for fish in self.fishes.values():
            fish.draw(self.screen)

        # 選択されたFishのハイライト
        if self.selected_fish:
            highlight_surface = pygame.Surface((self.width, self.height), pygame.SRCALPHA)
            pygame.draw.circle(highlight_surface, (255, 255, 255, 100),
                             (int(self.selected_fish.x), int(self.selected_fish.y)),
                             int(self.selected_fish.current_size + 10), 2)
            self.screen.blit(highlight_surface, (0, 0))

        # UI描画
        self.draw_ui()

        # 画面更新
        pygame.display.flip()

    def run(self):
        """メインループ"""
        print("=== Digital Life Aquarium を開始します ===")
        print("🐠 プロセスが生命体として水族館に現れるまでお待ちください...")
        print("💡 ヒント: プロセス名によって色が決まり、CPU使用時に光ります")

        while self.running:
            # イベント処理
            self.handle_events()

            # 更新
            self.update()

            # 描画
            self.draw()

            # FPS制御
            self.clock.tick(self.fps)

        # 終了処理
        pygame.quit()
        print("🌙 水族館を閉館しました。お疲れさまでした！")

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
        """最適なフルスクリーン解像度を取得（論理解像度を優先）"""
        try:
            # 常に論理解像度を使用（Retinaディスプレイ対応）
            info = pygame.display.Info()
            logical_width = info.current_w
            logical_height = info.current_h

            print(f"🔍 論理解像度を使用: {logical_width}x{logical_height}")
            return (logical_width, logical_height)

        except Exception as e:
            print(f"❌ 解像度取得エラー: {e}")
            # フォールバック: 一般的な解像度
            return (1920, 1080)

    def _get_japanese_font(self, size: int) -> pygame.font.Font:
        """日本語対応フォントを取得"""
        # macOSで確実に利用可能な日本語フォントのリスト（優先順）
        japanese_fonts = [
            # macOS Monterey以降
            "SF Pro Display",
            "SF Pro Text",
            # macOS標準の日本語フォント
            "Hiragino Sans",
            "Hiragino Kaku Gothic ProN",
            "Hiragino Kaku Gothic Pro",
            # その他のバックアップフォント
            "Arial Unicode MS",
            "Helvetica Neue",
            "Arial",
        ]

        # システムの日本語フォントファイルパスも試行
        font_paths = [
            "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
            "/System/Library/Fonts/Hiragino Sans GB.ttc",
            "/Library/Fonts/Arial Unicode.ttf",
            "/System/Library/Fonts/Arial.ttf",
        ]

        # まずシステムフォントを試行
        for font_name in japanese_fonts:
            try:
                font = pygame.font.SysFont(font_name, size)
                # 日本語文字でテスト（ひらがな、カタカナ、漢字）
                test_texts = ["あいう", "アイウ", "日本語", "テスト"]

                for test_text in test_texts:
                    try:
                        test_surface = font.render(test_text, True, (255, 255, 255))
                        if test_surface.get_width() > size:  # 文字が実際に描画されているかチェック
                            print(f"✅ 日本語フォント '{font_name}' を使用します (サイズ: {size})")
                            return font
                    except:
                        continue
            except Exception as e:
                print(f"❌ フォント '{font_name}' の読み込みに失敗: {e}")
                continue

        # 次にフォントファイルパスを試行
        for font_path in font_paths:
            try:
                if os.path.exists(font_path):
                    font = pygame.font.Font(font_path, size)
                    test_surface = font.render("テスト", True, (255, 255, 255))
                    if test_surface.get_width() > 0:
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
