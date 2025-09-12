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

        # 環境変数から設定を読み取り
        import os
        max_processes = int(os.environ.get('AQUARIUM_MAX_PROCESSES', '100'))
        target_fps = int(os.environ.get('AQUARIUM_FPS', '30'))

        # 画面設定
        self.width = width
        self.height = height
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

        # 統計情報
        self.total_processes = 0
        self.total_memory = 0.0
        self.avg_cpu = 0.0
        self.total_threads = 0

        # デバッグ情報表示
        self.show_debug = False  # デフォルトでデバッグ表示をオフ
        self.debug_text_lines = []

        # 実行状態
        self.running = True

    def init_background_particles(self):
        """背景の水泡パーティクルを初期化"""
        for _ in range(20):  # パーティクル数を20に削減
            particle = {
                'x': random.uniform(0, self.width),
                'y': random.uniform(0, self.height),
                'size': random.uniform(2, 6),
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
            "D: デバッグ表示切替"
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

            elif event.type == pygame.MOUSEBUTTONDOWN:
                if event.button == 1:  # 左クリック
                    self.handle_mouse_click(event.pos)

    def update(self):
        """フレーム更新"""
        # プロセスデータの更新
        self.update_process_data()

        # 背景パーティクルの更新
        self.update_background_particles()

        # Fishの位置更新
        for fish in list(self.fishes.values()):
            fish.update_position(self.width, self.height)

    def draw(self):
        """描画処理"""
        # 背景
        self.draw_background()

        # 親子関係の線
        if self.show_debug:
            self.draw_parent_child_connections()

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

def main():
    """メイン関数"""
    try:
        aquarium = Aquarium()
        aquarium.run()
    except KeyboardInterrupt:
        print("\n🌙 水族館を手動で閉館しました。")
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
