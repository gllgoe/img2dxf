#!/usr/bin/env python3
"""
智能图片转DXF工具 - 识别文字、直线、标注、图形

用法:
  python img2dxf_smart.py input.png
  python img2dxf_smart.py input.tif -o output.dxf
"""

import cv2
import numpy as np
import ezdxf
import argparse
from pathlib import Path


def smart_convert(input_path, output_path=None, min_line_length=100):
    """
    智能转换：分离文字、直线、标注、图形
    """
    input_path = Path(input_path)
    
    # 读取图片
    img = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
        # 尝试用PIL读取TIF
        from PIL import Image
        img_pil = Image.open(input_path)
        if img_pil.mode != 'L':
            img_pil = img_pil.convert('L')
        temp_png = str(input_path) + ".temp.png"
        img_pil.save(temp_png)
        img = cv2.imread(temp_png, cv2.IMREAD_GRAYSCALE)
        import os
        os.remove(temp_png)
    
    y_offset = img.shape[0]
    
    # 锐化
    kernel_sharpen = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    img_sharp = cv2.filter2D(img, -1, kernel_sharpen)
    
    # 二值化
    _, binary = cv2.threshold(img_sharp, 50, 255, cv2.THRESH_BINARY_INV)
    
    # ============================================================
    # 1. Hough直线检测
    # ============================================================
    edges = cv2.Canny(img_sharp, 50, 150)
    lines_raw = cv2.HoughLinesP(edges, 1, np.pi/180, threshold=50, 
                                 minLineLength=30, maxLineGap=20)
    lines = lines_raw if lines_raw is not None else []
    
    # 过滤长直线
    long_lines = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = np.sqrt((x2-x1)**2 + (y2-y1)**2)
        if length > min_line_length:
            long_lines.append(line[0])
    
    # ============================================================
    # 2. 轮廓检测和分类
    # ============================================================
    contours, _ = cv2.findContours(binary, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    
    text_contours = []
    dimension_contours = []
    drawing_contours = []
    
    for contour in contours:
        area = cv2.contourArea(contour)
        if area < 10:
            continue
        
        x, y, w, h = cv2.boundingRect(contour)
        aspect_ratio = max(w, h) / min(w, h) if min(w, h) > 0 else 0
        bbox_area = w * h
        density = area / bbox_area if bbox_area > 0 else 0
        
        hull = cv2.convexHull(contour)
        hull_area = cv2.contourArea(hull)
        solidity = area / hull_area if hull_area > 0 else 0
        
        perimeter = cv2.arcLength(contour, True)
        circularity = 4 * np.pi * area / (perimeter * perimeter) if perimeter > 0 else 0
        
        # 文字：小面积、高密度、接近矩形
        if (area < 800 and density > 0.3 and solidity > 0.4 
            and aspect_ratio < 8 and circularity < 0.5):
            text_contours.append(contour)
        # 标注：极长条形
        elif (aspect_ratio > 15 and area < 2000) or (aspect_ratio > 8 and area < 500):
            dimension_contours.append(contour)
        else:
            drawing_contours.append(contour)
    
    # ============================================================
    # 3. 生成DXF
    # ============================================================
    if output_path is None:
        output_path = input_path.with_suffix('.dxf')
    
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    doc.layers.add("DRAWING", color=7)       # 白色 - 图形
    doc.layers.add("H_LINES", color=6)       # 品红 - 精确直线
    doc.layers.add("DIMENSIONS", color=2)    # 黄色 - 标注
    doc.layers.add("TEXT_AREA", color=1)     # 红色 - 文字区域
    
    # Hough长直线
    for x1, y1, x2, y2 in long_lines:
        msp.add_line(
            (float(x1), float(y_offset - y1)),
            (float(x2), float(y_offset - y2)),
            dxfattribs={'layer': 'H_LINES'}
        )
    
    # 图形轮廓
    for contour in drawing_contours:
        epsilon = 0.001 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        points = [(float(pt[0][0]), float(y_offset - pt[0][1])) for pt in approx]
        if len(points) >= 2:
            if points[0] != points[-1]:
                points.append(points[0])
            msp.add_lwpolyline(points, dxfattribs={'layer': 'DRAWING'}).close()
    
    # 标注轮廓
    for contour in dimension_contours:
        epsilon = 0.0005 * cv2.arcLength(contour, True)
        approx = cv2.approxPolyDP(contour, epsilon, True)
        points = [(float(pt[0][0]), float(y_offset - pt[0][1])) for pt in approx]
        if len(points) >= 2:
            if points[0] != points[-1]:
                points.append(points[0])
            msp.add_lwpolyline(points, dxfattribs={'layer': 'DIMENSIONS'}).close()
    
    # 文字轮廓
    for contour in text_contours:
        points = [(float(pt[0][0]), float(y_offset - pt[0][1])) for pt in contour]
        if len(points) >= 2:
            if points[0] != points[-1]:
                points.append(points[0])
            msp.add_lwpolyline(points, dxfattribs={'layer': 'TEXT_AREA'}).close()
    
    doc.saveas(str(output_path))
    
    import os
    size = os.path.getsize(output_path) / 1024
    
    print(f'智能DXF: {size:.0f}KB')
    print(f'  DRAWING: {len(drawing_contours)}个图形')
    print(f'  H_LINES: {len(long_lines)}条直线')
    print(f'  DIMENSIONS: {len(dimension_contours)}条标注')
    print(f'  TEXT_AREA: {len(text_contours)}个文字')
    
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description='智能图片转DXF工具')
    parser.add_argument('input', help='输入图片路径')
    parser.add_argument('-o', '--output', help='输出DXF路径')
    parser.add_argument('--min-line-length', type=int, default=100,
                        help='最小直线长度（默认100像素）')
    
    args = parser.parse_args()
    smart_convert(args.input, args.output, args.min_line_length)


if __name__ == '__main__':
    main()
