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

    def __init__(self, width: int = 1200, height: int = 800, headless: bool = False,
                 headless_interval: float = 1.0, use_gpu: Optional[bool] = None):
        # Pygameの初期化
        self.headless = headless
        self.headless_interval = headless_interval
        if self.headless:
            # ダミードライバでウィンドウ生成を抑制
            os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
        self._gpu_texture_type = None
        self.gpu_renderer = None
        self.gpu_window = None
        self.gpu_texture = None
        self.requested_gpu = use_gpu if use_gpu is not None else self._env_flag("AQUARIUM_GPU", False)
        if self.headless and self.requested_gpu:
            print("[GPU] ヘッドレスモードのためGPUレンダラは無効化されます。")
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
            # オーディオデバイスが利用できない場合は無視
            print("⚠️  オーディオデバイスが利用できません。音声なしで継続します。")
            pass

        # macOS Retina対応の環境変数設定
        os.environ['SDL_VIDEO_HIGHDPI_DISABLED'] = '0'  # 高DPI有効化

        # 環境変数から設定を読み取り（制限を大幅に緩和）
        max_processes = int(os.environ.get('AQUARIUM_MAX_PROCESSES', '2000'))  # 500から2000に増加
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
            if self.requested_gpu:
                self._init_gpu_renderer(width, height)
            if not self.use_gpu:
                self.screen = pygame.display.set_mode((width, height))
                pygame.display.set_caption("Digital Life Aquarium - デジタル生命の水族館")
        else:
            # ヘッドレス時は描画用のダミーサーフェスを用意
            self.screen = pygame.Surface((width, height))

        # 時計とFPS
        self.clock = pygame.time.Clock()
        self.fps = target_fps if not self.headless else int(1.0 / max(headless_interval, 0.001))
        self._configure_quality_thresholds()

        # プロセス管理
        # 将来的に eBPF を有効化する場合は、起動パラメータや環境変数で
        # EbpfProcessSource を注入できるようにする予定。
        # 例: if os.environ.get("AQUARIUM_SOURCE") == "ebpf": source = EbpfProcessSource()
        source = None
        chosen = os.environ.get("AQUARIUM_SOURCE", "psutil").lower()
        if chosen == "ebpf":
            try:
                from ..core.sources import EbpfProcessSource
                eb = EbpfProcessSource(enable=True, hybrid_mode=True)
                if getattr(eb, 'available', False):
                    source = eb
                    print("[eBPF] EbpfProcessSource 有効化（ハイブリッドモード）")
                else:
                    # エラー詳細をライフサイクルイベントから取得
                    error_details = ""
                    try:
                        events = eb.drain_lifecycle_events()
                        for event in events:
                            if event.details and ('error' in event.details or 'warning' in event.details):
                                error_msg = event.details.get('error') or event.details.get('warning')
                                error_details = f" - 理由: {error_msg}"
                                break
                    except:
                        pass
                    print(f"[eBPF] 利用不可のため psutil にフォールバック{error_details}")
            except Exception as e:
                print(f"[eBPF] 初期化失敗: {e} -> psutil フォールバック")
        self.process_manager = ProcessManager(max_processes=max_processes, source=source)
        self.fishes: Dict[int, Fish] = {}  # PID -> Fish

        # プロセス制限とソート設定
        limit_str = os.environ.get("AQUARIUM_LIMIT")
        self.process_limit = int(limit_str) if limit_str else None
        self.sort_by = os.environ.get("AQUARIUM_SORT_BY", "cpu")
        self.sort_order = os.environ.get("AQUARIUM_SORT_ORDER", "desc")

        # ProcessManagerに設定を反映
        if self.process_limit is not None:
            self.process_manager.set_process_limit(self.process_limit)
        self.process_manager.set_sort_config(self.sort_by, self.sort_order)

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
        self._neighbor_cell_size = 120  # 近傍検索用のグリッドサイズ（ピクセル）

        # UI状態
        self.selected_fish: Optional[Fish] = None

        # 日本語フォント管理と動的スケーリング
        self._preferred_font_name: Optional[str] = None
        self._preferred_font_path: Optional[str] = None
        self._font_cache: Dict[int, pygame.font.Font] = {}
        self.font_scale = 1.0
        self._update_font_scale()
        self.font = self._get_japanese_font(int(24 * self.font_scale))
        self.small_font = self._get_japanese_font(int(18 * self.font_scale))
        self.bubble_font = self._get_japanese_font(self._determine_bubble_font_size())  # IPC会話吹き出し用フォント

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
        self.ipc_update_interval = 30  # 0.5秒間隔でIPC更新（高頻度化）
        
        # 通信履歴ベースの群れ形成
        self.communication_history = {}  # {(pid1, pid2): [timestamps]}
        self.history_cleanup_timer = 0
        self.history_cleanup_interval = 300  # 5秒間隔で履歴クリーンアップ
        self.communication_window = 60.0  # 60秒間の通信履歴を保持

        # デバッグ情報表示
        self.show_debug = False  # デフォルトでデバッグ表示をオフ
        self.show_ipc = True    # IPC可視化をオン
        self.debug_text_lines = []

        # 通信相手のハイライト
        self.highlighted_partners = []  # ハイライトする通信相手のPIDリスト

        # フルスクリーン管理
        self.original_size = (width, height)
        self._windowed_size = (width, height)

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

                # プロセス誕生ログ
                if not self._suppress_spawn_logs:
                    print(f"🐟 新しいプロセス誕生: PID {pid} ({proc.name})")
                elif "spawn_logs_suppressed" not in self._quality_message_shown:
                    print("🐟 新規プロセス発生ログは高負荷モードのため抑制されています。")
                    self._quality_message_shown.add("spawn_logs_suppressed")

                # 親子関係があれば分裂エフェクト
                if proc.ppid in self.fishes:
                    parent_fish = self.fishes[proc.ppid]
                    parent_fish.set_fork_event()
                    # 子プロセスは親の近くに配置
                    fish.x = parent_fish.x + random.uniform(-50, 50)
                    fish.y = parent_fish.y + random.uniform(-50, 50)
                    print(f"👨‍👦 親子関係検出: 親PID {proc.ppid} → 子PID {pid}")

        # exec検出とエフェクト
        exec_processes = self.process_manager.detect_exec()
        for proc in exec_processes:
            if proc.pid in self.fishes:
                self.fishes[proc.pid].set_exec_event()

        # 群れ行動の設定
        self._update_schooling_behavior()

        # IPC接続の更新
        self._update_ipc_connections()
        
        # 通信履歴の更新と群れ形成
        self._update_communication_history()

        # IPC吸引力の適用
        self._apply_ipc_attraction()

        # 既存のFishデータ更新
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
                # プロセスが消滅した場合
                # print(f"🔥 プロセス消失を検出: PID {pid} ({fish.process_name}) - 死亡フラグ設定")
                fish.set_death_event()
                processes_marked_for_death.append(pid)

        # if processes_marked_for_death:
        #     print(f"📊 死亡フラグ設定済みプロセス数: {len(processes_marked_for_death)}")

        # 死んだFishの除去
        dead_pids = []
        dying_fish_details = []
        for pid, fish in self.fishes.items():
            if fish.is_dying:
                dying_fish_details.append(f"PID {pid}: {fish.death_progress:.2f}")
                if fish.death_progress >= 1.0:
                    dead_pids.append(pid)
                    # print(f"💀 魚の死亡処理完了: PID {pid} ({fish.process_name}) - 削除対象")

        # 死亡中の魚の進行状況を定期的に表示（最大5匹まで）
        # if dying_fish_details:
        #     print(f"⏰ 死亡進行中: {', '.join(dying_fish_details[:5])}{'...' if len(dying_fish_details) > 5 else ''}")

        # print(f"📊 現在の魚数: {len(self.fishes)}, 削除対象: {len(dead_pids)}, 総プロセス数: {len(process_data)}")

        for pid in dead_pids:
            fish_name = self.fishes[pid].process_name
            del self.fishes[pid]
            # print(f"🗑️ 魚を削除完了: PID {pid} ({fish_name})")

        # if dead_pids:
        #     print(f"📊 削除後の魚数: {len(self.fishes)}")

    def _remove_oldest_fish(self):
        """最も古い魚を削除してパフォーマンスを維持"""
        if not self.fishes:
            return

        # 作成時刻でソートして最も古い魚を特定
        oldest_fish = min(self.fishes.values(), key=lambda f: f.creation_time)
        # print(f"🗑️ 古い魚を削除: PID {oldest_fish.pid} ({oldest_fish.process_name})")
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
        if self.enable_adaptive_quality:
            quality_label = f"{self.render_quality} (自動)"
        else:
            quality_label = "full (固定)"

        stats_lines = [
            f"総プロセス数: {self.total_processes}",
            f"表示中の魚: {len(self.fishes)}",
            f"総メモリ使用率: {self.total_memory:.1f}%",
            f"平均CPU使用率: {self.avg_cpu:.2f}%",
            f"総スレッド数: {self.total_threads}",
            f"FPS: {current_fps:.1f}",
            f"パーティクル数: {self.performance_monitor['adaptive_particle_count']}",
            f"描画品質: {quality_label}",
        ]

        if self.enable_adaptive_quality:
            reduced_threshold, minimal_threshold = self._quality_thresholds
            if reduced_threshold is not None and minimal_threshold is not None:
                stats_lines.append(f"品質閾値: 簡易≦{reduced_threshold:.1f}fps／最小≦{minimal_threshold:.1f}fps")

        # プロセス制限とソート情報を追加
        limit_str = "無制限" if self.process_limit is None else str(self.process_limit)
        stats_lines.append(f"制限: {limit_str}")

        field_names = {"cpu": "CPU", "memory": "メモリ", "name": "名前", "pid": "PID"}
        order_symbol = "↓" if self.sort_order == "desc" else "↑"
        stats_lines.append(f"ソート: {field_names.get(self.sort_by, self.sort_by)} {order_symbol}")

        # Retinaディスプレイ情報
        if hasattr(self, 'retina_info') and self.retina_info['is_retina']:
            stats_lines.append(f"Retina: {self.retina_info['scale_factor']:.1f}x")

        # 背景パネル
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

        # 統計テキスト
        for i, line in enumerate(stats_lines):
            color = (255, 100, 100) if current_fps < self.fps * 0.7 else (255, 255, 255)  # 低FPS時は赤
            text_surface = self._render_text(line, self.small_font, color)
            text_x = panel_x + panel_padding_x
            text_y = panel_y + panel_padding_y + i * line_height
            self.screen.blit(text_surface, (text_x, text_y))

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
            "F/F11: フルスクリーン切替",
            "L: プロセス制限切替",
            "S: ソートフィールド切替",
            "O: ソート順序切替"
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
                # 空のエントリを削除
                if not self.communication_history[key]:
                    del self.communication_history[key]
        
        # 通信頻度の高いプロセス同士を追加で群れにする
        self._form_communication_based_schools(current_time)

    def _form_communication_based_schools(self, current_time: float):
        """通信履歴に基づいて動的に群れを形成"""
        cutoff_time = current_time - self.communication_window
        
        for (pid1, pid2), timestamps in self.communication_history.items():
            recent_communications = [t for t in timestamps if t > cutoff_time]
            
            # 過去60秒間に3回以上通信があれば群れ関係とみなす
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
                    print(f"IPC可視化: {'オン' if self.show_ipc else 'オフ'}")
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
            elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                self.handle_mouse_click(event.pos)

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

        # 全てのFishを描画
        for fish in self.fishes.values():
            fish.draw(self.screen, self.bubble_font, quality=self.render_quality,
                      text_renderer=self._render_text)

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
        if self.use_gpu:
            self._present_gpu_frame()
        else:
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
        """フォントが日本語文字を正しく描画できるかを検証"""
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
        """日本語対応フォントを取得（クロスプラットフォーム対応）"""
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

    def _env_flag(self, name: str, default: bool = False) -> bool:
        value = os.environ.get(name)
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _init_gpu_renderer(self, width: int, height: int):
        try:
            from pygame._sdl2.video import Window, Renderer, Texture

            self.gpu_window = Window("Digital Life Aquarium - デジタル生命の水族館 (GPUモード)",
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
            pygame.display.set_caption("Digital Life Aquarium - デジタル生命の水族館")
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
        base_font_size = 24
        small_font_size = 18
        self.font = self._get_japanese_font(int(base_font_size * self.font_scale))
        self.small_font = self._get_japanese_font(int(small_font_size * self.font_scale))
        self.bubble_font = self._get_japanese_font(self._determine_bubble_font_size())

def main():
    """メイン関数"""
    aquarium = Aquarium()
    aquarium.run()

if __name__ == "__main__":
    main()
