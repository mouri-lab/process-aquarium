"""
pyglet_draw_utils.py

pygame 版描画処理を pyglet へ忠実移植する際に再利用する共通ユーティリティ群。
Task: 共通描画ユーティリティ追加 (Todo #2)

方針:
 - Fish / Aquarium 双方から呼び出す低レベル図形ヘルパーを集約し、後続の忠実移植ステップで重複コードを減らす
 - ここではまだ最終的な『完全一致』調整 (寸法/アルファカーブ) を確定しない。まず API を安定化し後段で fish_pyglet.py から差し替えやすくする
 - pyglet 不在時でも import 可能 (関数内ガード) にしてテスト容易性を確保

含まれる機能 (初期セット):
 - draw_ellipse / draw_ellipse_outline: 楕円 (頂点数は半径に応じて自動)
 - draw_polygon: 任意ポリゴン (GL_TRIANGLE_FAN or 切り替え)
 - draw_rounded_rect: 角丸矩形 (吹き出しや UI パネル用)
 - draw_speech_bubble: 角丸 + テール (吹き出し統合ラッパ)
 - draw_ripples: 重ね円 (巨大魚波紋エフェクト準備)
 - draw_lightning_polyline: 稲妻ポリライン (巨大魚追加エフェクト準備)

各関数は戻り値として生成した vertex_list / shape のリストを返し、呼び出し側で保持 or 破棄を選択できるようにする。
後続タスク (#4 以降) でアルファ減衰 / 時間進行に合わせた半径比などを pygame 版ロジックへ合わせる。
"""
from __future__ import annotations
from typing import List, Sequence, Tuple, Optional, Union, Any
import math
import random

try:  # pyglet が無い環境(ヘッドレスCI等)でも import だけは通す
    import pyglet  # type: ignore
    from pyglet import gl
    from pyglet import shapes
except Exception:  # pragma: no cover
    pyglet = None  # type: ignore
    gl = None      # type: ignore
    shapes = None  # type: ignore

ColorRGB = Tuple[int, int, int]
ColorRGBA = Tuple[int, int, int, int]
ColorLike = Union[ColorRGB, ColorRGBA]

# --------------------------------------------------------------------------------------
# 基本図形
# --------------------------------------------------------------------------------------

def _color_to_rgba(color: ColorLike, alpha: Optional[int]) -> ColorRGBA:
    if len(color) == 4:  # type: ignore[arg-type]
        r, g, b, a = color  # type: ignore[misc]
        if alpha is not None:
            a = alpha
        return int(r), int(g), int(b), int(a)
    r, g, b = color  # type: ignore[misc]
    a = 255 if alpha is None else alpha
    return int(r), int(g), int(b), int(a)

def draw_polygon(points: Sequence[Tuple[float, float]], color: ColorLike, alpha: Optional[int] = None, batch: Optional[Any] = None, filled: bool = True):
    """任意ポリゴン描画。
    filled=True の場合 TRIANGLE_FAN、False の場合 LINE_LOOP 相当。
    """
    if not pyglet or not points:
        return None
    rgba = _color_to_rgba(color, alpha)
    position_data: List[float] = []
    for x, y in points:
        position_data.extend([x, y, 0.0])
    count = len(points)
    color_data: List[int] = []
    for _ in range(count):
        color_data.extend(rgba)
    if filled:
        return pyglet.graphics.draw(
            count,
            gl.GL_TRIANGLE_FAN,
            position=('f', position_data),
            colors=('B', color_data)
        )
    else:
        # LINE_LOOP が無い/合わない場合は strip + 最後に最初の点を再度追加
        flat_line: List[float] = []
        flat_line.extend(position_data)
        flat_line.extend([points[0][0], points[0][1], 0.0])
        color_line: List[int] = []
        for _ in range(count + 1):
            color_line.extend(rgba)
        return pyglet.graphics.draw(
            count + 1,
            gl.GL_LINE_STRIP,
            position=('f', flat_line),
            colors=('B', color_line)
        )

def draw_ellipse(cx: float, cy: float, rx: float, ry: float, color: ColorLike, alpha: Optional[int] = None, batch: Optional[Any] = None, segments: Optional[int] = None):
    """楕円 (塗りつぶし)。pygame の ellipse 相当。
    segments が未指定なら周長近似に基づき自動 (最小 16)。"""
    if not pyglet or rx <= 0 or ry <= 0:
        return None
    # 周長近似 (Ramanujan) で分割数目安
    if segments is None:
        h = ((rx - ry)**2) / ((rx + ry)**2) if (rx + ry) else 0
        circumference = math.pi * (rx + ry) * (1 + (3*h)/(10 + math.sqrt(4 - 3*h)))
        segments = max(16, int(circumference / 6))  # 1セグメント ~6px
    pts = []
    for i in range(segments):
        t = 2 * math.pi * i / segments
        pts.append((cx + math.cos(t) * rx, cy + math.sin(t) * ry))
    return draw_polygon(pts, color, alpha, batch, filled=True)

def draw_ellipse_outline(cx: float, cy: float, rx: float, ry: float, color: ColorLike, alpha: Optional[int] = None, batch: Optional[Any] = None, segments: Optional[int] = None):
    if not pyglet or rx <= 0 or ry <= 0:
        return None
    if segments is None:
        h = ((rx - ry)**2) / ((rx + ry)**2) if (rx + ry) else 0
        circumference = math.pi * (rx + ry) * (1 + (3*h)/(10 + math.sqrt(4 - 3*h)))
        segments = max(16, int(circumference / 6))
    pts = []
    for i in range(segments):
        t = 2 * math.pi * i / segments
        pts.append((cx + math.cos(t) * rx, cy + math.sin(t) * ry))
    return draw_polygon(pts, color, alpha, batch, filled=False)

# --------------------------------------------------------------------------------------
# 角丸矩形 / 吹き出し
# --------------------------------------------------------------------------------------

def draw_rounded_rect(x: float, y: float, w: float, h: float, radius: float, color: ColorLike, alpha: Optional[int] = None, batch: Optional[Any] = None, corner_segments: int = 6):
    """角丸矩形 (単層)。pygame の複数 draw.rect + circle 合成を一体化。
    単純化: 4隅を corner_segments 分割のクォーター円で補間し TRIANGLE_FAN。"""
    if not pyglet:
        return None
    radius = max(0, min(radius, min(w, h) / 2))
    cx0, cy0 = x + radius, y + radius  # 左下角丸中心
    cx1, cy1 = x + w - radius, y + radius  # 右下
    cx2, cy2 = x + w - radius, y + h - radius  # 右上
    cx3, cy3 = x + radius, y + h - radius  # 左上
    pts: List[Tuple[float, float]] = []
    def arc(cx, cy, start_ang, end_ang):
        steps = corner_segments
        for i in range(steps + 1):
            t = i / steps
            ang = start_ang + (end_ang - start_ang) * t
            pts.append((cx + math.cos(ang) * radius, cy + math.sin(ang) * radius))
    # 左下(180→270), 右下(270→360), 右上(0→90), 左上(90→180)
    arc(cx0, cy0, math.pi, 1.5 * math.pi)
    arc(cx1, cy1, 1.5 * math.pi, 2 * math.pi)
    arc(cx2, cy2, 0, 0.5 * math.pi)
    arc(cx3, cy3, 0.5 * math.pi, math.pi)
    # 中央近似: TRIANGLE_FAN 用に中心点を先頭に追加
    center = (x + w / 2, y + h / 2)
    fan_pts = [center] + pts
    return draw_polygon(fan_pts, color, alpha, batch, filled=True)

def draw_speech_bubble(x: float, y: float, w: float, h: float, tail_cx: float, tail_height: float, color_bg: ColorRGBA, color_border: ColorRGBA, batch: Optional[Any], border_thickness: int = 2, radius: float = 8, inner: bool = False, inner_inset: int = 2):
    """吹き出し (角丸 + テール + 枠 + 任意で内側レイヤ)。
    Parameters:
      inner: True の場合、内側にもう一段 (白など) の角丸を描く（pygame 二層表現再現）
      inner_inset: 内側レイヤの余白
    戻り値: dict(outer=..., inner=..., tail=..., border=...)
    """
    if not pyglet:
        return None
    items = {}
    # 背景
    rect_bg = draw_rounded_rect(x, y, w, h, radius, color_bg, color_bg[3], batch)
    items['outer'] = rect_bg
    # テール三角
    tail_half_w = min(20, w * 0.25)
    tail_pts = [
        (tail_cx - tail_half_w / 2, y),
        (tail_cx + tail_half_w / 2, y),
        (tail_cx, y - tail_height)
    ]
    tail = draw_polygon(tail_pts, color_bg, color_bg[3], batch, filled=True)
    items['tail'] = tail

    # 内側レイヤ
    if inner:
        inset = inner_inset
        inner_w = max(0, w - inset * 2)
        inner_h = max(0, h - inset * 2)
        inner_rect = draw_rounded_rect(x + inset, y + inset, inner_w, inner_h, max(0, radius - 2), color_border, color_border[3], batch)
        items['inner'] = inner_rect
    # 枠 (簡易: 外周線 + テール線)
    border_pts = []
    # 角丸矩形外周 (再計算; OUTLINE 用)
    radius = max(0, min(radius, min(w, h) / 2))
    cx0, cy0 = x + radius, y + radius
    cx1, cy1 = x + w - radius, y + radius
    cx2, cy2 = x + w - radius, y + h - radius
    cx3, cy3 = x + radius, y + h - radius
    def arc_outline(cx, cy, start_ang, end_ang):
        steps = 16
        for i in range(steps + 1):
            t = i / steps
            ang = start_ang + (end_ang - start_ang) * t
            border_pts.append((cx + math.cos(ang) * radius, cy + math.sin(ang) * radius))
    arc_outline(cx0, cy0, math.pi, 1.5 * math.pi)
    arc_outline(cx1, cy1, 1.5 * math.pi, 2 * math.pi)
    arc_outline(cx2, cy2, 0, 0.5 * math.pi)
    arc_outline(cx3, cy3, 0.5 * math.pi, math.pi)
    # テール境界を外周に接続
    border_pts.append((tail_cx + tail_half_w / 2, y))
    border_pts.append((tail_cx, y - tail_height))
    border_pts.append((tail_cx - tail_half_w / 2, y))
    draw_polygon(border_pts, color_border, color_border[3], batch, filled=False)
    return items

# --------------------------------------------------------------------------------------
# エフェクト: 波紋 / 稲妻 (初期バージョン - 後でパラメータ微調整)
# --------------------------------------------------------------------------------------

def draw_ripples(cx: float, cy: float, base_radius: float, count: int, color: ColorLike, alpha: int, phase: float, radius_step: float = 1.0, batch: Optional[Any] = None):
    if not pyglet:
        return []
    items = []
    for i in range(count):
        # 位相差で半径ゆらぎ
        r = base_radius * (1 + i * radius_step + 0.15 * math.sin(phase + i * 0.5))
        a = max(0, int(alpha * (0.35 - i * 0.08)))
        if a <= 5:
            continue
        items.append(draw_ellipse_outline(cx, cy, r, r, color, a, batch))
    return items

def draw_lightning_polyline(cx: float, cy: float, angle: float, length: float, segments: int, color: ColorLike, alpha: int, randomness: float = 0.4, batch: Optional[Any] = None):
    if not pyglet or segments < 1:
        return None
    rgba = _color_to_rgba(color, alpha)
    pts: List[float] = []
    for s in range(segments + 1):
        t = s / segments
        # 基本半径
        r = length * t
        # 角度にランダムゆらぎ (末端ほど小さく)
        ang = angle + (random.uniform(-randomness, randomness) * (1 - t))
        px = cx + math.cos(ang) * r
        py = cy + math.sin(ang) * r
        pts.extend([px, py])
    vertex_count = len(pts) // 2
    positions: List[float] = []
    for i in range(0, len(pts), 2):
        positions.extend([pts[i], pts[i + 1], 0.0])
    color_data: List[int] = []
    for _ in range(vertex_count):
        color_data.extend(rgba)
    return pyglet.graphics.draw(
        vertex_count,
        gl.GL_LINE_STRIP,
        position=('f', positions),
        colors=('B', color_data)
    )

__all__ = [
    'draw_polygon', 'draw_ellipse', 'draw_ellipse_outline', 'draw_rounded_rect',
    'draw_speech_bubble', 'draw_ripples', 'draw_lightning_polyline'
]
