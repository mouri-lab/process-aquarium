"""
Digital Life Aquarium - プロセス管理モジュール

OSのプロセス情報をリアルタイムで取得・管理するクラス群
"""

import psutil
import time
import random
from typing import Dict, List, Optional, Set
from dataclasses import dataclass
from datetime import datetime
import random


@dataclass
class ProcessInfo:
    """プロセス情報を格納するデータクラス"""
    pid: int
    ppid: int
    name: str
    exe: str
    memory_percent: float
    cpu_percent: float
    num_threads: int
    create_time: float
    status: str
    cmdline: List[str]

    # 生命体としての属性
    birth_time: datetime
    last_update: datetime
    is_new: bool = False
    is_dying: bool = False


class ProcessManager:
    """プロセス情報を管理するメインクラス"""

    def __init__(self, max_processes: int = 100):
        self.processes: Dict[int, ProcessInfo] = {}
        self.previous_pids: Set[int] = set()
        self.previous_process_exes: Dict[int, str] = {}  # exec検出用
        self.update_interval = 1.0  # 更新間隔を1秒に延長
        self.last_update = time.time()
        self.max_processes = max_processes  # 表示する最大プロセス数
        
        # プロセス関係追跡
        self.process_families: Dict[int, List[int]] = {}  # 親→子リスト
        self.recent_forks: List[tuple] = []  # 最近のfork履歴
        self.recent_execs: List[int] = []    # 最近のexec履歴
        
        # 重要なプロセス名のフィルタ（優先表示）
        self.important_processes = {
            'python', 'chrome', 'firefox', 'safari', 'code', 'terminal',
            'finder', 'dock', 'systemuiserver', 'windowserver', 'kernel_task',
            'launchd', 'zoom', 'slack', 'discord', 'spotify', 'photoshop',
            'illustrator', 'aftereffects', 'node', 'java', 'docker'
        }
        
        # 除外するプロセス（システムの細かなデーモン等）
        self.excluded_processes = {
            'com.apple.', 'cfprefsd', 'distnoted', 'trustd', 'secd',
            'bluetoothd', 'audiomxd', 'logd_helper', 'deleted'
        }

    def get_all_processes(self) -> Dict[int, ProcessInfo]:
        """全プロセス情報を取得"""
        return self.processes.copy()

    def get_process(self, pid: int) -> Optional[ProcessInfo]:
        """指定されたPIDのプロセス情報を取得"""
        return self.processes.get(pid)

    def update(self) -> None:
        """プロセス情報を更新"""
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return

        current_pids = set()
        new_processes = {}
        current_process_exes = {}

        # 現在のプロセス一覧を取得
        for proc in psutil.process_iter(['pid', 'ppid', 'name', 'exe', 'memory_percent',
                                       'cpu_percent', 'num_threads', 'create_time',
                                       'status', 'cmdline']):
            try:
                info = proc.info
                pid = info['pid']
                name = info['name'] or 'unknown'
                exe = info['exe'] or ''
                memory_percent = info['memory_percent'] or 0.0
                cpu_percent = info['cpu_percent'] or 0.0
                
                # プロセスフィルタリング
                if not self._should_include_process(name, memory_percent, cpu_percent):
                    continue
                
                current_pids.add(pid)
                current_process_exes[pid] = exe

                # 新しいプロセスかどうかをチェック
                is_new = pid not in self.previous_pids

                # プロセス情報を作成
                process_info = ProcessInfo(
                    pid=pid,
                    ppid=info['ppid'] or 0,
                    name=name,
                    exe=exe,
                    memory_percent=memory_percent,
                    cpu_percent=cpu_percent,
                    num_threads=info['num_threads'] or 1,
                    create_time=info['create_time'] or 0.0,
                    status=info['status'] or 'unknown',
                    cmdline=info['cmdline'] or [],
                    birth_time=datetime.now() if is_new else (
                        self.processes[pid].birth_time if pid in self.processes
                        else datetime.now()
                    ),
                    last_update=datetime.now(),
                    is_new=is_new
                )

                new_processes[pid] = process_info

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                # プロセスがアクセス不可または既に終了している場合はスキップ
                continue

        # exec検出
        self._detect_exec_events(current_process_exes)
        
        # 家族関係の更新
        self._update_process_families(new_processes)

        # 消滅したプロセスをマーク
        for pid in self.previous_pids:
            if pid not in current_pids and pid in self.processes:
                self.processes[pid].is_dying = True

        # プロセス情報を更新
        self.processes = new_processes
        self.previous_pids = current_pids
        self.previous_process_exes = current_process_exes
        self.last_update = current_time

    def _should_include_process(self, process_name: str, memory_percent: float, cpu_percent: float) -> bool:
        """プロセスを表示対象に含めるかどうかを判定"""
        # Noneチェック
        if memory_percent is None:
            memory_percent = 0.0
        if cpu_percent is None:
            cpu_percent = 0.0
        if process_name is None:
            process_name = "unknown"
        
        # 除外リストのチェック
        for excluded in self.excluded_processes:
            if excluded in process_name.lower():
                return False
        
        # 重要なプロセスは常に含める
        for important in self.important_processes:
            if important in process_name.lower():
                return True
        
        # リソース使用量が一定以上のプロセスは含める
        if memory_percent > 0.5 or cpu_percent > 1.0:
            return True
        
        # その他のプロセスは確率的に選択（負荷軽減）
        return random.random() < 0.3

    def get_new_processes(self) -> List[ProcessInfo]:
        """新しく生成されたプロセスのリストを取得"""
        return [proc for proc in self.processes.values() if proc.is_new]

    def get_dying_processes(self) -> List[ProcessInfo]:
        """消滅するプロセスのリストを取得"""
        return [proc for proc in self.processes.values() if proc.is_dying]

    def get_process_statistics(self) -> Dict[str, any]:
        """プロセス統計情報を取得"""
        total_processes = len(self.processes)
        total_memory = sum(proc.memory_percent for proc in self.processes.values())
        avg_cpu = sum(proc.cpu_percent for proc in self.processes.values()) / total_processes if total_processes > 0 else 0
        total_threads = sum(proc.num_threads for proc in self.processes.values())

        return {
            'total_processes': total_processes,
            'total_memory_percent': total_memory,
            'average_cpu_percent': avg_cpu,
            'total_threads': total_threads,
            'new_processes': len(self.get_new_processes()),
            'dying_processes': len(self.get_dying_processes())
        }

    def detect_fork(self) -> List[tuple]:
        """fork操作を検知（親子関係の新規作成）"""
        forks = []
        for proc in self.get_new_processes():
            if proc.ppid in self.processes:
                parent = self.processes[proc.ppid]
                forks.append((parent, proc))
        
        # 最近のfork履歴を更新
        self.recent_forks.extend(forks)
        # 履歴は最大10個まで保持
        self.recent_forks = self.recent_forks[-10:]
        
        return forks

    def detect_exec(self) -> List[ProcessInfo]:
        """exec操作を検知（実行ファイルパスの変更）"""
        # recent_execsから該当するプロセス情報を取得
        execs = []
        for pid in self.recent_execs:
            if pid in self.processes:
                execs.append(self.processes[pid])
        
        # 履歴をクリア（一度検出したらクリア）
        self.recent_execs.clear()
        
        return execs
    
    def _detect_exec_events(self, current_process_exes: Dict[int, str]):
        """exec操作を検知する内部メソッド"""
        for pid, current_exe in current_process_exes.items():
            if pid in self.previous_process_exes:
                previous_exe = self.previous_process_exes[pid]
                # 実行ファイルパスが変更された場合はexecとみなす
                if previous_exe and current_exe and previous_exe != current_exe:
                    self.recent_execs.append(pid)
    
    def _update_process_families(self, new_processes: Dict[int, ProcessInfo]):
        """プロセスファミリー（親子関係）を更新"""
        self.process_families.clear()
        for proc in new_processes.values():
            if proc.ppid > 0:  # 親プロセスが存在する場合
                if proc.ppid not in self.process_families:
                    self.process_families[proc.ppid] = []
                self.process_families[proc.ppid].append(proc.pid)
    
    def get_process_children(self, pid: int) -> List[ProcessInfo]:
        """指定されたプロセスの子プロセス一覧を取得"""
        if pid not in self.process_families:
            return []
        
        children = []
        for child_pid in self.process_families[pid]:
            if child_pid in self.processes:
                children.append(self.processes[child_pid])
        return children
    
    def get_related_processes(self, pid: int, max_distance: int = 2) -> List[ProcessInfo]:
        """指定されたプロセスに関連するプロセス群を取得（群れ行動用）"""
        related = []
        visited = set()
        
        def collect_related(current_pid: int, distance: int):
            if distance > max_distance or current_pid in visited:
                return
            
            visited.add(current_pid)
            if current_pid in self.processes:
                related.append(self.processes[current_pid])
            
            # 子プロセスを追加
            for child_pid in self.process_families.get(current_pid, []):
                collect_related(child_pid, distance + 1)
            
            # 兄弟プロセスを追加
            if current_pid in self.processes:
                parent_pid = self.processes[current_pid].ppid
                for sibling_pid in self.process_families.get(parent_pid, []):
                    if sibling_pid != current_pid:
                        collect_related(sibling_pid, distance + 1)
        
        collect_related(pid, 0)
        return related
    
    def detect_ipc_connections(self) -> List[tuple]:
        """プロセス間通信の可能性を検出（簡単な実装）"""
        connections = []
        
        # 同じ実行ファイル名を持つプロセス群を検出
        exe_groups = {}
        for proc in self.processes.values():
            if proc.exe:
                exe_name = proc.exe.split('/')[-1]  # ファイル名のみ取得
                if exe_name not in exe_groups:
                    exe_groups[exe_name] = []
                exe_groups[exe_name].append(proc)
        
        # 複数のプロセスを持つ実行ファイルは通信の可能性あり
        for exe_name, procs in exe_groups.items():
            if len(procs) > 1:
                # 全ての組み合わせを接続とみなす
                for i in range(len(procs)):
                    for j in range(i + 1, len(procs)):
                        connections.append((procs[i], procs[j]))
        
        return connections


def test_process_manager():
    """ProcessManagerのテスト関数"""
    manager = ProcessManager()

    print("=== Digital Life Aquarium - Process Monitor Test ===")
    print("プロセス情報を10秒間監視します...")

    for i in range(20):  # 10秒間（0.5秒間隔）
        manager.update()
        stats = manager.get_process_statistics()

        print(f"\n--- Update {i+1} ---")
        print(f"総プロセス数: {stats['total_processes']}")
        print(f"総メモリ使用率: {stats['total_memory_percent']:.2f}%")
        print(f"平均CPU使用率: {stats['average_cpu_percent']:.2f}%")
        print(f"総スレッド数: {stats['total_threads']}")
        print(f"新規プロセス: {stats['new_processes']}")
        print(f"消滅プロセス: {stats['dying_processes']}")

        # 新しいプロセスを表示
        new_procs = manager.get_new_processes()
        if new_procs:
            print("新しい生命体が誕生しました:")
            for proc in new_procs[:3]:  # 最大3つまで表示
                print(f"  - {proc.name} (PID: {proc.pid})")

        # fork操作を検知
        forks = manager.detect_fork()
        if forks:
            print("分裂が発生しました:")
            for parent, child in forks:
                print(f"  - {parent.name} → {child.name}")

        time.sleep(0.5)


if __name__ == "__main__":
    test_process_manager()
