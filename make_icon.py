#!/usr/bin/env python3
"""
アイコン生成スクリプト（標準ライブラリのみ）
生成物: icon.png / icon.icns（Mac用）/ icon.ico（Windows用）
"""
import zlib, struct, math, os

# ------------------------------------------------------------------ 描画エンジン

SIZE = 256

def new_canvas(size):
    return [(0, 0, 0, 0)] * (size * size)

def hex_rgb(h):
    h = h.lstrip('#')
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def blend(px, size, x, y, color, alpha=255):
    if not (0 <= x < size and 0 <= y < size):
        return
    r, g, b = color
    er, eg, eb, ea = px[y * size + x]
    a = alpha / 255
    px[y * size + x] = (
        int(er * (1-a) + r * a),
        int(eg * (1-a) + g * a),
        int(eb * (1-a) + b * a),
        min(255, ea + alpha),
    )

def draw_circle(px, size, cx, cy, radius, color):
    for y in range(max(0, cy-radius-2), min(size, cy+radius+2)):
        for x in range(max(0, cx-radius-2), min(size, cx+radius+2)):
            d = math.hypot(x - cx, y - cy)
            if d < radius:
                blend(px, size, x, y, color, 255)
            elif d < radius + 1.5:
                blend(px, size, x, y, color, int((radius + 1.5 - d) / 1.5 * 255))

def draw_rrect(px, size, x1, y1, x2, y2, color, r=0):
    """角丸四角形"""
    for y in range(max(0, y1), min(size, y2 + 1)):
        for x in range(max(0, x1), min(size, x2 + 1)):
            # コーナー判定
            if x < x1+r and y < y1+r:
                cx, cy = x1+r, y1+r
            elif x > x2-r and y < y1+r:
                cx, cy = x2-r, y1+r
            elif x < x1+r and y > y2-r:
                cx, cy = x1+r, y2-r
            elif x > x2-r and y > y2-r:
                cx, cy = x2-r, y2-r
            else:
                blend(px, size, x, y, color, 255)
                continue
            d = math.hypot(x - cx, y - cy)
            if d < r:
                blend(px, size, x, y, color, 255)
            elif d < r + 1.5:
                blend(px, size, x, y, color, int((r + 1.5 - d) / 1.5 * 255))

def draw_triangle(px, size, pts, color):
    xs = [p[0] for p in pts]; ys = [p[1] for p in pts]
    def sign(p1, p2, p3):
        return (p1[0]-p3[0])*(p2[1]-p3[1]) - (p2[0]-p3[0])*(p1[1]-p3[1])
    for y in range(max(0, min(ys)), min(size, max(ys)+1)):
        for x in range(max(0, min(xs)), min(size, max(xs)+1)):
            d1 = sign((x,y), pts[0], pts[1])
            d2 = sign((x,y), pts[1], pts[2])
            d3 = sign((x,y), pts[2], pts[0])
            if not ((d1<0 or d2<0 or d3<0) and (d1>0 or d2>0 or d3>0)):
                blend(px, size, x, y, color, 255)

# ------------------------------------------------------------------ PNG エンコーダ

def encode_png(px, size):
    def chunk(tag, data):
        c = tag + data
        return struct.pack('>I', len(data)) + c + struct.pack('>I', zlib.crc32(c) & 0xffffffff)
    raw = b''.join(
        b'\x00' + b''.join(bytes(px[y*size+x]) for x in range(size))
        for y in range(size)
    )
    ihdr = struct.pack('>IIBBBBB', size, size, 8, 6, 0, 0, 0)
    return (b'\x89PNG\r\n\x1a\n'
            + chunk(b'IHDR', ihdr)
            + chunk(b'IDAT', zlib.compress(raw, 9))
            + chunk(b'IEND', b''))

# ------------------------------------------------------------------ アイコン描画

S   = SIZE
px  = new_canvas(S)

BG    = hex_rgb('#1e1e2e')  # 背景（ダーク紺）
BLUE  = hex_rgb('#89b4fa')  # 左バブル（青）
GREEN = hex_rgb('#a6e3a1')  # 右バブル（緑）
WHITE = hex_rgb('#cdd6f4')  # ハイライト

# 背景サークル
draw_circle(px, S, S//2, S//2, S//2 - 2, BG)

# --- 左の吹き出し（青・手前） ---
draw_rrect(px, S, 24,  50, 162, 140, BLUE,  r=22)
draw_triangle(px, S, [(36, 138), (72, 138), (28, 172)], BLUE)

# --- 右の吹き出し（緑・奥） ---
draw_rrect(px, S, 90, 108, 228, 198, GREEN, r=22)
draw_triangle(px, S, [(182, 196), (218, 196), (224, 230)], GREEN)

# ハイライト（青バブル内に小さい白丸を3つ）
for i, bx in enumerate([60, 93, 126]):
    draw_circle(px, S, bx, 95, 8, WHITE)

# ハイライト（緑バブル内）
for i, bx in enumerate([130, 163, 196]):
    draw_circle(px, S, bx, 153, 8, WHITE)

# ------------------------------------------------------------------ ファイル出力

here = os.path.dirname(os.path.abspath(__file__))
png_data = encode_png(px, S)

# icon.png
png_path = os.path.join(here, 'icon.png')
with open(png_path, 'wb') as f:
    f.write(png_data)
print(f"✓ icon.png")

# icon.icns（macOS）— ic08 = 256x256 PNG
icns_body = b'ic08' + struct.pack('>I', 8 + len(png_data)) + png_data
icns_data = b'icns' + struct.pack('>I', 8 + len(icns_body)) + icns_body
with open(os.path.join(here, 'icon.icns'), 'wb') as f:
    f.write(icns_data)
print(f"✓ icon.icns（Mac用）")

# icon.ico（Windows）— 256x256 PNG 埋め込み形式
ico  = struct.pack('<HHH', 0, 1, 1)
ico += struct.pack('<BBBBHHII', 0, 0, 0, 0, 1, 32, len(png_data), 22)
ico += png_data
with open(os.path.join(here, 'icon.ico'), 'wb') as f:
    f.write(ico)
print(f"✓ icon.ico（Windows用）")

print("\nアイコン生成完了！")
