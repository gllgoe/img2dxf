# img2dxf

图片转DXF工具，支持扫描/拍照图片转换为AutoCAD格式。

## 功能特点

- 支持 JPG/PNG/BMP/TIFF/WebP 格式
- 使用 OpenCV 进行图像预处理和轮廓检测
- 使用 vtracer 进行矢量化
- 使用 ezdxf 生成DXF文件
- 保留原始轮廓精度

## 安装

```bash
# 创建虚拟环境
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
pip install -r requirements.txt
```

## 使用方法

```bash
# 基本转换
python img2dxf.py input.jpg

# 指定输出
python img2dxf.py input.jpg -o output.dxf

# 批量转换
python img2dxf.py ./images/
```

## 参数说明

- `--mode`: 矢量化模式 (polygon/spline)
- `--colormode`: 颜色模式 (color/binary)
- `--scale`: 缩放比例
- `--filter-speckle`: 过滤噪点大小
- `--length-threshold`: 路径长度阈值

## 依赖

- Python 3.8+
- vtracer
- ezdxf
- Pillow
- opencv-python-headless
