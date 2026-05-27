#!/usr/bin/env python3
"""
OCR智能图片转DXF工具 - 使用Umi-OCR识别文字，分离图形和直线

用法:
  python img2dxf_ocr.py input.png
  python img2dxf_ocr.py input.tif -o output.dxf

依赖:
  - Umi-OCR 运行在 http://127.0.0.1:1224
  - opencv-python-headless
  - ezdxf
"""

import base64
import json
import urllib.request
import cv2
import numpy as np
import ezdxf
import argparse
from pathlib import Path


def umi_ocr(image_path, host="127.0.0.1", port=1224):
    """调用Umi-OCR API返回结构化数据"""
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("utf-8")
    
    payload = json.dumps({
        "base64": b64,
        "options": {
            "ocr.angle": False,
            "ocr.language": "models/config_chinese.txt",
            "ocr.maxSideLen": 4096,
            "tbpu.parser": "multi_line",
            "data.format": "dict",
        }
    }).encode("utf-8")
    
    req = urllib.request.Request(
        f"http://{host}:{port}/api/ocr",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    resp = urllib.request.urlopen(req, timeout=60)
    result = json.loads(resp.read().decode("utf-8"))
    
    if result.get("code") == 100:
        return result["data"]
    else:
        raise RuntimeError(f"OCR error: {result}")


def ocr_convert(input_path, output_path=None, min_line_length=80):
    """
    OCR智能转换：文字用TEXT实体，图形和直线分离
    """
    input_path = Path(input_path)
    
    # 读取图片
    img = cv2.imread(str(input_path), cv2.IMREAD_GRAYSCALE)
    if img is None:
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
    
    # 1. OCR识别
    print("正在调用Umi-OCR...")
    ocr_data = umi_ocr(input_path)
    print(f"识别到 {len(ocr_data)} 个文字块")
    
    # 创建文字区域掩码
    text_mask = np.zeros_like(img)
    for item in ocr_data:
        box = item.get("box", [])
        if len(box) == 4:
            pts = np.array(box, dtype=np.int32)
            cv2.fillPoly(text_mask, [pts], 255)
    
    # 膨胀文字区域
    kernel = np.ones((5, 5), np.uint8)
    text_mask = cv2.dilate(text_mask, kernel, iterations=2)
    
    # 2. 图像处理
    kernel_sharpen = np.array([[-1,-1,-1], [-1,9,-1], [-1,-1,-1]])
    img_sharp = cv2.filter2D(img, -1, kernel_sharpen)
    
    _, binary = cv2.threshold(img_sharp, 50, 255, cv2.THRESH_BINARY_INV)
    binary_no_text = cv2.bitwise_and(binary, cv2.bitwise_not(text_mask))
    
    # 3. Hough直线检测
    edges = cv2.Canny(img_sharp, 50, 150)
    edges_no_text = cv2.bitwise_and(edges, cv2.bitwise_not(text_mask))
    
    lines_raw = cv2.HoughLinesP(edges_no_text, 1, np.pi/180, threshold=50,
                                 minLineLength=30, maxLineGap=20)
    lines = lines_raw if lines_raw is not None else []
    
    long_lines = []
    for line in lines:
        x1, y1, x2, y2 = line[0]
        length = np.sqrt((x2-x1)**2 + (y2-y1)**2)
        if length > min_line_length:
            long_lines.append(line[0])
    
    # 4. 轮廓检测
    contours, _ = cv2.findContours(binary_no_text, cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE)
    drawing_contours = [c for c in contours if cv2.contourArea(c) >= 20]
    
    # 5. 生成DXF
    if output_path is None:
        output_path = input_path.with_suffix('.dxf')
    
    doc = ezdxf.new('R2010')
    msp = doc.modelspace()
    
    doc.layers.add("DRAWING", color=7)
    doc.layers.add("H_LINES", color=6)
    doc.layers.add("TEXT", color=3)
    
    # 直线
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
    
    # OCR文字
    text_count = 0
    for item in ocr_data:
        text = item.get("text", "").strip()
        box = item.get("box", [])
        
        if text and len(box) == 4:
            x_coords = [p[0] for p in box]
            y_coords = [p[1] for p in box]
            
            x_min = min(x_coords)
            y_min = min(y_coords)
            y_max = max(y_coords)
            
            text_height = y_max - y_min
            text_width = max(x_coords) - x_min
            
            if text_height > 5 and text_width > 10:
                dxf_height = max(text_height * 0.8, 2.0)
                x_pos = float(x_min)
                y_pos = float(y_offset - y_max)
                
                try:
                    msp.add_text(
                        text,
                        dxfattribs={
                            'layer': 'TEXT',
                            'height': dxf_height,
                            'insert': (x_pos, y_pos),
                        }
                    )
                    text_count += 1
                except:
                    pass
    
    doc.saveas(str(output_path))
    
    import os
    size = os.path.getsize(output_path) / 1024
    
    print(f"\nOCR智能DXF: {size:.0f}KB")
    print(f"  DRAWING: {len(drawing_contours)}个图形")
    print(f"  H_LINES: {len(long_lines)}条直线")
    print(f"  TEXT: {text_count}个文字实体")
    
    return str(output_path)


def main():
    parser = argparse.ArgumentParser(description='OCR智能图片转DXF工具')
    parser.add_argument('input', help='输入图片路径')
    parser.add_argument('-o', '--output', help='输出DXF路径')
    parser.add_argument('--min-line-length', type=int, default=80,
                        help='最小直线长度（默认80像素）')
    
    args = parser.parse_args()
    ocr_convert(args.input, args.output, args.min_line_length)


if __name__ == '__main__':
    main()
