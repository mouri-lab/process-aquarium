#!/usr/bin/env python3
"""
Digital Life Aquarium - コマンドライン設定版
パフォーマンス最適化のオプション付き

使用方法:
    python main.py                    # 標準設定（100プロセス）
    python main.py --light            # 軽量設定（50プロセス）
    python main.py --ultra-light      # 超軽量設定（25プロセス）
    python main.py --full             # 全プロセス表示（重い）
    python main.py --fps 20           # FPS指定
    python main.py --max-processes 80 # 最大プロセス数指定
"""

import sys
import os
import argparse

# プロジェクトルートディレクトリをパスに追加
project_root = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, project_root)

from src.visuals.aquarium import Aquarium

def parse_arguments():
    """コマンドライン引数の解析"""
    parser = argparse.ArgumentParser(description='Digital Life Aquarium - デジタル生命の水族館')
    
    # 事前定義設定
    parser.add_argument('--light', action='store_true', 
                       help='軽量設定（50プロセス、FPS20）')
    parser.add_argument('--ultra-light', action='store_true', 
                       help='超軽量設定（25プロセス、FPS15）')
    parser.add_argument('--full', action='store_true', 
                       help='全プロセス表示（重い、500+プロセス）')
    
    # 個別設定
    parser.add_argument('--max-processes', type=int, default=100,
                       help='表示する最大プロセス数（デフォルト: 100）')
    parser.add_argument('--fps', type=int, default=30,
                       help='フレームレート（デフォルト: 30）')
    parser.add_argument('--width', type=int, default=1200,
                       help='ウィンドウ幅（デフォルト: 1200）')
    parser.add_argument('--height', type=int, default=800,
                       help='ウィンドウ高さ（デフォルト: 800）')
    
    return parser.parse_args()

def main():
    """メイン関数"""
    args = parse_arguments()
    
    # 事前定義設定の適用
    if args.ultra_light:
        max_processes = 25
        fps = 15
        print("🌊 超軽量設定: 25プロセス、15FPS")
    elif args.light:
        max_processes = 50
        fps = 20
        print("🐟 軽量設定: 50プロセス、20FPS")
    elif args.full:
        max_processes = 1000  # 実質無制限
        fps = args.fps
        print("🐋 全プロセス表示: 重い設定です！")
    else:
        max_processes = args.max_processes
        fps = args.fps
        print(f"⚙️  カスタム設定: {max_processes}プロセス、{fps}FPS")
    
    try:
        # Aquariumを作成して実行
        print("🎭 Digital Life Aquarium を起動中...")
        
        # ProcessManager用の設定をAquariumに渡すためのアプローチが必要
        # 今回は環境変数を使用
        os.environ['AQUARIUM_MAX_PROCESSES'] = str(max_processes)
        os.environ['AQUARIUM_FPS'] = str(fps)
        
        aquarium = Aquarium(width=args.width, height=args.height)
        aquarium.run()
        
    except KeyboardInterrupt:
        print("\n🌙 水族館を手動で閉館しました。")
    except Exception as e:
        print(f"❌ エラーが発生しました: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
