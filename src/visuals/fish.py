"""
Digital Life Aquarium - Fish Entity
デジタル生命体（プロセス）の視覚的表現を管理するクラス
"""

import pygame
import math
import random
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
        self.parent_pid: Optional[int] = None

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

        # 視覚的属性
        self.base_size = 10
        self.current_size = self.base_size
        self.color = self._generate_color()
        self.alpha = 255
        self.glow_intensity = 0

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
                          thread_count: int, parent_pid: Optional[int] = None):
        """プロセスデータの更新"""
        self.memory_percent = memory_percent
        self.cpu_percent = cpu_percent
        self.thread_count = thread_count
        self.parent_pid = parent_pid

        # メモリ使用量に基づくサイズ調整
        memory_factor = 1.0 + (memory_percent / 100.0) * 2.0  # 1.0～3.0倍
        self.current_size = self.base_size * memory_factor

        # CPU使用率に基づく光り方
        self.glow_intensity = min(cpu_percent * 10, 255)

        # CPU使用率に基づく移動速度調整
        speed_factor = 1.0 + (cpu_percent / 100.0) * 3.0
        max_speed = 2.0 * speed_factor
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
        """死亡イベントの設定"""
        self.is_dying = True
        self.death_progress = 0.0

    def update_position(self, screen_width: int, screen_height: int, nearby_fish: List['Fish'] = None):
        """位置の更新とバウンド処理（群れ行動対応版）"""
        # 年齢を増やす
        self.age += 1

        # スポーン時のアニメーション
        if self.is_spawning:
            self.spawn_progress += 0.05
            if self.spawn_progress >= 1.0:
                self.is_spawning = False
                self.spawn_progress = 1.0

        # 死亡時のアニメーション
        if self.is_dying:
            self.death_progress += 0.03
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

        # フォーク時の白い光り
        if self.recently_forked:
            glow_factor = self.fork_glow_timer / 60.0
            r = int(r + (255 - r) * glow_factor)
            g = int(g + (255 - g) * glow_factor)
            b = int(b + (255 - b) * glow_factor)

        # CPU使用時の光り
        if self.glow_intensity > 0:
            intensity = self.glow_intensity / 255.0
            r = min(255, int(r + intensity * 50))
            g = min(255, int(g + intensity * 50))
            b = min(255, int(b + intensity * 50))

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

    def get_thread_satellites(self) -> list:
        """スレッド数に応じた衛星の位置を計算"""
        satellites = []
        if self.thread_count > 1:
            satellite_count = min(self.thread_count - 1, 8)  # 最大8個まで
            for i in range(satellite_count):
                angle = (2 * math.pi * i) / satellite_count + self.age * 0.02
                radius = self.current_size * 1.5
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
        swim_speed = 0.1 + speed * 0.1
        self.swim_cycle += swim_speed
        self.tail_swing = math.sin(self.swim_cycle) * (0.2 + speed * 0.1)

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

    def draw(self, screen: pygame.Surface):
        """Fishの描画（魚らしい見た目版）"""
        if self.death_progress >= 1.0:
            return

        # 現在の描画属性を取得
        color = self.get_display_color()
        alpha = self.get_display_alpha()
        size = self.get_display_size()

        # サイズが小さすぎる場合はスキップ
        if size < 2:
            return

        # メイン生命体の描画（魚の形状）
        if alpha > 20:  # 透明度が低すぎる場合はスキップ
            self._draw_fish_shape(screen, color, alpha, size)

        # スレッド衛星の描画（小魚の群れとして）
        if self.thread_count > 1 and size > 5:
            satellites = self.get_thread_satellites()
            # 最大4個まで描画
            for i, (sat_x, sat_y) in enumerate(satellites[:4]):
                sat_size = max(2, size * 0.2)
                # 小さな魚として描画
                self._draw_small_fish(screen, color, alpha//2, sat_x, sat_y, sat_size)

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
