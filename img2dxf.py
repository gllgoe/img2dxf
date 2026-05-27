#!/usr/bin/env python3
"""
图片转 DXF 工具
支持: JPG/PNG/BMP/TIFF 等图片 → DXF (AutoCAD格式)

用法:
  python img2dxf.py input.jpg                    # 输出 input.dxf
  python img2dxf.py input.jpg -o output.dxf      # 指定输出文件名
  python img2dxf.py input.jpg --mode polygon      # 多边形模式(适合建筑图)
  python img2dxf.py input.jpg --mode spline       # 样条曲线模式(适合手绘)
  python img2dxf.py input.jpg --colormode color   # 彩色模式(保留颜色)
  python img2dxf.py input.jpg --scale 2.0         # 放大2倍
  python img2dxf.py ./images/                     # 批量处理目录下所有图片
"""

import argparse
import sys
import os
import re
import math
from pathlib import Path
import xml.etree.ElementTree as ET

import vtracer
import ezdxf
from PIL import Image


def parse_svg_transform(transform_str: str):
    """解析 SVG transform 属性，返回 (tx, ty) 平移量"""
    if not transform_str:
        return 0, 0
    
    # 匹配 translate(x, y) 或 translate(x y)
    m = re.search(r'translate\(\s*([-\d.]+)[,\s]+([-\d.]+)\s*\)', transform_str)
    if m:
        return float(m.group(1)), float(m.group(2))
    return 0, 0


def parse_svg_path_commands(d: str):
    """解析 SVG path 的 d 属性，提取所有坐标点（处理 M/L/C/Z 等命令）"""
    points = []
    current_x, current_y = 0, 0
    
    # 提取命令和坐标
    tokens = re.findall(r'[MmLlHhVvCcSsQqTtAaZz]|[-+]?[0-9]*\.?[0-9]+(?:e[-+]?[0-9]+)?', d)
    
    i = 0
    cmd = ''
    while i < len(tokens):
        if re.match(r'[MmLlHhVvCcSsQqTtAaZz]', tokens[i]):
            cmd = tokens[i]
            i += 1
        
        if cmd in ('M', 'm', 'L', 'l'):
            if i + 1 < len(tokens):
                x, y = float(tokens[i]), float(tokens[i+1])
                if cmd.islower():
                    x += current_x
                    y += current_y
                current_x, current_y = x, y
                points.append((x, y))
                i += 2
            else:
                break
        elif cmd in ('H', 'h'):
            if i < len(tokens):
                x = float(tokens[i])
                if cmd.islower():
                    x += current_x
                current_x = x
                points.append((current_x, current_y))
                i += 1
            else:
                break
        elif cmd in ('V', 'v'):
            if i < len(tokens):
                y = float(tokens[i])
                if cmd.islower():
                    y += current_y
                current_y = y
                points.append((current_x, current_y))
                i += 1
            else:
                break
        elif cmd in ('C', 'c'):  # 三次贝塞尔
            if i + 5 < len(tokens):
                coords = [float(tokens[j]) for j in range(i, i+6)]
                if cmd.islower():
                    coords = [coords[j] + (current_x if j%2==0 else current_y) for j in range(6)]
                # 简化：只取控制点和终点
                points.extend([(coords[0], coords[1]), (coords[2], coords[3]), (coords[4], coords[5])])
                current_x, current_y = coords[4], coords[5]
                i += 6
            else:
                break
        elif cmd in ('Q', 'q'):  # 二次贝塞尔
            if i + 3 < len(tokens):
                coords = [float(tokens[j]) for j in range(i, i+4)]
                if cmd.islower():
                    coords = [coords[j] + (current_x if j%2==0 else current_y) for j in range(4)]
                points.extend([(coords[0], coords[1]), (coords[2], coords[3])])
                current_x, current_y = coords[2], coords[3]
                i += 4
            else:
                break
        elif cmd in ('Z', 'z'):
            if points:
                points.append(points[0])  # 闭合
            i += 1
        else:
            i += 1
    
    return points


def svg_to_dxf(svg_path: str, dxf_path: str, img_width: int, img_height: int, scale: float, colormode: str):
    """将 SVG 文件转换为 DXF，正确处理 transform"""
    
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    doc.layers.add("IMAGE_OUTLINE", color=7)
    
    if colormode == "color":
        for i in range(10):
            doc.layers.add(f"COLOR_{i}", color=i + 1)
    
    tree = ET.parse(svg_path)
    root = tree.getroot()
    
    y_offset = img_height * scale
    
    line_count = 0
    polyline_count = 0
    path_count = 0
    
    for path_elem in root.iter('{http://www.w3.org/2000/svg}path'):
        d = path_elem.get('d', '')
        transform = path_elem.get('transform', '')
        fill = path_elem.get('fill', '')
        
        # 解析变换
        tx, ty = parse_svg_transform(transform)
        
        # 解析路径
        raw_points = parse_svg_path_commands(d)
        if len(raw_points) < 2:
            continue
        
        # 应用变换和缩放，翻转Y轴
        scaled_points = []
        for x, y in raw_points:
            px = (x + tx) * scale
            py = y_offset - (y + ty) * scale
            scaled_points.append((px, py))
        
        # 确定颜色
        color_idx = 7  # 默认白色
        if colormode == "color" and fill and fill.startswith('#') and len(fill) >= 7:
            try:
                r, g, b = int(fill[1:3], 16), int(fill[3:5], 16), int(fill[5:7], 16)
                color_idx = rgb_to_aci(r, g, b)
            except:
                pass
        
        layer_name = f"COLOR_{color_idx % 10}" if colormode == "color" else "IMAGE_OUTLINE"
        
        # 分段写入（每段最多100个点避免过长）
        chunk_size = 100
        for start_idx in range(0, len(scaled_points), chunk_size - 10):
            end_idx = min(start_idx + chunk_size, len(scaled_points))
            chunk = scaled_points[start_idx:end_idx]
            if len(chunk) >= 2:
                msp.add_lwpolyline(chunk, dxfattribs={'layer': layer_name, 'color': color_idx})
                polyline_count += 1
        
        path_count += 1
    
    doc.saveas(dxf_path)
    print(f"   📊 共转换: {path_count} 个路径, {polyline_count} 条多段线")


def convert_image_to_dxf(
    input_path: str,
    output_path: str = None,
    mode: str = "polygon",
    colormode: str = "color",
    scale: float = 1.0,
    filter_speckle: int = 4,
    color_precision: int = 6,
    layer_difference: int = 16,
    corner_threshold: int = 60,
    length_threshold: int = 4,
    max_iterations: int = 10,
    splice_threshold: int = 45,
    path_precision: int = 3,
):
    """将图片转换为 DXF 文件"""
    
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    
    # vtracer不支持TIF格式，需要先转换为PNG
    temp_png = None
    if input_path.suffix.lower() in ('.tif', '.tiff'):
        print(f"🔄 TIF格式，先转换为PNG...")
        temp_png = str(input_path) + ".temp.png"
        with Image.open(input_path) as img:
            if img.mode != 'L' and img.mode != 'RGB':
                img = img.convert('L')
            img.save(temp_png)
        input_path_for_vtracer = temp_png
    else:
        input_path_for_vtracer = str(input_path)
    
    if output_path is None:
        output_path = input_path.with_suffix('.dxf')
    
    print(f"📷 输入: {input_path}")
    print(f"📐 输出: {output_path}")
    
    with Image.open(input_path) as img:
        img_width, img_height = img.size
        print(f"📏 图片尺寸: {img_width} x {img_height}")
    
    print("🔄 Step 1: 图片矢量化 (vtracer)...")
    svg_path = str(input_path) + ".temp.svg"
    
    vtracer.convert_image_to_svg_py(
        image_path=input_path_for_vtracer,
        out_path=svg_path,
        colormode=colormode,
        hierarchical="stacked",
        mode=mode,
        filter_speckle=filter_speckle,
        color_precision=color_precision,
        layer_difference=layer_difference,
        corner_threshold=corner_threshold,
        length_threshold=length_threshold,
        max_iterations=max_iterations,
        splice_threshold=splice_threshold,
        path_precision=path_precision,
    )
    print("   ✅ SVG 矢量化完成")
    
    print("🔄 Step 2: SVG 转 DXF (ezdxf)...")
    svg_to_dxf(svg_path, str(output_path), img_width, img_height, scale, colormode)
    print("   ✅ DXF 转换完成")
    
    os.remove(svg_path)
    if temp_png and os.path.exists(temp_png):
        os.remove(temp_png)
    
    size_kb = os.path.getsize(output_path) / 1024
    print(f"\n🎉 转换完成!")
    print(f"   文件: {output_path}")
    print(f"   大小: {size_kb:.1f} KB")
    
    return str(output_path)


def rgb_to_aci(r: int, g: int, b: int) -> int:
    """RGB 转 AutoCAD 颜色索引"""
    colors = [
        (255, 0, 0), (255, 255, 0), (0, 255, 0), (0, 255, 255),
        (0, 0, 255), (255, 0, 255), (255, 255, 255), (128, 128, 128),
        (192, 192, 192), (0, 0, 0),
    ]
    min_dist = float('inf')
    best_idx = 7
    for i, (cr, cg, cb) in enumerate(colors):
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < min_dist:
            min_dist = dist
            best_idx = i + 1
    return best_idx


def batch_convert(input_dir: str, **kwargs):
    """批量转换目录下的所有图片"""
    input_dir = Path(input_dir)
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}
    image_files = [f for f in input_dir.iterdir() if f.suffix.lower() in image_extensions]
    
    if not image_files:
        print(f"❌ 目录 {input_dir} 中没有找到图片文件")
        return
    
    print(f"📁 找到 {len(image_files)} 个图片文件\n")
    
    results = []
    for img_file in image_files:
        try:
            output = convert_image_to_dxf(str(img_file), **kwargs)
            results.append((img_file.name, True, output))
        except Exception as e:
            results.append((img_file.name, False, str(e)))
            print(f"❌ {img_file.name} 转换失败: {e}\n")
    
    print("\n" + "=" * 50)
    print("📊 批量转换结果:")
    success = sum(1 for _, ok, _ in results if ok)
    print(f"   成功: {success}/{len(results)}")
    for name, ok, info in results:
        status = "✅" if ok else "❌"
        print(f"   {status} {name}")


def main():
    parser = argparse.ArgumentParser(description='图片转 DXF 工具')
    parser.add_argument('input', help='输入图片路径或目录')
    parser.add_argument('-o', '--output', help='输出 DXF 文件路径')
    parser.add_argument('--mode', choices=['polygon', 'spline'], default='polygon')
    parser.add_argument('--colormode', choices=['color', 'binary'], default='color')
    parser.add_argument('--scale', type=float, default=1.0)
    parser.add_argument('--filter-speckle', type=int, default=4)
    parser.add_argument('--color-precision', type=int, default=6)
    parser.add_argument('--corner-threshold', type=int, default=60)
    parser.add_argument('--length-threshold', type=int, default=4)
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    kwargs = dict(
        mode=args.mode,
        colormode=args.colormode,
        scale=args.scale,
        filter_speckle=args.filter_speckle,
        color_precision=args.color_precision,
        corner_threshold=args.corner_threshold,
        length_threshold=args.length_threshold,
    )
    
    if input_path.is_dir():
        batch_convert(str(input_path), **kwargs)
    elif input_path.is_file():
        convert_image_to_dxf(str(input_path), args.output, **kwargs)
    else:
        print(f"❌ 路径不存在: {input_path}")
        sys.exit(1)


if __name__ == '__main__':
    main()
