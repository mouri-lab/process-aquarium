#!/usr/bin/env python3
"""
Digital Life Aquarium - メイン実行ファイル
デジタル生命の水族館を起動します

使用方法:
    python main.py
    
あるいは直接実行:
    chmod +x main.py
    ./main.py
"""

import sys
import os

# プロジェクトルートディレクトリをパスに追加
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.visuals.aquarium import main

if __name__ == "__main__":
    main()
