"""Digital Life Aquarium - プロセス管理モジュール

従来のポーリング方式(psutil)による実装に加えて、今後 eBPF ベースの
イベント駆動ソースへ差し替え可能な抽象レイヤを導入するための
互換ラッパークラス。

新設: ``src.core.sources`` に `IProcessSource` 抽象と `PsutilProcessSource` を
定義し、ここではレガシー API (`update()`, `get_process_statistics()` など) を
保ったまま内部的にソースへ委譲する。
"""

import psutil
import time
import random
from typing import Dict, List, Optional, Set, Any
from dataclasses import dataclass
from datetime import datetime
import random

try:
    # 新しい抽象層 (存在しない場合でも旧来構造で動作できるよう try)
    from .sources import IProcessSource, PsutilProcessSource
    from .types import ProcessInfo as UnifiedProcessInfo, ProcessLifecycleEvent, IPCConnection
except Exception:
    IProcessSource = None  # type: ignore
    PsutilProcessSource = None  # type: ignore
    UnifiedProcessInfo = None  # type: ignore
    ProcessLifecycleEvent = None  # type: ignore
    IPCConnection = None  # type: ignore


if UnifiedProcessInfo is None:
    # フォールバック: 旧来データクラス (新しい types.py が見つからない場合用)
    @dataclass
    class ProcessInfo:  # type: ignore
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
        birth_time: datetime
        last_update: datetime
        is_new: bool = False
        is_dying: bool = False
else:
    # 新しい統一型を再エクスポート
    ProcessInfo = UnifiedProcessInfo  # type: ignore


class ProcessManager:
    """プロセス情報を管理するメインクラス (互換ラッパー)。

    既存コードとの互換性維持のため public API は保持しつつ、内部で
    `IProcessSource` に委譲する。指定されなければ psutil ベースを使用。
    """

    def __init__(self, max_processes: int = 100, source: Optional[Any] = None):  # source: IProcessSource | None
        self.max_processes = max_processes
        self._external_source = source

        # 旧来フィールド（互換目的 / 一部ロジックで参照される）
        self.processes: Dict[int, ProcessInfo] = {}
        self.previous_pids: Set[int] = set()
        self.previous_process_exes: Dict[int, str] = {}
        self.update_interval = 1.0
        self.last_update = time.time()

        # プロセス関係追跡
        self.process_families: Dict[int, List[int]] = {}
        self.recent_forks: List[tuple] = []
        self.recent_execs: List[int] = []

        # 重要/除外フィルタ (psutil直利用時のみ使用)
        self.important_processes = {
            'python', 'chrome', 'firefox', 'safari', 'code', 'terminal',
            'finder', 'dock', 'systemuiserver', 'windowserver', 'kernel_task',
            'launchd', 'zoom', 'slack', 'discord', 'spotify', 'photoshop',
            'illustrator', 'aftereffects', 'node', 'java', 'docker'
        }
        self.excluded_processes = {
            'com.apple.', 'cfprefsd', 'distnoted', 'trustd', 'secd',
            'bluetoothd', 'audiomxd', 'logd_helper', 'deleted'
        }

        # プロセス制限とソート設定
        self.process_limit: Optional[int] = None
        self.sort_by: str = "cpu"  # cpu, memory, name, pid
        self.sort_order: str = "desc"  # asc, desc

        # ソース確立
        if self._external_source is None and PsutilProcessSource is not None:
            self._external_source = PsutilProcessSource(max_processes=max_processes)

    def get_all_processes(self) -> Dict[int, ProcessInfo]:
        """全プロセス情報を取得"""
        return self.processes.copy()

    def set_process_limit(self, limit: Optional[int]) -> None:
        """表示プロセス数の制限を設定"""
        self.process_limit = limit
        if self._external_source is not None and hasattr(self._external_source, 'set_process_limit'):
            self._external_source.set_process_limit(limit)

    def set_sort_config(self, sort_by: str, sort_order: str = "desc") -> None:
        """ソート設定を変更"""
        if sort_by in ["cpu", "memory", "name", "pid"]:
            self.sort_by = sort_by
        if sort_order in ["asc", "desc"]:
            self.sort_order = sort_order
        if self._external_source is not None and hasattr(self._external_source, 'set_sort_config'):
            self._external_source.set_sort_config(sort_by, sort_order)

    def get_process(self, pid: int) -> Optional[ProcessInfo]:
        """指定されたPIDのプロセス情報を取得"""
        return self.processes.get(pid)

    def update(self) -> None:
        """プロセス情報を更新 (抽象ソース経由)。"""
        if self._external_source is not None:
            # 新実装経路
            self._external_source.update()
            snapshot = self._external_source.get_processes()

            # ソートと制限を適用
            snapshot = self._apply_sort_and_limit(snapshot)

            # 互換フィールドへ反映
            self.processes = snapshot
            current_pids = set(snapshot.keys())
            self.previous_pids = current_pids
            # 家族関係再構築
            self._update_process_families(snapshot)

            # exec / fork 検出: lifecycle events を利用
            if hasattr(self._external_source, 'drain_lifecycle_events'):
                try:
                    events = self._external_source.drain_lifecycle_events()
                except Exception:
                    events = []
                for ev in events:
                    if ev.event_type == 'exec':
                        self.recent_execs.append(ev.pid)
                    elif ev.event_type == 'spawn':
                        # spawn + 親存在なら fork とみなす
                        if ev.ppid and ev.ppid in snapshot:
                            parent = snapshot[ev.ppid]
                            child = snapshot.get(ev.pid)
                            if parent and child:
                                self.recent_forks.append((parent, child))
                                self.recent_forks = self.recent_forks[-10:]
            return

        # フォールバック：旧来ロジック（sources が無い環境用）
        current_time = time.time()
        if current_time - self.last_update < self.update_interval:
            return
        # （旧実装を保持するのは冗長なので最小限。将来的に削除可能）
        new_snapshot: Dict[int, ProcessInfo] = {}
        current_pids: Set[int] = set()
        current_exe: Dict[int, str] = {}
        for proc in psutil.process_iter(['pid','ppid','name','exe','memory_percent','cpu_percent','num_threads','create_time','status','cmdline']):
            try:
                info = proc.info
                pid = info['pid']
                name = info['name'] or 'unknown'
                exe = info['exe'] or ''
                mem = info['memory_percent'] or 0.0
                cpu = info['cpu_percent'] or 0.0
                if not self._should_include_process(name, mem, cpu):
                    continue
                current_pids.add(pid)
                current_exe[pid] = exe
                is_new = pid not in self.previous_pids
                pinfo = ProcessInfo(
                    pid=pid, ppid=info['ppid'] or 0, name=name, exe=exe,
                    memory_percent=mem, cpu_percent=cpu,
                    num_threads=info['num_threads'] or 1,
                    create_time=info['create_time'] or 0.0,
                    status=info['status'] or 'unknown',
                    cmdline=info['cmdline'] or [],
                    birth_time=datetime.now() if is_new else (self.processes[pid].birth_time if pid in self.processes else datetime.now()),
                    last_update=datetime.now(), is_new=is_new
                )
                new_snapshot[pid] = pinfo
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue

        # ソートと制限を適用
        new_snapshot = self._apply_sort_and_limit(new_snapshot)

        self._detect_exec_events(current_exe)
        self._update_process_families(new_snapshot)
        dying_processes = []
        for pid in self.previous_pids:
            if pid not in current_pids and pid in self.processes:
                process_name = self.processes[pid].name
                # print(f"⚰️ ProcessManager: プロセス終了検出 PID {pid} ({process_name}) - is_dying=True設定")
                self.processes[pid].is_dying = True
                dying_processes.append(pid)

        # if dying_processes:
        #     print(f"📊 ProcessManager: 今回のサイクルで{len(dying_processes)}個のプロセス終了を検出")
        prev_count = len(self.processes)
        self.processes = new_snapshot
        new_count = len(self.processes)
        # print(f"📊 ProcessManager更新: {prev_count} → {new_count} プロセス (現在PID数: {len(current_pids)})")

        self.previous_pids = current_pids
        self.previous_process_exes = current_exe
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
        if memory_percent > 0.1 or cpu_percent > 0.5:  # 閾値を下げる
            return True

        # その他のプロセスも高確率で選択（制限解除）
        return random.random() < 0.8  # 30%から80%に増加

    def _apply_sort_and_limit(self, processes: Dict[int, ProcessInfo]) -> Dict[int, ProcessInfo]:
        """プロセスをソートして制限を適用"""
        if not processes:
            return processes

        # プロセスリストに変換
        process_list = list(processes.values())

        # ソートキーを決定
        if self.sort_by == "cpu":
            key_func = lambda p: p.cpu_percent
        elif self.sort_by == "memory":
            key_func = lambda p: p.memory_percent
        elif self.sort_by == "name":
            key_func = lambda p: p.name.lower()
        elif self.sort_by == "pid":
            key_func = lambda p: p.pid
        else:
            key_func = lambda p: p.cpu_percent

        # ソート
        reverse = (self.sort_order == "desc")
        process_list.sort(key=key_func, reverse=reverse)

        # 制限を適用
        if self.process_limit is not None and self.process_limit > 0:
            process_list = process_list[:self.process_limit]

        # 辞書に戻す
        return {p.pid: p for p in process_list}

    def get_new_processes(self) -> List[ProcessInfo]:
        """新しく生成されたプロセスのリストを取得"""
        return [proc for proc in self.processes.values() if proc.is_new]

    def get_dying_processes(self) -> List[ProcessInfo]:
        """消滅するプロセスのリストを取得"""
        return [proc for proc in self.processes.values() if proc.is_dying]

    def get_data_source(self) -> str:
        """現在使用中のデータソース名を取得"""
        if self._external_source is not None:
            source_class = self._external_source.__class__.__name__
            if "Ebpf" in source_class:
                return "eBPF"
            elif "Psutil" in source_class:
                return "psutil"
            else:
                return source_class.replace("ProcessSource", "").lower()
        return "psutil"  # フォールバック時

    def get_process_statistics(self) -> Dict[str, any]:
        """プロセス統計情報を取得"""
        total_processes = len(self.processes)
        total_memory = sum(proc.memory_percent for proc in self.processes.values())
        avg_cpu = sum(proc.cpu_percent for proc in self.processes.values()) / total_processes if total_processes > 0 else 0
        total_threads = sum(proc.num_threads for proc in self.processes.values())

        stats = {
            'total_processes': total_processes,
            'total_memory_percent': total_memory,
            'average_cpu_percent': avg_cpu,
            'total_threads': total_threads,
            'new_processes': len(self.get_new_processes()),
            'dying_processes': len(self.get_dying_processes()),
            'data_source': self.get_data_source()
        }

        # eBPFソースの場合はイベント統計を含める
        if (self._external_source is not None and
            hasattr(self._external_source, '_event_stats')):
            event_stats = self._external_source._event_stats
            if event_stats.get('initial_scan', 0) > 0:
                stats['ebpf_events'] = f"initial:{event_stats['initial_scan']} spawn:{event_stats['spawn']} exec:{event_stats['exec']} exit:{event_stats['exit']} captured:{event_stats['captured']}"
            else:
                stats['ebpf_events'] = f"spawn:{event_stats['spawn']} exec:{event_stats['exec']} exit:{event_stats['exit']} captured:{event_stats['captured']}"

        return stats

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
        # まず起点プロセスの親を確認
        start_proc = self.processes.get(pid)
        if start_proc is not None and start_proc.ppid <= 1:
            # launchd配下のプロセスは群れ形成禁止 - 単独行動のみ
            return [start_proc]

        related = []
        visited = set()

        def collect_related(current_pid: int, distance: int):
            if distance > max_distance or current_pid in visited:
                return

            visited.add(current_pid)
            current_proc = self.processes.get(current_pid)
            if current_proc is not None:
                related.append(current_proc)

            # 子プロセスを追加
            for child_pid in self.process_families.get(current_pid, []):
                collect_related(child_pid, distance + 1)

            # 兄弟プロセスを追加
            if current_proc is not None:
                parent_pid = current_proc.ppid
                # 通常の親プロセス配下では全兄弟を含める
                for sibling_pid in self.process_families.get(parent_pid, []):
                    if sibling_pid != current_pid:
                        collect_related(sibling_pid, distance + 1)

        collect_related(pid, 0)
        return related

    def detect_ipc_connections(self) -> List[tuple]:
        """プロセス間通信（IPC）接続を検出

        Returns:
            List[tuple]: (ProcessInfo, ProcessInfo)のタプルリスト
        """
        if self._external_source is not None and hasattr(self._external_source, 'get_ipc_connections'):
            try:
                source_conns = self._external_source.get_ipc_connections(limit=20)
                if source_conns:
                    # source からの形式を (ProcessInfo, ProcessInfo) に変換
                    mapped = []
                    for conn in source_conns:
                        if hasattr(conn, 'pid_a') and hasattr(conn, 'pid_b'):
                            proc_a = self.processes.get(conn.pid_a)
                            proc_b = self.processes.get(conn.pid_b)
                            if proc_a and proc_b and proc_a != proc_b:
                                mapped.append((proc_a, proc_b))
                    if mapped:
                        return mapped[:20]
            except Exception:
                pass

        connections = []

        try:
            # ネットワーク接続からプロセス間通信を推定
            net_connections = psutil.net_connections(kind='inet')

            # ローカル接続を抽出
            local_connections = {}
            for conn in net_connections:
                if (conn.laddr and conn.raddr and
                    conn.laddr.ip in ['127.0.0.1', '::1'] and
                    conn.raddr.ip in ['127.0.0.1', '::1'] and
                    conn.pid):

                    key = (min(conn.laddr.port, conn.raddr.port),
                           max(conn.laddr.port, conn.raddr.port))

                    if key not in local_connections:
                        local_connections[key] = []
                    local_connections[key].append(conn.pid)

            # 同じポートペアを使用するプロセス同士を接続として扱う
            for port_pair, pids in local_connections.items():
                if len(pids) >= 2:
                    unique_pids = list(set(pids))
                    for i in range(len(unique_pids)):
                        for j in range(i + 1, len(unique_pids)):
                            pid1, pid2 = unique_pids[i], unique_pids[j]
                            if pid1 in self.processes and pid2 in self.processes:
                                proc1 = self.processes[pid1]
                                proc2 = self.processes[pid2]
                                connections.append((proc1, proc2))

            # Unixドメインソケット接続の検出
            try:
                unix_connections = psutil.net_connections(kind='unix')
                unix_socket_map = {}

                for conn in unix_connections:
                    if conn.laddr and conn.pid and conn.pid in self.processes:
                        socket_path = conn.laddr
                        if socket_path not in unix_socket_map:
                            unix_socket_map[socket_path] = []
                        unix_socket_map[socket_path].append(conn.pid)

                # 同じUnixソケットパスを使用するプロセス同士を接続として扱う
                for socket_path, pids in unix_socket_map.items():
                    if len(pids) >= 2:
                        unique_pids = list(set(pids))
                        for i in range(len(unique_pids)):
                            for j in range(i + 1, len(unique_pids)):
                                pid1, pid2 = unique_pids[i], unique_pids[j]
                                if pid1 in self.processes and pid2 in self.processes:
                                    proc1 = self.processes[pid1]
                                    proc2 = self.processes[pid2]
                                    # 既に追加されていない場合のみ追加
                                    if not any((p1.pid == proc1.pid and p2.pid == proc2.pid) or
                                              (p1.pid == proc2.pid and p2.pid == proc1.pid)
                                              for p1, p2 in connections):
                                        connections.append((proc1, proc2))

            except (psutil.AccessDenied, OSError):
                # Unixソケットへのアクセス権限がない場合はスキップ
                pass

            # 親子関係も一種のIPC接続として扱う
            for proc in self.processes.values():
                if proc.ppid in self.processes:
                    parent = self.processes[proc.ppid]
                    # 既に追加されていない場合のみ追加
                    if not any((p1.pid == parent.pid and p2.pid == proc.pid) or
                              (p1.pid == proc.pid and p2.pid == parent.pid)
                              for p1, p2 in connections):
                        connections.append((parent, proc))

        except (psutil.AccessDenied, psutil.NoSuchProcess) as e:
            # アクセス権限がない場合は親子関係のみ返す
            for proc in self.processes.values():
                if proc.ppid in self.processes:
                    parent = self.processes[proc.ppid]
                    connections.append((parent, proc))

        # 接続数を制限（パフォーマンス考慮）
        return connections[:20]

    def shutdown(self) -> None:
        """バックエンドソースを安全に停止"""
        if self._external_source is not None and hasattr(self._external_source, "shutdown"):
            try:
                self._external_source.shutdown()
            except Exception:
                pass

    def __del__(self):
        try:
            self.shutdown()
        except Exception:
            pass

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
