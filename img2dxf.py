#!/usr/bin/env python3
"""
图片转 DXF 工具（原始轮廓版）
支持: JPG/PNG/BMP/TIFF 等图片 → DXF (AutoCAD格式)

用法:
  python img2dxf.py input.jpg                    # 输出 input.dxf
  python img2dxf.py input.jpg -o output.dxf      # 指定输出文件名
  python img2dxf.py ./images/                     # 批量处理目录下所有图片
"""

import argparse
import sys
import os
from pathlib import Path

import cv2
import numpy as np
import ezdxf
from PIL import Image


def convert_image_to_dxf(
    input_path: str,
    output_path: str = None,
    min_area: int = 3,
    sharpen: bool = True,
):
    """将图片转换为 DXF 文件（原始轮廓）"""
    
    input_path = Path(input_path)
    if not input_path.exists():
        raise FileNotFoundError(f"输入文件不存在: {input_path}")
    
    # TIF格式需要先转换为PNG
    temp_png = None
    if input_path.suffix.lower() in ('.tif', '.tiff'):
        print(f"🔄 TIF格式，先转换为PNG...")
        temp_png = str(input_path) + ".temp.png"
        with Image.open(input_path) as img:
            if img.mode != 'L' and img.mode != 'RGB':
                img = img.convert('L')
            img.save(temp_png)
        img = cv2.imread(temp_png, cv2.IMREAD_GRAYSCALE)
    else:
        img = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    
    if img is None:
        raise ValueError(f"无法读取图片: {input_path}")
    
    if output_path is None:
        output_path = str(input_path.with_suffix('.dxf'))
    
    y_offset = img.shape[0]
    
    print(f"📷 输入: {input_path}")
    print(f"📐 输出: {output_path}")
    print(f"📏 图片尺寸: {img.shape[1]} x {img.shape[0]}")
    
    # 锐化
    if sharpen:
        kernel_sharpen = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
        img_sharp = cv2.filter2D(img, -1, kernel_sharpen)
    else:
        img_sharp = img
    
    # 自适应阈值二值化
    binary = cv2.adaptiveThreshold(
        img_sharp, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
        cv2.THRESH_BINARY_INV, 11, 2
    )
    
    # 轮廓检测
    contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    filtered = [c for c in contours if cv2.contourArea(c) >= min_area]
    
    print(f"🔍 检测到 {len(contours)} 个轮廓，保留 {len(filtered)} 个")
    
    # 生成DXF
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    doc.layers.add("OUTLINES", color=7)
    
    # 原始轮廓，不简化
    for contour in filtered:
        points = [(float(pt[0][0]), float(y_offset - pt[0][1])) for pt in contour]
        if len(points) >= 2:
            if points[0] != points[-1]:
                points.append(points[0])
            msp.add_lwpolyline(points, dxfattribs={'layer': 'OUTLINES'}).close()
    
    doc.saveas(output_path)
    
    # 清理临时文件
    if temp_png and os.path.exists(temp_png):
        os.remove(temp_png)
    
    size_kb = os.path.getsize(output_path) / 1024
    print(f"\n🎉 转换完成!")
    print(f"   文件: {output_path}")
    print(f"   大小: {size_kb:.1f} KB")
    print(f"   轮廓: {len(filtered)} 个")
    
    return str(output_path)


def batch_convert(input_dir: str, **kwargs):
    """批量转换目录下的所有图片"""
    input_dir = Path(input_dir)
    image_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.tiff', '.tif', '.webp'}
    image_files = [f for f in input_dir.iterdir() if f.suffix.lower() in image_extensions]
    
    if not image_files:
        print(f"❌ 目录 {input_dir} 中没有找到图片文件")
        return
    
    print(f"📁 找到 {len(image_files)} 个图片文件\n")
    
    for img_file in image_files:
        try:
            convert_image_to_dxf(str(img_file), **kwargs)
            print()
        except Exception as e:
            print(f"❌ {img_file.name} 转换失败: {e}\n")


def main():
    parser = argparse.ArgumentParser(description='图片转DXF工具（原始轮廓版）')
    parser.add_argument('input', help='输入图片路径或目录')
    parser.add_argument('-o', '--output', help='输出DXF文件路径')
    parser.add_argument('--min-area', type=int, default=3,
                        help='最小轮廓面积（默认3）')
    parser.add_argument('--no-sharpen', action='store_true',
                        help='不进行锐化处理')
    
    args = parser.parse_args()
    
    input_path = Path(args.input)
    kwargs = dict(
        min_area=args.min_area,
        sharpen=not args.no_sharpen,
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
