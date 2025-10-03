#!/usr/bin/env python3
"""
怪しいプロセス動作シミュレーター
Process Aquariumでの表示テスト用

このスクリプトは以下の怪しい動作をシミュレートします：
1. フォーク爆弾（制御された）
2. 大量プロセス生成
3. ネットワーク通信
4. プロセス名変更
5. 短時間で大量のプロセス生成・消去
"""

import os
import sys
import time
import socket
import threading
import subprocess
import signal
import random
import argparse
from multiprocessing import Process, Queue
from concurrent.futures import ThreadPoolExecutor

class SuspiciousProcessSimulator:
    def __init__(self):
        self.processes = []
        self.threads = []
        self.running = True
        self.long_lived_mode = False
        
    def signal_handler(self, signum, frame):
        """Ctrl+Cでの終了処理"""
        print("\n🛑 シミュレーターを停止中...")
        self.running = False
        self.cleanup()
        sys.exit(0)
        
    def cleanup(self):
        """プロセスとスレッドのクリーンアップ"""
        print("🧹 クリーンアップ中...")
        
        # プロセス終了
        for p in self.processes:
            try:
                if p.is_alive():
                    p.terminate()
                    p.join(timeout=1)
                    if p.is_alive():
                        p.kill()
            except:
                pass
                
        # スレッド終了待機
        for t in self.threads:
            try:
                if t.is_alive():
                    t.join(timeout=1)
            except:
                pass
                
        print("✅ クリーンアップ完了")

    def fork_bomb_controlled(self, max_depth=3, delay=0.5):
        """制御されたフォーク爆弾（最大深度制限付き）"""
        print(f"💣 フォーク爆弾開始 (最大深度: {max_depth})")
        
        def fork_worker(depth, worker_id):
            if depth >= max_depth or not self.running:
                return
                
            try:
                # プロセス名を変更
                if hasattr(os, 'prctl'):
                    import prctl
                    prctl.set_name(f"fork_bomb_{depth}_{worker_id}")
                
                print(f"  🔥 フォーク深度 {depth}, Worker {worker_id}, PID: {os.getpid()}")
                
                # 子プロセス生成
                if depth < max_depth - 1:
                    for i in range(2):  # 2つの子プロセスを生成
                        if not self.running:
                            break
                        p = Process(target=fork_worker, args=(depth + 1, i))
                        p.start()
                        self.processes.append(p)
                        time.sleep(delay)
                        
                # しばらく生存
                time.sleep(random.uniform(2, 5))
                
            except Exception as e:
                print(f"  ❌ フォークエラー: {e}")
                
        # 初期プロセス開始
        initial_process = Process(target=fork_worker, args=(0, 0))
        initial_process.start()
        self.processes.append(initial_process)

    def mass_process_generator(self, count=20, interval=0.2):
        """大量プロセス生成器"""
        print(f"🏭 大量プロセス生成開始 (数: {count})")
        
        def worker(worker_id):
            try:
                # プロセス名を設定
                if hasattr(os, 'prctl'):
                    import prctl
                    prctl.set_name(f"mass_proc_{worker_id}")
                
                # long_livedモードに応じて生存時間を調整
                if hasattr(self, 'long_lived_mode') and self.long_lived_mode:
                    sleep_time = random.uniform(60, 180)  # 1-3分
                    calc_range = 50000
                    io_size = 50000
                else:
                    sleep_time = random.uniform(10, 30)  # 10-30秒
                    calc_range = 10000
                    io_size = 10000
                
                operations = [
                    lambda: time.sleep(sleep_time),
                    lambda: [i**2 for i in range(calc_range)],  # CPU集約的処理
                    lambda: open('/dev/null', 'w').write('test' * io_size),  # I/O処理
                ]
                
                operation = random.choice(operations)
                operation()
                
                print(f"  🔧 大量プロセス Worker {worker_id} 完了, PID: {os.getpid()}")
                
            except Exception as e:
                print(f"  ❌ 大量プロセスエラー: {e}")
        
        # プロセスを段階的に生成
        for i in range(count):
            if not self.running:
                break
            p = Process(target=worker, args=(i,))
            p.start()
            self.processes.append(p)
            time.sleep(interval)

    def network_communicator(self, duration=10):
        """ネットワーク通信シミュレーター"""
        print(f"🌐 ネットワーク通信開始 (時間: {duration}秒)")
        
        def tcp_client():
            """TCP接続試行"""
            targets = [
                ('google.com', 80),
                ('github.com', 443),
                ('localhost', 8080),
                ('127.0.0.1', 22),
            ]
            
            while self.running:
                try:
                    target = random.choice(targets)
                    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                    sock.settimeout(2)
                    result = sock.connect_ex(target)
                    sock.close()
                    print(f"  🔌 TCP接続試行: {target[0]}:{target[1]} -> {result}")
                    time.sleep(random.uniform(0.5, 2))
                except Exception as e:
                    print(f"  ❌ TCP接続エラー: {e}")
                    time.sleep(1)
        
        def udp_sender():
            """UDP送信"""
            while self.running:
                try:
                    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    data = f"suspicious_data_{random.randint(1000, 9999)}"
                    sock.sendto(data.encode(), ('127.0.0.1', 12345))
                    sock.close()
                    print(f"  📡 UDP送信: {data}")
                    time.sleep(random.uniform(1, 3))
                except Exception as e:
                    print(f"  ❌ UDP送信エラー: {e}")
                    time.sleep(1)
        
        # ネットワークスレッド開始
        tcp_thread = threading.Thread(target=tcp_client)
        udp_thread = threading.Thread(target=udp_sender)
        
        tcp_thread.start()
        udp_thread.start()
        
        self.threads.extend([tcp_thread, udp_thread])
        
        # 指定時間後に停止
        time.sleep(duration)

    def process_name_changer(self, count=5):
        """プロセス名変更器"""
        print(f"🎭 プロセス名変更開始 (数: {count})")
        
        def name_changer(worker_id):
            try:
                suspicious_names = [
                    'definitely_not_malware',
                    'system_update',
                    'legitimate_process',
                    'chrome_helper',
                    'kernel_worker',
                    'network_manager',
                    'security_scanner',
                ]
                
                for name in suspicious_names:
                    if not self.running:
                        break
                        
                    if hasattr(os, 'prctl'):
                        import prctl
                        prctl.set_name(f"{name}_{worker_id}")
                    
                    print(f"  🎪 プロセス名変更: {name}_{worker_id}, PID: {os.getpid()}")
                    time.sleep(random.uniform(15, 25))  # 15-25秒に延長
                    
            except Exception as e:
                print(f"  ❌ プロセス名変更エラー: {e}")
        
        for i in range(count):
            if not self.running:
                break
            p = Process(target=name_changer, args=(i,))
            p.start()
            self.processes.append(p)
            time.sleep(0.5)

    def rapid_spawn_killer(self, cycles=5, spawn_count=10):
        """高速プロセス生成・削除"""
        print(f"⚡ 高速生成削除開始 (サイクル: {cycles}, 各サイクル: {spawn_count}プロセス)")
        
        for cycle in range(cycles):
            if not self.running:
                break
                
            print(f"  🔄 サイクル {cycle + 1}/{cycles}")
            temp_processes = []
            
            # 高速生成
            for i in range(spawn_count):
                def quick_worker(cycle_id, worker_id):
                    if hasattr(os, 'prctl'):
                        import prctl
                        prctl.set_name(f"rapid_{cycle_id}_{worker_id}")
                    time.sleep(random.uniform(0.5, 2))
                
                p = Process(target=quick_worker, args=(cycle, i))
                p.start()
                temp_processes.append(p)
                time.sleep(0.1)  # 高速生成
            
            # 少し待つ
            time.sleep(2)
            
            # 高速削除
            for p in temp_processes:
                if p.is_alive():
                    p.terminate()
            
            # プロセス終了待機
            for p in temp_processes:
                p.join(timeout=1)
                if p.is_alive():
                    p.kill()
            
            print(f"  ✅ サイクル {cycle + 1} 完了: {spawn_count}プロセス生成・削除")
            time.sleep(1)

    def cpu_intensive_workers(self, count=3, duration=10):
        """CPU集約的ワーカー"""
        print(f"💻 CPU集約的処理開始 (ワーカー数: {count}, 時間: {duration}秒)")
        
        def cpu_worker(worker_id):
            try:
                if hasattr(os, 'prctl'):
                    import prctl
                    prctl.set_name(f"cpu_intensive_{worker_id}")
                
                start_time = time.time()
                counter = 0
                
                while self.running and (time.time() - start_time) < duration:
                    # CPU集約的な計算（計算量を大幅に増加）
                    for i in range(100000):  # 10倍に増加
                        counter += i ** 2
                    
                    # 少し休憩して他のプロセスにCPU時間を譲る
                    time.sleep(0.1)
                    
                    if counter % 10000000 == 0:  # 出力頻度を調整
                        print(f"  🔥 CPU Worker {worker_id}: {counter} 計算完了")
                    
                print(f"  ✅ CPU Worker {worker_id} 完了, PID: {os.getpid()}")
                
            except Exception as e:
                print(f"  ❌ CPU Worker エラー: {e}")
        
        for i in range(count):
            if not self.running:
                break
            p = Process(target=cpu_worker, args=(i,))
            p.start()
            self.processes.append(p)

    def run_simulation(self, mode='all', process_count=50, duration=30, long_lived=False):
        """シミュレーション実行"""
        signal.signal(signal.SIGINT, self.signal_handler)
        
        # long_livedモードの場合、各プロセスの生存時間を大幅に延長
        if long_lived:
            self.long_lived_mode = True
            print("🚀 怪しいプロセス動作シミュレーター開始（長時間生存モード）")
            print(f"   プロセス数: {process_count}, 実行時間: {duration}秒")
            print("   各プロセスは数分間動作します")
        else:
            self.long_lived_mode = False
            print("🚀 怪しいプロセス動作シミュレーター開始")
            print(f"   プロセス数: {process_count}, 実行時間: {duration}秒")
        print("   Ctrl+C で停止")
        print("=" * 50)
        
        try:
            if mode == 'all' or mode == 'fork':
                # フォーク爆弾は数を制限（システム安全のため）
                fork_depth = min(4, max(2, int(process_count / 15)))
                self.fork_bomb_controlled(max_depth=fork_depth, delay=0.3)
                time.sleep(2)
            
            if mode == 'all' or mode == 'mass':
                count = process_count if mode == 'mass' else min(process_count // 3, 20)
                self.mass_process_generator(count=count, interval=0.1)
                time.sleep(3)
            
            if mode == 'all' or mode == 'network':
                net_duration = duration if mode == 'network' else min(duration // 3, 10)
                self.network_communicator(duration=net_duration)
                time.sleep(2)
            
            if mode == 'all' or mode == 'names':
                name_count = process_count if mode == 'names' else min(process_count // 7, 10)
                self.process_name_changer(count=name_count)
                time.sleep(3)
            
            if mode == 'all' or mode == 'rapid':
                cycles = max(2, duration // 10)
                spawn_count = min(process_count // 5, 15)
                self.rapid_spawn_killer(cycles=cycles, spawn_count=spawn_count)
                time.sleep(2)
            
            if mode == 'all' or mode == 'cpu':
                cpu_count = min(process_count // 10, 8)  # CPU集約的なので数を制限
                cpu_duration = duration if mode == 'cpu' else min(duration // 3, 10)
                self.cpu_intensive_workers(count=cpu_count, duration=cpu_duration)
                time.sleep(5)
            
            # 全体完了まで待機
            print("⏳ シミュレーション実行中... (Ctrl+C で停止)")
            start_time = time.time()
            while self.running and any(p.is_alive() for p in self.processes):
                if time.time() - start_time > duration:
                    print(f"⏰ 指定時間 ({duration}秒) が経過しました")
                    break
                time.sleep(1)
            
            print("🎉 シミュレーション完了!")
            
        except KeyboardInterrupt:
            print("\n🛑 ユーザーによる停止")
        finally:
            self.cleanup()


def main():
    parser = argparse.ArgumentParser(
        description='怪しいプロセス動作シミュレーター',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
実行例:
  python3 suspicious_process_simulator.py --mode all --count 100 --duration 60
  python3 suspicious_process_simulator.py --mode mass --count 50
  python3 suspicious_process_simulator.py --mode fork --duration 30
  python3 suspicious_process_simulator.py --mode network --duration 45
  python3 suspicious_process_simulator.py --mode names --count 20
        """
    )
    
    parser.add_argument(
        '--mode', 
        choices=['all', 'fork', 'mass', 'network', 'names', 'rapid', 'cpu'],
        default='all',
        help='実行する動作モード (デフォルト: all)'
    )
    
    parser.add_argument(
        '--count',
        type=int,
        default=50,
        help='生成するプロセス数 (デフォルト: 50)'
    )
    
    parser.add_argument(
        '--duration',
        type=int,
        default=30,
        help='実行時間（秒） (デフォルト: 30)'
    )
    
    parser.add_argument(
        '--long-lived',
        action='store_true',
        help='プロセスを長時間生存させる（各プロセスが数分間動作）'
    )
    
    args = parser.parse_args()
    
    simulator = SuspiciousProcessSimulator()
    simulator.run_simulation(mode=args.mode, process_count=args.count, duration=args.duration, long_lived=args.long_lived)


if __name__ == '__main__':
    main()