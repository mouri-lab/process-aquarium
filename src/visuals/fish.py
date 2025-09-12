"""
Digital Life Aquarium - Fish Entity
デジタル生命体（プロセス）の視覚的表現を管理するクラス
"""

import pygame
import math
import random
from typing import Tuple, Optional

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
    
    def update_position(self, screen_width: int, screen_height: int):
        """位置の更新とバウンド処理"""
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
        
        # ランダムな目標位置の変更（ゆらゆら泳ぐ効果）
        if random.random() < 0.01:  # 1%の確率で目標変更
            self.target_x = random.uniform(50, screen_width - 50)
            self.target_y = random.uniform(50, screen_height - 50)
        
        # 目標位置に向かって移動
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
    
    def draw(self, screen: pygame.Surface):
        """Fishの描画（最適化版）"""
        if self.death_progress >= 1.0:
            return
        
        # 現在の描画属性を取得
        color = self.get_display_color()
        alpha = self.get_display_alpha()
        size = self.get_display_size()
        
        # サイズが小さすぎる場合はスキップ
        if size < 2:
            return
        
        # メイン生命体の描画（シンプル版）
        if alpha > 20:  # 透明度が低すぎる場合はスキップ
            # 直接円を描画（半透明サーフェスの作成を避ける）
            if alpha >= 255:
                pygame.draw.circle(screen, color, (int(self.x), int(self.y)), int(size))
            else:
                # 半透明が必要な場合のみサーフェスを使用
                temp_surface = pygame.Surface((size * 2, size * 2), pygame.SRCALPHA)
                pygame.draw.circle(temp_surface, (*color, alpha), 
                                 (size, size), int(size))
                screen.blit(temp_surface, (self.x - size, self.y - size))
        
        # スレッド衛星の描画（簡素化）
        if self.thread_count > 1 and size > 5:
            satellites = self.get_thread_satellites()
            # 最大4個まで描画
            for i, (sat_x, sat_y) in enumerate(satellites[:4]):
                sat_size = max(2, size * 0.2)
                pygame.draw.circle(screen, color, (int(sat_x), int(sat_y)), int(sat_size))
    
    def __str__(self) -> str:
        return f"Fish(PID:{self.pid}, {self.name}, pos:({self.x:.1f},{self.y:.1f}))"
