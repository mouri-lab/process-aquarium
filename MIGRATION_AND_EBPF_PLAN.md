# Process Aquarium Migration & eBPF Plan

## 1. 現状サマリ (feat/ebpf_monitor ブランチ)
- 可視化: `pygame-ce` によるプロセス群ビジュアライゼーション (魚エンティティ)
- データ取得: 既定は `psutil` ポーリング (1s)
- 抽象化導入:
  - `src/core/types.py`: `ProcessInfo`, `ProcessLifecycleEvent`, `IPCConnection`
  - `src/core/sources.py`: `IProcessSource`, `PsutilProcessSource`, `EbpfProcessSource (MVP)`
  - `src/core/process_manager.py`: 既存API互換ラッパ (source 差し替え対応)
- ヘッドレス対応: `--headless` / `--headless-interval` (統計ログのみ出力)
- eBPF (MVP): fork/exec/exit tracepoint を BCC で購読 → lifecycle events 化 (IPC は未実装)
- ソース選択: `--source ebpf` または `AQUARIUM_SOURCE=ebpf` (失敗時 psutil フォールバック)

## 2. これまで追加/変更点一覧
| 区分 | 追加ファイル / 変更 | 概要 |
|------|---------------------|------|
| 抽象層 | `types.py` | 統一データモデル定義 |
| 抽象層 | `sources.py` | psutil実装移植 + eBPF実装(MVP) |
| 管理 | `process_manager.py` | Source委譲 + 互換維持 |
| 表示 | `aquarium.py` | ソース自動選択(環境変数) + headless 対応 |
| 起動 | `main.py` | CLI引数: `--headless`, `--headless-interval`, `--source` |
| 文書 | `README.md` | eBPF / headless 使用法、設計概要追加 |
| 新規 | `MIGRATION_AND_EBPF_PLAN.md` | このまとめ |

## 3. 現在の制約 / 課題
- OrbStack カスタムカーネルで bcc パッケージ (apt) がインストール不可
- eBPF ソースはリソース統計 (CPU%, MEM%) を取得せず spawn/exec/exit イベントのみ
- IPC 可視化は psutil 推定 (loopback + 親子) で精度限定
- 魚の近傍探索 O(N^2) (大量プロセスでスケール課題)
- マジックナンバー散在 (距離・しきい値) / テスト未整備

## 4. 環境移行時の推奨手順
### A. 新環境 (標準 Ubuntu カーネル) セットアップ
```bash
sudo apt update
sudo apt install -y python3-bpfcc linux-headers-$(uname -r) \
    libbpf-dev clang llvm make gcc python3-venv
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt  # (bcc が必要なら requirements に追記可)
```

### B. eBPF 動作検証
```bash
sudo python main.py --source ebpf --headless --headless-interval 2
```
期待ログ: `[eBPF] EbpfProcessSource 有効化` + 定期統計行

### C. フォールバック確認
```bash
AQUARIUM_SOURCE=ebpf python main.py --headless  # 権限なしで実行
# => 利用不可ログ後 psutil にフォールバック
```

### D. Docker (代替) 例
```bash
docker run --rm -it --privileged -v $(pwd):/app -w /app ubuntu:24.04 bash
# コンテナ内で A, B を実行
```

## 5. 今後のロードマップ (提案)
| 優先 | 項目 | 内容 | 見積(相対) |
|------|------|------|------------|
| 高 | ハイブリッド統合 | eBPF lifecycle + psutil メトリクス融合 | M |
| 高 | IPC 拡張 | ソケット/Unix/Pipe eBPF トレース → `IPCConnection.kind` 詳細化 | M~L |
| 中 | 近傍最適化 | グリッド/Quadtree で O(N) 近傍探索 | M |
| 中 | JSON/ストリーム出力 | `--json` で NDJSON 統計 + イベント | S |
| 中 | テスト基盤 | sources の unit test (mock psutil, fake ring buffer) | M |
| 低 | Config 化 | `.toml` / `.env` で閾値・表示調整 | S |
| 低 | 色/テーマ拡張 | CPU / メモリ / IPC種別によるカラー定義 | S |

## 6. ハイブリッド設計案 (概要)
```
+------------------+    +----------------------+    +------------------+
| EbpfProcessSource| -> | LifecycleEventMerger  | -> | Unified Store     |
|  (events)        |    |  (ring drain & map)  |    | (pid -> ProcessInfo)
+------------------+    +----------------------+    +------------------+
                                 ^
                                 |
                    +-------------------------+
                    | PsutilMetricsRefresher  |
                    | (interval CPU/MEM scan) |
                    +-------------------------+
```
- Event 受信後、該当 PID の `ProcessInfo` を作成/更新 (初期 CPU/MEM は 0)
- 定期 psutil スキャンで差分メトリクス埋め戻し
- 失踪 PID は exit イベント無ければタイムアウト扱い (保険)

## 7. CO-RE への将来拡張メモ
- `/sys/kernel/btf/vmlinux` を利用しヘッダ依存を軽減
- libbpf (Python ラッパ or 生成した skel C 呼び出し) で最小 BPF
- Distroless / コンテナ軽量化容易に

## 8. リスク & 対策
| リスク | 影響 | 緩和策 |
|--------|------|--------|
| カーネル非互換 (eBPF) | 起動失敗 / フォールバック多発 | 早期にエラーをイベント化しUI表示 |
| 短命プロセス取りこぼし | 可視化抜け | eBPF ソース優先 / ハイブリッド化 | 
| 大量プロセス時のFPS低下 | UX劣化 | 近傍最適化 + 魚描画サンプリング |
| bcc 依存肥大化 | 配布サイズ | CO-RE 化 / plugin 選択制 |
| IPC 誤識別 | 誤学習・混乱 | 種別タグ付け & 凡例表示 |

## 9. 移行時チェックリスト
- [ ] 新環境で `psutil` 可視化起動確認
- [ ] eBPF import / attach 成功
- [ ] fork/exec/exit イベント表示（デバッグ用ログ出力追加検討）
- [ ] フォールバック発生条件テスト (非root / 権限なし)
- [ ] ハイブリッド PoC ブランチ作成

## 10. 参考コマンド集
```bash
# Headless psutil
python main.py --headless

# eBPF + headless
sudo python main.py --source ebpf --headless --headless-interval 2

# フォールバック確認 (権限無し)
python main.py --source ebpf --headless

# 一時的イベント多発 (短命プロセス生成)
for i in $(seq 1 50); do /bin/true; done
```

## 11. 次アクション候補
1. ハイブリッド統合基盤の `HybridProcessSource` スケルトン追加
2. eBPF IPC (inet connect state) 追跡 BPF プログラム分割
3. JSON ロギングオプション `--json` 実装
4. 近傍探索最適化（セルパーティショニング）

---
更新日: 2025-10-03
