"""
Digital Life Aquarium - Fish Entity
デジタル生命体（プロセス）の視覚的表現を管理するクラス
"""

import pygame
import math
import random
import time
from typing import Tuple, Optional, List

class Fish:
    """
    プロセスを表現するデジタル生命体クラス
    プロセスの状態（メモリ、CPU、スレッド数など）に応じて
    視覚的な属性（サイズ、色、動きなど）を動的に変更する
    """

    def __init__(self, pid: int, name: str, x: float, y: float):
        # プロセス基本情報
        self.pid = pid
        self.name = name
        self.process_name = name  # aquarium.pyとの互換性
        self.parent_pid: Optional[int] = None
        self.creation_time = time.time()  # 作成時刻を記録

        # 位置と動き
        self.x = x
        self.y = y
        self.vx = random.uniform(-1, 1)  # 水平速度
        self.vy = random.uniform(-1, 1)  # 垂直速度
        self.target_x = x
        self.target_y = y

        # 魚の向きと形状
        self.angle = 0.0  # 魚の向き（ラジアン）
        self.tail_swing = 0.0  # 尻尾の振り
        self.swim_cycle = 0.0  # 泳ぎのサイクル
        self.fish_shape = self._determine_fish_shape(name)  # プロセス名による形状

        # 群れ行動の属性
        self.school_members: List[int] = []  # 群れのメンバーPID
        self.is_leader = False  # 群れのリーダーかどうか
        self.flocking_strength = 0.8  # 群れ行動の強さ
        self.separation_distance = 30.0  # 分離距離
        self.alignment_distance = 50.0   # 整列距離
        self.cohesion_distance = 70.0    # 結束距離

        # IPC通信の吸引力
        self.ipc_attraction_x = 0.0  # IPC接続による吸引力X
        self.ipc_attraction_y = 0.0  # IPC接続による吸引力Y

        # 視覚的属性
        self.base_size = 10
        self.current_size = self.base_size
        self.color = self._generate_color()
        self.alpha = 255
        self.glow_intensity = 0
        self.is_memory_giant = False  # メモリ巨大魚フラグ
        self.pulsation_phase = 0.0  # 脈動エフェクト用

        # 生命活動指標
        self.memory_percent = 0.0
        self.cpu_percent = 0.0
        self.thread_count = 1
        self.age = 0  # フレーム数

        # アニメーション状態
        self.is_spawning = True
        self.spawn_progress = 0.0
        self.is_dying = False
        self.death_progress = 0.0

        # 特殊状態
        self.recently_forked = False
        self.fork_glow_timer = 0
        self.exec_transition = False
        self.exec_timer = 0

        # IPC会話状態
        self.is_talking = False  # 会話中かどうか
        self.talk_timer = 0  # 会話アニメーションタイマー
        self.talk_message = ""  # 表示するメッセージ
        self.talk_partners = []  # 通信相手のPIDリスト
        self.bubble_rect = None  # 吹き出しのクリック領域 (x, y, width, height)
        self.exec_timer = 0

    def _generate_color(self) -> Tuple[int, int, int]:
        """プロセス名に基づいて固有の色を生成"""
        # プロセス名のハッシュ値を使って色を決定
        hash_value = hash(self.name) % 360

        # HSVからRGBに変換（彩度と明度は固定）
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
        """プロセス名に基づいて魚の形状を決定"""
        name_lower = process_name.lower()

        # ブラウザ系：サメ（大きくて速い）
        if any(browser in name_lower for browser in ['chrome', 'firefox', 'safari', 'edge']):
            return 'shark'

        # 開発系：熱帯魚（カラフル）
        elif any(dev in name_lower for dev in ['code', 'vscode', 'atom', 'sublime', 'vim']):
            return 'tropical'

        # システム系：エイ（平たく神秘的）
        elif any(sys in name_lower for sys in ['kernel', 'system', 'daemon', 'service']):
            return 'ray'

        # 通信系：イルカ（群れを作る）
        elif any(comm in name_lower for comm in ['zoom', 'slack', 'discord', 'teams']):
            return 'dolphin'

        # 重いプロセス：クジラ（大きい）
        elif any(heavy in name_lower for heavy in ['photoshop', 'docker', 'virtualbox']):
            return 'whale'

        # ターミナル：ウナギ（細長い）
        elif any(term in name_lower for term in ['terminal', 'bash', 'zsh', 'cmd']):
            return 'eel'

        # その他：一般的な魚
        else:
            return 'fish'

    def update_process_data(self, memory_percent: float, cpu_percent: float,
                          thread_count: int, parent_pid: Optional[int] = None,
                          memory_peak: Optional[float] = None):
        """プロセスデータの更新"""
        memory_percent = max(memory_percent, 0.0)
        self.memory_percent = memory_percent
        self.cpu_percent = cpu_percent
        self.thread_count = thread_count
        self.parent_pid = parent_pid

        # メモリ使用量に応じたサイズ調整（相対シェアと対数圧縮のブレンド）
        memory_normalized = memory_percent / 100.0
        if memory_peak is not None and memory_peak > 0:
            relative_share = min(memory_percent / max(memory_peak, 1e-6), 1.0)
        else:
            relative_share = min(memory_normalized, 1.0)

        relative_component = math.pow(relative_share, 0.65)
        absolute_component = math.log1p(memory_percent / 6.0)

        memory_factor = 1.0 + relative_component * 2.8 + absolute_component * 2.2
        memory_factor = max(1.0, min(memory_factor, 9.0))
        self.current_size = self.base_size * memory_factor

        # メモリ巨大魚の判定（より抑制された閾値）
        self.is_memory_giant = memory_percent >= 8.0 or memory_factor >= 5.5

        # CPU使用率に基づく光り方（指数関数的に強調）
        cpu_normalized = cpu_percent / 100.0
        # 指数関数で光の強さを計算
        glow_factor = (math.exp(3 * cpu_normalized) - 1) / (math.exp(3) - 1)
        self.glow_intensity = min(glow_factor * 255, 255)

        # CPU使用率に基づく移動速度調整（指数関数的に高速化）
        # 指数関数で速度倍率を計算：1.0 + (exp(4 * cpu) - 1) / (exp(4) - 1) * 6
        # これにより0%で1倍、100%で約7倍の速度になる
        speed_factor = 1.0 + (math.exp(4 * cpu_normalized) - 1) / (math.exp(4) - 1) * 6.0
        max_speed = 2.0 * min(speed_factor, 8.0)  # 最大8倍で制限
        self.vx = max(min(self.vx, max_speed), -max_speed)
        self.vy = max(min(self.vy, max_speed), -max_speed)

    def set_fork_event(self):
        """フォーク（分裂）イベントの設定"""
        self.recently_forked = True
        self.fork_glow_timer = 60  # 60フレーム間光る

    def set_exec_event(self):
        """exec（変態）イベントの設定"""
        self.exec_transition = True
        self.exec_timer = 30
        # 新しい色を生成
        self.color = self._generate_color()

    def set_death_event(self):
        """死亡イベントの設定（既に死亡中の場合は進行状況をリセットしない）"""
        if not self.is_dying:  # 初回のみリセット
            self.is_dying = True
            self.death_progress = 0.0

    def update_position(self, screen_width: int, screen_height: int, nearby_fish: List['Fish'] = None):
        """位置の更新とバウンド処理（群れ行動対応版）"""
        # 年齢を増やす
        self.age += 1

        # メモリ巨大魚の脈動エフェクト
        if self.is_memory_giant:
            self.pulsation_phase += 0.15  # 脈動速度
            if self.pulsation_phase > 2 * math.pi:
                self.pulsation_phase -= 2 * math.pi

        # スポーン時のアニメーション
        if self.is_spawning:
            self.spawn_progress += 0.05
            if self.spawn_progress >= 1.0:
                self.is_spawning = False
                self.spawn_progress = 1.0

        # 死亡時のアニメーション
        if self.is_dying:
            old_progress = self.death_progress
            self.death_progress += 0.03
            # デバッグ用：進行状況を定期的に出力
            # if int(old_progress * 10) != int(self.death_progress * 10):  # 0.1刻みで出力
            #     print(f"💀 死亡進行: PID {self.pid} ({self.process_name}) - {old_progress:.2f} -> {self.death_progress:.2f}")
            # if self.death_progress >= 1.0 and old_progress < 1.0:
            #     print(f"💀 魚の死亡完了: PID {self.pid} ({self.process_name}) - progress {old_progress:.2f} -> {self.death_progress:.2f}")
            return self.death_progress < 1.0

        # 特殊エフェクトのタイマー更新
        if self.fork_glow_timer > 0:
            self.fork_glow_timer -= 1
            if self.fork_glow_timer == 0:
                self.recently_forked = False

        if self.exec_timer > 0:
            self.exec_timer -= 1
            if self.exec_timer == 0:
                self.exec_transition = False

        # 会話タイマーの更新
        if self.talk_timer > 0:
            self.talk_timer -= 1
            if self.talk_timer == 0:
                self.is_talking = False
                self.talk_message = ""
                self.bubble_rect = None  # 吹き出し領域をクリア
                self.talk_message = ""

        # 群れ行動の計算
        flocking_force_x = 0.0
        flocking_force_y = 0.0

        if nearby_fish and self.school_members:
            # 群れのメンバーのみを対象にする
            school_fish = [f for f in nearby_fish if f.pid in self.school_members]
            if school_fish:
                flocking_force_x, flocking_force_y = self.calculate_flocking_forces(school_fish)

        # ランダムな目標位置の変更（群れ行動がない場合）
        if not self.school_members and random.random() < 0.01:  # 1%の確率で目標変更
            self.target_x = random.uniform(50, screen_width - 50)
            self.target_y = random.uniform(50, screen_height - 50)

        # 基本的な移動計算
        if self.school_members:
            # 群れ行動時は群れの力を主とする
            self.vx += flocking_force_x * self.flocking_strength
            self.vy += flocking_force_y * self.flocking_strength
        else:
            # 単独行動時は目標位置に向かう
            dx = self.target_x - self.x
            dy = self.target_y - self.y
            distance = math.sqrt(dx*dx + dy*dy)

            if distance > 5:
                self.vx += dx * 0.001
                self.vy += dy * 0.001

        # 摩擦
        self.vx *= 0.98
        self.vy *= 0.98

        # IPC通信による吸引力を適用
        self.vx += self.ipc_attraction_x
        self.vy += self.ipc_attraction_y

        # 位置更新
        self.x += self.vx
        self.y += self.vy

        # 画面端での反射
        if self.x <= self.current_size or self.x >= screen_width - self.current_size:
            self.vx *= -0.8
            self.x = max(self.current_size, min(screen_width - self.current_size, self.x))

        if self.y <= self.current_size or self.y >= screen_height - self.current_size:
            self.vy *= -0.8
            self.y = max(self.current_size, min(screen_height - self.current_size, self.y))

        return True  # まだ生きている

    def get_display_color(self) -> Tuple[int, int, int]:
        """現在の状態に応じた表示色を取得"""
        r, g, b = self.color

        # メモリ巨大魚の特別な色合い（赤みを強調）
        if self.is_memory_giant:
            # 脈動に合わせて赤色を強調
            red_boost = int(50 * (1.0 + 0.5 * math.sin(self.pulsation_phase)))
            r = min(255, r + red_boost)
            # 青を少し減らして赤紫っぽく
            b = max(0, b - 20)

        # フォーク時の白い光り
        if self.recently_forked:
            glow_factor = self.fork_glow_timer / 60.0
            r = int(r + (255 - r) * glow_factor)
            g = int(g + (255 - g) * glow_factor)
            b = int(b + (255 - b) * glow_factor)

        # CPU使用時の光り（指数関数的に強調）
        if self.glow_intensity > 0:
            intensity = self.glow_intensity / 255.0
            # 指数関数的な光の強調：最大150の明度追加（非常に明るく）
            glow_boost = (math.exp(3 * intensity) - 1) / (math.exp(3) - 1) * 150
            r = min(255, int(r + glow_boost))
            g = min(255, int(g + glow_boost))
            b = min(255, int(b + glow_boost))

        # exec変態時の色変化
        if self.exec_transition:
            transition_factor = 1.0 - (self.exec_timer / 30.0)
            # 虹色エフェクト
            rainbow_shift = int(transition_factor * 180)
            r = (r + rainbow_shift) % 255
            g = (g + rainbow_shift) % 255
            b = (b + rainbow_shift) % 255

        return (r, g, b)

    def get_display_alpha(self) -> int:
        """現在の状態に応じた透明度を取得"""
        alpha = self.alpha

        # スポーン時のフェードイン
        if self.is_spawning:
            alpha = int(255 * self.spawn_progress)

        # 死亡時のフェードアウト
        if self.is_dying:
            alpha = int(255 * (1.0 - self.death_progress))

        return alpha

    def get_display_size(self) -> float:
        """現在の状態に応じた表示サイズを取得"""
        size = self.current_size

        # メモリ巨大魚の脈動エフェクト（±30%の変動）
        if self.is_memory_giant:
            pulsation = 1.0 + 0.3 * math.sin(self.pulsation_phase)
            size *= pulsation

        # スポーン時の拡大
        if self.is_spawning:
            spawn_scale = 0.1 + 0.9 * self.spawn_progress
            size *= spawn_scale

        # 死亡時の縮小
        if self.is_dying:
            death_scale = 1.0 - self.death_progress
            size *= death_scale

        # フォーク時の一時的拡大
        if self.recently_forked:
            fork_scale = 1.0 + (self.fork_glow_timer / 60.0) * 0.3
            size *= fork_scale

        return size

    def _draw_memory_giant_effects(self, screen: pygame.Surface, alpha: int):
        """メモリ巨大魚用の特別エフェクト（波紋など）"""
        # 波紋エフェクト：3つの同心円
        ripple_color = (255, 100, 100, max(30, alpha // 4))  # 赤っぽい半透明

        for i in range(3):  # 波紋を3層に抑制
            # 各波紋の半径と透明度を脈動に合わせて変化（より大きな範囲）
            ripple_phase = self.pulsation_phase + i * (math.pi / 4)
            # 波紋の範囲を2倍に拡大：巨大魚に相応しいスケール
            ripple_radius = self.current_size * (3.0 + i * 1.2) * (1.0 + 0.5 * math.sin(ripple_phase))
            ripple_alpha = max(8, int((alpha // 8) * (1.0 - i * 0.2)))

            # 半透明の円を描画
            if ripple_radius > 0 and ripple_alpha > 0:
                try:
                    # 一時的なサーフェスを作成して半透明描画
                    temp_surface = pygame.Surface((ripple_radius * 2 + 4, ripple_radius * 2 + 4), pygame.SRCALPHA)
                    pygame.draw.circle(temp_surface, (*ripple_color[:3], ripple_alpha),
                                     (ripple_radius + 2, ripple_radius + 2), int(ripple_radius), 2)
                    screen.blit(temp_surface, (self.x - ripple_radius - 2, self.y - ripple_radius - 2),
                               special_flags=pygame.BLEND_ALPHA_SDL2)
                except (ValueError, pygame.error):
                    pass  # 描画エラーを無視

    def _draw_lightning_effects(self, screen: pygame.Surface, alpha: int):
        """超巨大魚用の雷エフェクト（メモリ使用率20%以上）"""
        if not hasattr(self, 'lightning_timer'):
            self.lightning_timer = 0

        self.lightning_timer += 1

        # ランダムに雷を発生（30フレームに1回程度）
        if self.lightning_timer % 30 == 0 or random.random() < 0.1:
            lightning_color = (255, 255, 150, max(100, alpha // 2))  # 明るい黄色

            # 魚の周りに3-5本の雷を描画
            num_bolts = random.randint(3, 5)
            for _ in range(num_bolts):
                # 雷の起点と終点をランダムに設定
                angle = random.uniform(0, 2 * math.pi)
                start_radius = self.current_size * 0.8
                end_radius = self.current_size * 2.5

                start_x = self.x + math.cos(angle) * start_radius
                start_y = self.y + math.sin(angle) * start_radius
                end_x = self.x + math.cos(angle) * end_radius
                end_y = self.y + math.sin(angle) * end_radius

                # ジグザグの雷を描画
                try:
                    points = [(start_x, start_y)]
                    segments = 4
                    for i in range(1, segments):
                        t = i / segments
                        mid_x = start_x + (end_x - start_x) * t
                        mid_y = start_y + (end_y - start_y) * t
                        # ランダムな揺れを追加
                        offset_x = random.uniform(-20, 20)
                        offset_y = random.uniform(-20, 20)
                        points.append((mid_x + offset_x, mid_y + offset_y))
                    points.append((end_x, end_y))

                    # 雷の線を描画
                    if len(points) >= 2:
                        pygame.draw.lines(screen, lightning_color[:3], False, points, 2)
                except (ValueError, pygame.error):
                    pass

    def get_thread_satellites(self) -> list:
        """スレッド数に応じた衛星の位置を計算（指数関数的に強調）"""
        satellites = []
        if self.thread_count > 1:
            capped_threads = min(self.thread_count - 1, 12)
            if capped_threads <= 0:
                return satellites

            satellite_count = max(1, min(int(math.ceil(capped_threads ** 0.7)), 8))

            for i in range(satellite_count):
                angle = (2 * math.pi * i) / satellite_count + self.age * 0.018
                radius_multiplier = 1.1 + min(self.thread_count, 12) * 0.1
                radius = self.current_size * radius_multiplier
                sat_x = self.x + math.cos(angle) * radius
                sat_y = self.y + math.sin(angle) * radius
                satellites.append((sat_x, sat_y))
        return satellites

    def _draw_fish_shape(self, screen: pygame.Surface, color: Tuple[int, int, int],
                        alpha: int, size: float):
        """魚の形状に応じた描画"""
        if size < 3:
            return

        # 魚の向きを計算（より滑らかに）
        if abs(self.vx) > 0.1 or abs(self.vy) > 0.1:
            target_angle = math.atan2(self.vy, self.vx)
            # 角度を滑らかに変化させる
            angle_diff = target_angle - self.angle
            if angle_diff > math.pi:
                angle_diff -= 2 * math.pi
            elif angle_diff < -math.pi:
                angle_diff += 2 * math.pi
            self.angle += angle_diff * 0.1

        # 泳ぎのアニメーション（速度に応じて変化）
        speed = math.sqrt(self.vx**2 + self.vy**2)

        # CPU使用率に応じて泳ぎの激しさを指数関数的に調整
        cpu_factor = 1.0
        if hasattr(self, 'cpu_percent'):
            cpu_normalized = self.cpu_percent / 100.0
            # 指数関数でCPU使用率による激しさを計算
            cpu_factor = 1.0 + (math.exp(2 * cpu_normalized) - 1) / (math.exp(2) - 1) * 4.0

        swim_speed = (0.1 + speed * 0.1) * cpu_factor
        self.swim_cycle += swim_speed

        # 尻尾の振りもCPU使用率に応じて激しく
        tail_intensity = (0.2 + speed * 0.1) * cpu_factor
        self.tail_swing = math.sin(self.swim_cycle) * min(tail_intensity, 1.0)  # 最大1.0で制限

        # 魚の基本サイズ（形状によって調整）
        body_length = size * 1.8
        body_width = size * 0.9

        if self.fish_shape == 'shark':
            self._draw_shark(screen, color, alpha, body_length, body_width)
        elif self.fish_shape == 'tropical':
            self._draw_tropical_fish(screen, color, alpha, body_length, body_width)
        elif self.fish_shape == 'ray':
            self._draw_ray(screen, color, alpha, body_length * 1.2, body_width * 1.5)
        elif self.fish_shape == 'dolphin':
            self._draw_dolphin(screen, color, alpha, body_length, body_width)
        elif self.fish_shape == 'whale':
            self._draw_whale(screen, color, alpha, body_length * 1.3, body_width * 1.2)
        elif self.fish_shape == 'eel':
            self._draw_eel(screen, color, alpha, body_length * 2.0, body_width * 0.4)
        else:
            self._draw_generic_fish(screen, color, alpha, body_length, body_width)

    def draw(self, screen: pygame.Surface, font: pygame.font.Font = None, quality: str = "full",
             text_renderer=None):
        """Fishの描画（魚らしい見た目版）"""
        if self.death_progress >= 1.0:
            return

        # 現在の描画属性を取得
        color = self.get_display_color()
        alpha = self.get_display_alpha()
        size = self.get_display_size()

        if quality not in {"full", "reduced", "minimal"}:
            quality = "full"

        # サイズが小さすぎる場合はスキップ
        if size < 2:
            return

        if quality == "minimal":
            # 超過密モードではシンプルな円のみ描画
            radius = max(2, min(int(size), 24))
            pygame.draw.circle(screen, color, (int(self.x), int(self.y)), radius)
            return

        # メモリ巨大魚の波紋エフェクト（メモリ使用率5%以上）
        enable_memory_fx = (quality == "full")
        if enable_memory_fx and self.is_memory_giant and hasattr(self, 'memory_percent'):
            if self.memory_percent >= 1.0:
                self._draw_memory_giant_effects(screen, alpha)
            # 超巨大魚（20%以上）には追加の雷エフェクト
            if self.memory_percent >= 20.0:
                self._draw_lightning_effects(screen, alpha)

        # メイン生命体の描画（魚の形状）
        if alpha > 20:  # 透明度が低すぎる場合はスキップ
            self._draw_fish_shape(screen, color, alpha, size)

        # スレッド衛星の描画（小魚の群れとして）
        if quality == "full" and self.thread_count > 1 and size > 5:
            satellites = self.get_thread_satellites()
            # スレッド数に応じて表示数を増加（最大12個まで）
            max_display = min(len(satellites), max(4, self.thread_count // 2))
            for i, (sat_x, sat_y) in enumerate(satellites[:max_display]):
                # スレッド数が多いほど衛星サイズも大きく
                thread_size_factor = 1.0 + (self.thread_count / 20.0)
                sat_size = max(1.5, min(size * 0.20 * thread_size_factor, size * 0.7))
                # 小さな魚として描画
                self._draw_small_fish(screen, color, alpha//2, sat_x, sat_y, sat_size)

        # 会話吹き出しの描画
        if quality != "minimal" and self.is_talking and self.talk_message:
            self._draw_speech_bubble(screen, self.talk_message, font, text_renderer)

    def _draw_small_fish(self, screen: pygame.Surface, color: Tuple[int, int, int],
                        alpha: int, x: float, y: float, size: float):
        """小魚（スレッド衛星）の描画"""
        if size < 2:
            return

        # シンプルな小魚の形
        if alpha >= 255:
            # 体
            pygame.draw.ellipse(screen, color,
                              (x - size, y - size/2, size * 1.5, size))
            # 尻尾
            tail_points = [
                (x - size, y),
                (x - size * 1.5, y - size/3),
                (x - size * 1.5, y + size/3)
            ]
            pygame.draw.polygon(screen, color, tail_points)
        else:
            temp_surface = pygame.Surface((size * 3, size * 2), pygame.SRCALPHA)
            # 体
            pygame.draw.ellipse(temp_surface, (*color, alpha),
                              (size/2, size/2, size * 1.5, size))
            # 尻尾
            tail_points = [
                (size/2, size),
                (0, size * 2/3),
                (0, size * 4/3)
            ]
            pygame.draw.polygon(temp_surface, (*color, alpha), tail_points)
            screen.blit(temp_surface, (x - size * 1.5, y - size))

    def _draw_shark(self, screen: pygame.Surface, color: Tuple[int, int, int],
                    alpha: int, body_length: float, body_width: float):
        """サメの描画"""
        pygame.draw.ellipse(screen, (*color, alpha),
                            (self.x - body_length / 2, self.y - body_width / 2,
                             body_length, body_width))

        # 尻尾の描画
        tail_length = body_length * 0.7
        tail_width = body_width * 0.3
        tail_angle = self.angle + math.pi / 2 + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(tail_angle) * tail_length,
                              self.y + math.sin(tail_angle) * tail_length),
                             (self.x + math.cos(tail_angle) * tail_length * 0.8,
                              self.y + math.sin(tail_angle) * tail_length * 0.8)])

    def _draw_tropical_fish(self, screen: pygame.Surface, color: Tuple[int, int, int],
                            alpha: int, body_length: float, body_width: float):
        """熱帯魚の描画"""
        pygame.draw.ellipse(screen, (*color, alpha),
                            (self.x - body_length / 2, self.y - body_width / 2,
                             body_length, body_width))

        # 尻尾の描画
        tail_length = body_length * 0.6
        tail_width = body_width * 0.4
        tail_angle = self.angle + math.pi / 2 + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(tail_angle) * tail_length,
                              self.y + math.sin(tail_angle) * tail_length),
                             (self.x + math.cos(tail_angle) * tail_length * 0.7,
                              self.y + math.sin(tail_angle) * tail_length * 0.7)])

        # ひれの描画
        fin_length = body_length * 0.4
        fin_width = body_width * 0.2
        fin_angle = self.angle - math.pi / 2 + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(fin_angle) * fin_length,
                              self.y + math.sin(fin_angle) * fin_length),
                             (self.x + math.cos(fin_angle) * fin_length * 0.8,
                              self.y + math.sin(fin_angle) * fin_length * 0.8)])

    def _draw_ray(self, screen: pygame.Surface, color: Tuple[int, int, int],
                  alpha: int, body_length: float, body_width: float):
        """エイの描画"""
        pygame.draw.ellipse(screen, (*color, alpha),
                            (self.x - body_length / 2, self.y - body_width / 2,
                             body_length, body_width))

        # 尻尾の描画
        tail_length = body_length * 0.8
        tail_width = body_width * 0.2
        tail_angle = self.angle + math.pi + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(tail_angle) * tail_length,
                              self.y + math.sin(tail_angle) * tail_length),
                             (self.x + math.cos(tail_angle) * tail_length * 0.9,
                              self.y + math.sin(tail_angle) * tail_length * 0.9)])

    def _draw_dolphin(self, screen: pygame.Surface, color: Tuple[int, int, int],
                      alpha: int, body_length: float, body_width: float):
        """イルカの描画"""
        pygame.draw.ellipse(screen, (*color, alpha),
                            (self.x - body_length / 2, self.y - body_width / 2,
                             body_length, body_width))

        # 尻尾の描画
        tail_length = body_length * 0.7
        tail_width = body_width * 0.3
        tail_angle = self.angle + math.pi / 2 + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(tail_angle) * tail_length,
                              self.y + math.sin(tail_angle) * tail_length),
                             (self.x + math.cos(tail_angle) * tail_length * 0.8,
                              self.y + math.sin(tail_angle) * tail_length * 0.8)])

        # ひれの描画
        fin_length = body_length * 0.5
        fin_width = body_width * 0.2
        fin_angle = self.angle - math.pi / 2 + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(fin_angle) * fin_length,
                              self.y + math.sin(fin_angle) * fin_length),
                             (self.x + math.cos(fin_angle) * fin_length * 0.8,
                              self.y + math.sin(fin_angle) * fin_length * 0.8)])

    def _draw_whale(self, screen: pygame.Surface, color: Tuple[int, int, int],
                    alpha: int, body_length: float, body_width: float):
        """クジラの描画"""
        pygame.draw.ellipse(screen, (*color, alpha),
                            (self.x - body_length / 2, self.y - body_width / 2,
                             body_length, body_width))

        # 尻尾の描画
        tail_length = body_length * 0.9
        tail_width = body_width * 0.4
        tail_angle = self.angle + math.pi / 2 + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(tail_angle) * tail_length,
                              self.y + math.sin(tail_angle) * tail_length),
                             (self.x + math.cos(tail_angle) * tail_length * 0.8,
                              self.y + math.sin(tail_angle) * tail_length * 0.8)])

    def _draw_eel(self, screen: pygame.Surface, color: Tuple[int, int, int],
                  alpha: int, body_length: float, body_width: float):
        """ウナギの描画"""
        pygame.draw.ellipse(screen, (*color, alpha),
                            (self.x - body_length / 2, self.y - body_width / 2,
                             body_length, body_width))

        # 尻尾の描画
        tail_length = body_length * 0.5
        tail_width = body_width * 0.2
        tail_angle = self.angle + math.pi / 2 + self.tail_swing

        pygame.draw.polygon(screen, (*color, alpha),
                            [(self.x, self.y),
                             (self.x + math.cos(tail_angle) * tail_length,
                              self.y + math.sin(tail_angle) * tail_length),
                             (self.x + math.cos(tail_angle) * tail_length * 0.7,
                              self.y + math.sin(tail_angle) * tail_length * 0.7)])

    def _draw_generic_fish(self, screen: pygame.Surface, color: Tuple[int, int, int],
                            alpha: int, body_length: float, body_width: float):
        """一般的な魚の描画（改良版）"""
        cos_angle = math.cos(self.angle)
        sin_angle = math.sin(self.angle)

        # 体の中心
        body_x = self.x
        body_y = self.y

        # 魚の体をより魚らしい形に（複数の楕円で構成）
        # メインボディ
        main_body_rect = pygame.Rect(body_x - body_length/2, body_y - body_width/2,
                                   body_length * 0.8, body_width)

        if alpha >= 255:
            pygame.draw.ellipse(screen, color, main_body_rect)
            # 頭部（少し小さく）
            head_rect = pygame.Rect(body_x + body_length*0.2, body_y - body_width*0.3,
                                  body_length * 0.3, body_width * 0.6)
            pygame.draw.ellipse(screen, color, head_rect)
        else:
            temp_surface = pygame.Surface((body_length*2, body_width*2), pygame.SRCALPHA)
            pygame.draw.ellipse(temp_surface, (*color, alpha),
                              (body_length/2, body_width/2, body_length * 0.8, body_width))
            pygame.draw.ellipse(temp_surface, (*color, alpha),
                              (body_length*0.7, body_width*0.35, body_length * 0.3, body_width * 0.6))
            screen.blit(temp_surface, (body_x - body_length, body_y - body_width))

        # 尻尾（より流線型に）
        tail_x = body_x - cos_angle * body_length * 0.4
        tail_y = body_y - sin_angle * body_length * 0.4
        tail_size = body_width * 0.5

        # 上下に分かれた尻尾
        tail_swing_factor = self.tail_swing
        upper_tail = [
            (tail_x, tail_y),
            (tail_x - cos_angle * tail_size * 1.2 + sin_angle * tail_size * 0.3 * tail_swing_factor,
             tail_y - sin_angle * tail_size * 1.2 - cos_angle * tail_size * 0.3 * tail_swing_factor),
            (tail_x - cos_angle * tail_size * 0.8, tail_y - sin_angle * tail_size * 0.8)
        ]

        lower_tail = [
            (tail_x, tail_y),
            (tail_x - cos_angle * tail_size * 1.2 - sin_angle * tail_size * 0.3 * tail_swing_factor,
             tail_y - sin_angle * tail_size * 1.2 + cos_angle * tail_size * 0.3 * tail_swing_factor),
            (tail_x - cos_angle * tail_size * 0.8, tail_y - sin_angle * tail_size * 0.8)
        ]

        if alpha >= 255:
            pygame.draw.polygon(screen, color, upper_tail)
            pygame.draw.polygon(screen, color, lower_tail)
        else:
            temp_surface = pygame.Surface((tail_size*4, tail_size*4), pygame.SRCALPHA)
            offset_x, offset_y = tail_size*2, tail_size*2

            adjusted_upper = [(p[0] - tail_x + offset_x, p[1] - tail_y + offset_y) for p in upper_tail]
            adjusted_lower = [(p[0] - tail_x + offset_x, p[1] - tail_y + offset_y) for p in lower_tail]

            pygame.draw.polygon(temp_surface, (*color, alpha), adjusted_upper)
            pygame.draw.polygon(temp_surface, (*color, alpha), adjusted_lower)
            screen.blit(temp_surface, (tail_x - offset_x, tail_y - offset_y))

        # 背びれ
        dorsal_x = body_x - cos_angle * body_length * 0.1
        dorsal_y = body_y - sin_angle * body_length * 0.1
        dorsal_size = body_width * 0.3

        dorsal_fin = [
            (dorsal_x, dorsal_y),
            (dorsal_x + sin_angle * dorsal_size * 0.8, dorsal_y - cos_angle * dorsal_size * 0.8),
            (dorsal_x + sin_angle * dorsal_size * 0.5, dorsal_y - cos_angle * dorsal_size * 0.5)
        ]

        if alpha >= 255:
            pygame.draw.polygon(screen, color, dorsal_fin)
        else:
            temp_surface = pygame.Surface((dorsal_size*2, dorsal_size*2), pygame.SRCALPHA)
            offset_x, offset_y = dorsal_size, dorsal_size
            adjusted_dorsal = [(p[0] - dorsal_x + offset_x, p[1] - dorsal_y + offset_y) for p in dorsal_fin]
            pygame.draw.polygon(temp_surface, (*color, alpha), adjusted_dorsal)
            screen.blit(temp_surface, (dorsal_x - offset_x, dorsal_y - offset_y))

        # 目
        if body_width > 8:  # サイズが十分大きい場合のみ
            eye_size = max(2, body_width * 0.15)
            eye_x = body_x + cos_angle * body_length * 0.3 + sin_angle * body_width * 0.2
            eye_y = body_y + sin_angle * body_length * 0.3 - cos_angle * body_width * 0.2

            # 白い目
            pygame.draw.circle(screen, (255, 255, 255), (int(eye_x), int(eye_y)), int(eye_size))
            # 黒い瞳
            pupil_size = max(1, eye_size * 0.6)
            pygame.draw.circle(screen, (0, 0, 0), (int(eye_x), int(eye_y)), int(pupil_size))

    def set_school_members(self, member_pids: List[int], is_leader: bool = False):
        """群れのメンバーを設定"""
        self.school_members = member_pids
        self.is_leader = is_leader

    def calculate_flocking_forces(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
        """群れ行動のための力を計算（ボイドアルゴリズム）"""
        if not nearby_fish:
            return 0.0, 0.0

        # 3つの基本的な群れ行動
        sep_x, sep_y = self._calculate_separation(nearby_fish)
        ali_x, ali_y = self._calculate_alignment(nearby_fish)
        coh_x, coh_y = self._calculate_cohesion(nearby_fish)

        # 重み付きで合成
        separation_weight = 2.0
        alignment_weight = 1.0
        cohesion_weight = 1.0

        force_x = (sep_x * separation_weight +
                  ali_x * alignment_weight +
                  coh_x * cohesion_weight)
        force_y = (sep_y * separation_weight +
                  ali_y * alignment_weight +
                  coh_y * cohesion_weight)

        # 力を制限
        max_force = 0.5
        force_magnitude = math.sqrt(force_x**2 + force_y**2)
        if force_magnitude > max_force:
            force_x = (force_x / force_magnitude) * max_force
            force_y = (force_y / force_magnitude) * max_force

        return force_x, force_y

    def _calculate_separation(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
        """分離：近すぎる魚から離れる"""
        force_x = 0.0
        force_y = 0.0
        count = 0

        for fish in nearby_fish:
            distance = math.sqrt((self.x - fish.x)**2 + (self.y - fish.y)**2)
            if 0 < distance < self.separation_distance:
                # 自分から相手への方向の逆方向に力を加える
                diff_x = self.x - fish.x
                diff_y = self.y - fish.y
                # 距離で重み付け（近いほど強い力）
                weight = self.separation_distance / distance
                force_x += diff_x * weight
                force_y += diff_y * weight
                count += 1

        if count > 0:
            force_x /= count
            force_y /= count

        return force_x, force_y

    def _calculate_alignment(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
        """整列：近くの魚と同じ方向に泳ぐ"""
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
            # 現在の速度との差分を力とする
            force_x = avg_vx - self.vx
            force_y = avg_vy - self.vy
            return force_x, force_y

        return 0.0, 0.0

    def _calculate_cohesion(self, nearby_fish: List['Fish']) -> Tuple[float, float]:
        """結束：近くの魚の中心に向かう"""
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
            # 中心への方向に力を加える
            force_x = (center_x - self.x) * 0.01
            force_y = (center_y - self.y) * 0.01
            return force_x, force_y

        return 0.0, 0.0

    def _draw_speech_bubble(self, screen: pygame.Surface, message: str,
                             font: pygame.font.Font = None, text_renderer=None):
        """会話吹き出しの描画"""
        if not message:
            return

        # フォントの設定（引数で指定されたフォントを優先）
        if font is None:
            try:
                font = pygame.font.Font(None, 12)
            except Exception:
                font = pygame.font.SysFont("Arial", 12)

        # テキストのレンダリング
        try:
            if text_renderer:
                text_surface = text_renderer(message, font, (0, 0, 0))
            else:
                text_surface = font.render(message, True, (0, 0, 0))
        except Exception:
            safe_message = message.encode('ascii', 'replace').decode('ascii')
            try:
                text_surface = font.render(safe_message, True, (0, 0, 0))
            except Exception:
                return
        text_rect = text_surface.get_rect()

        # 吹き出しの位置とサイズ
        bubble_margin = 5
        bubble_width = text_rect.width + bubble_margin * 2
        bubble_height = text_rect.height + bubble_margin * 2

        # 魚の上に吹き出しを配置
        bubble_x = self.x - bubble_width // 2
        bubble_y = self.y - bubble_height - 20

        # 画面外に出ないように調整
        bubble_x = max(5, min(bubble_x, screen.get_width() - bubble_width - 5))
        bubble_y = max(5, bubble_y)

        # 吹き出しのクリック領域を記録
        self.bubble_rect = (bubble_x, bubble_y, bubble_width, bubble_height)

        # 吹き出しの背景
        bubble_surface = pygame.Surface((bubble_width, bubble_height), pygame.SRCALPHA)
        pygame.draw.rect(bubble_surface, (0, 0, 0, 180),
                        (0, 0, bubble_width, bubble_height), border_radius=8)
        pygame.draw.rect(bubble_surface, (255, 255, 255, 220),
                        (2, 2, bubble_width-4, bubble_height-4), border_radius=6)

        # テキストを描画
        text_x = bubble_margin
        text_y = bubble_margin
        bubble_surface.blit(text_surface, (text_x, text_y))

        # 吹き出しの尻尾（三角形）
        tail_points = [
            (bubble_width // 2, bubble_height),
            (bubble_width // 2 - 8, bubble_height + 10),
            (bubble_width // 2 + 8, bubble_height + 10)
        ]
        pygame.draw.polygon(bubble_surface, (255, 255, 255, 220), tail_points)

        # 画面に描画
        screen.blit(bubble_surface, (bubble_x, bubble_y))
