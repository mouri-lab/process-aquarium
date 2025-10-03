#!/usr/bin/env python3
"""
Fork Bomb - 一つのプロセスが大量にforkするテストスクリプト
Process Aquariumでの大量プロセス生成テスト用

⚠️ 注意: このスクリプトは大量のプロセスを生成します。
システムリソースを大量に消費する可能性があるため、注意して使用してください。
"""

import os
import sys
import time
import signal
import argparse
from multiprocessing import Process
import psutil

class ForkBomb:
    def __init__(self, max_children=50, fork_interval=0.1, child_lifetime=30.0, use_recursion=False):
        """
        Fork Bomb初期化
        
        Args:
            max_children: 最大子プロセス数
            fork_interval: fork間隔（秒）
            child_lifetime: 子プロセスの生存時間（秒）
            use_recursion: 再帰的fork（各子プロセスが更に子を作る）
        """
        self.max_children = max_children
        self.fork_interval = fork_interval
        self.child_lifetime = child_lifetime
        self.use_recursion = use_recursion
        self.children = []
        self.running = True
        
        # シグナルハンドラ設定
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
    def _signal_handler(self, signum, frame):
        """シグナル受信時の処理"""
        print(f"\n🛑 シグナル {signum} を受信。子プロセスを終了中...")
        self.running = False
        self._cleanup_children()
        sys.exit(0)
        
    def _cleanup_children(self):
        """子プロセスのクリーンアップ"""
        print(f"🧹 {len(self.children)} 個の子プロセスをクリーンアップ中...")
        for child in self.children:
            try:
                if child.is_alive():
                    child.terminate()
                    child.join(timeout=2)
                    if child.is_alive():
                        child.kill()
            except Exception as e:
                print(f"⚠️ 子プロセス終了エラー: {e}")
        self.children.clear()
        
    def child_worker(self, child_id, generation=1):
        """子プロセスのワーカー関数"""
        try:
            print(f"👶 子プロセス開始: ID={child_id}, PID={os.getpid()}, 世代={generation}")
            
            # 再帰的forkの場合、さらに子プロセスを作成
            if self.use_recursion and generation < 3:  # 最大3世代まで
                grandchildren = []
                for i in range(min(3, self.max_children // generation)):  # 世代が深くなるほど子の数を減らす
                    try:
                        grandchild = Process(
                            target=self.child_worker, 
                            args=(f"{child_id}-{i}", generation + 1)
                        )
                        grandchild.start()
                        grandchildren.append(grandchild)
                        time.sleep(0.05)  # 短い間隔でfork
                    except Exception as e:
                        print(f"⚠️ 孫プロセス作成エラー: {e}")
                        break
                
                # 孫プロセスの管理
                time.sleep(self.child_lifetime / 2)
                for grandchild in grandchildren:
                    try:
                        if grandchild.is_alive():
                            grandchild.terminate()
                    except:
                        pass
            else:
                # CPU使用を軽く行う（観測可能にするため）
                start_time = time.time()
                cpu_work_time = min(2.0, self.child_lifetime * 0.1)  # 最大2秒のCPU作業
                
                while time.time() - start_time < cpu_work_time:
                    # 軽いCPU作業
                    sum(i * i for i in range(1000))
                    time.sleep(0.01)
                
                # 残り時間は待機
                remaining_time = self.child_lifetime - (time.time() - start_time)
                if remaining_time > 0:
                    time.sleep(remaining_time)
                    
        except Exception as e:
            print(f"⚠️ 子プロセスエラー (ID={child_id}): {e}")
        finally:
            print(f"💀 子プロセス終了: ID={child_id}, PID={os.getpid()}")
            
    def start_fork_bomb(self):
        """Fork Bomb開始"""
        print(f"💣 Fork Bomb開始!")
        print(f"📊 設定: 最大子プロセス数={self.max_children}, fork間隔={self.fork_interval}s")
        print(f"⏰ 子プロセス生存時間={self.child_lifetime}s, 再帰fork={'有効' if self.use_recursion else '無効'}")
        print(f"🎯 親プロセス PID: {os.getpid()}")
        
        child_counter = 0
        
        try:
            while self.running:
                # 死んだ子プロセスを除去
                self.children = [child for child in self.children if child.is_alive()]
                
                # 新しい子プロセスを作成
                while len(self.children) < self.max_children and self.running:
                    try:
                        child_id = f"child-{child_counter}"
                        child = Process(target=self.child_worker, args=(child_id,))
                        child.start()
                        self.children.append(child)
                        child_counter += 1
                        
                        print(f"🚀 新しい子プロセス作成: {child_id} (PID: {child.pid}) - 現在の子数: {len(self.children)}")
                        
                        time.sleep(self.fork_interval)
                        
                    except Exception as e:
                        print(f"⚠️ 子プロセス作成失敗: {e}")
                        time.sleep(1)
                        break
                
                # 親プロセスの状態表示
                if child_counter % 10 == 0:
                    try:
                        parent_proc = psutil.Process(os.getpid())
                        print(f"📈 親プロセス状態: CPU={parent_proc.cpu_percent():.1f}%, "
                              f"メモリ={parent_proc.memory_info().rss/1024/1024:.1f}MB, "
                              f"アクティブ子数={len(self.children)}")
                    except:
                        pass
                
                time.sleep(0.5)  # メインループの休憩
                
        except KeyboardInterrupt:
            print("\n🛑 Ctrl+C検出。終了処理開始...")
        finally:
            self._cleanup_children()
            print("✅ Fork Bomb終了")

def main():
    parser = argparse.ArgumentParser(description='Fork Bomb - 大量プロセス生成テスト')
    parser.add_argument('--max-children', type=int, default=30, 
                       help='最大子プロセス数 (デフォルト: 30)')
    parser.add_argument('--fork-interval', type=float, default=0.2,
                       help='fork間隔（秒） (デフォルト: 0.2)')
    parser.add_argument('--child-lifetime', type=float, default=20.0,
                       help='子プロセス生存時間（秒） (デフォルト: 20.0)')
    parser.add_argument('--recursive', action='store_true',
                       help='再帰的fork（各子がさらに子を作る）を有効化')
    parser.add_argument('--duration', type=float, default=0,
                       help='実行時間（秒）。0なら無限実行 (デフォルト: 0)')
    
    args = parser.parse_args()
    
    # 安全性チェック
    if args.max_children > 100:
        print("⚠️ 警告: 100を超える子プロセス数は危険です。本当に実行しますか？ (y/N)")
        response = input().strip().lower()
        if response != 'y':
            print("実行をキャンセルしました。")
            return
    
    bomb = ForkBomb(
        max_children=args.max_children,
        fork_interval=args.fork_interval,
        child_lifetime=args.child_lifetime,
        use_recursion=args.recursive
    )
    
    if args.duration > 0:
        print(f"⏰ {args.duration}秒間実行後に自動終了します")
        
        def timeout_handler(signum, frame):
            print(f"\n⏰ 実行時間終了（{args.duration}秒）")
            bomb.running = False
            
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(int(args.duration))
    
    bomb.start_fork_bomb()

if __name__ == "__main__":
    main()