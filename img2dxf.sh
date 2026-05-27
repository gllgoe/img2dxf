#!/bin/bash
# 图片转 DXF 快捷脚本
# 用法: img2dxf input.jpg [output.dxf]

VENV="$HOME/img2dxf-env"
SCRIPT="$HOME/tools/img2dxf/img2dxf.py"

source "$VENV/bin/activate" 2>/dev/null
python3 "$SCRIPT" "$@"
