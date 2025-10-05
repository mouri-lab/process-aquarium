# 🐠 プロセス水族館 (アクアリウム) - Process Aquarium

日本語 | [English README](./README.en.md)

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey.svg)

**プロセスを美しい魚として可視化する、インタラクティブな水族館アプリケーション**

プロセス水族館は、コンピューター上で動作するプロセス（プログラム）を水族館の魚として表現し、リアルタイムでモニタリングできる革新的なシステム監視ツールです。従来の味気ないプロセス監視とは一線を画す、視覚的で楽しい体験を提供します。

## 特徴

**ビジュアライゼーション概要**
- 各プロセスはプロセス名を元に決定された色と形状の「魚」として表示
- メモリ使用量: 魚のサイズ（相対比と対数圧縮を組み合わせたスケール）に反映
- CPU使用率: 発光（グロー）強度と最大速度へ反映（色そのものは基本固定）
- スレッド数: 周囲の衛星（最大14個）の数や軌道に反映
- 新規生成/終了: スポーン(フェードイン)とフェードアウトアニメーション

**監視**
- eBPF または psutil によるプロセス情報取得（`--source` で選択）
- CPU / メモリ / スレッド情報を定期更新
- 将来の他ソース追加を見据えた抽象化レイヤを内部実装

**実行オプション**
- ソート基準変更（CPU / メモリ / 名前 / PID）
- 表示数制限
- ヘッドレスモード（統計ログ出力）

## クイックスタート

### 1. 必要な環境

- **Python 3.10以上**
- **Linux**（eBPF機能を最大限活用するため）

### 2. インストール

```bash
# システム依存関係をインストール（Ubuntu/Debian）
sudo apt install -y python3-bpfcc linux-headers-$(uname -r) \
    libbpf-dev clang llvm make gcc python3-venv

# uvをインストール
curl -LsSf https://astral.sh/uv/install.sh | sh

# リポジトリをクローン
git clone https://github.com/mouri-lab/process-aquarium.git
cd process-aquarium
git switch main

# 仮想環境を作成（システムサイトパッケージへのアクセスを有効化）
uv venv -p /usr/bin/python3 --system-site-packages

# 依存関係をインストール
uv sync
```

### 3. 実行

```bash
# eBPFを使用して実行（推奨、root権限が必要）
sudo ./.venv/bin/python3 main.py --source ebpf

# またはpsutilを使用して実行（root権限不要）
./.venv/bin/python3 main.py --source psutil
```

⚠️ 重要な注意事項
- eBPFモード（推奨）: カーネルレベルアクセスが必要なため `sudo` 必須
- システムサイトパッケージ利用: `--system-site-packages` を付けて既存 bpf 関連を再利用
- Pythonバージョン整合性: 不一致は eBPF 読み込み失敗要因

水族館のウィンドウが開き、システム上で動作しているプロセスが魚として表示されます。

## 使い方

### 基本操作

- マウス移動: 視点（カメラ）基準位置の把握
- 左クリック: 魚選択 & 詳細パネル表示
- 右クリック: 選択魚を追従ターゲットに設定
- 左ドラッグ: カメラパン（ドラッグ開始で追従解除）
- マウスホイール: ズーム（0.1x〜5x）
- F / F11: フルスクリーン切替
- Esc: 終了

### キー操作一覧

| キー       | 機能                   | 備考                                 |
| ---------- | ---------------------- | ------------------------------------ |
| Esc        | 終了                   | 即時終了                             |
| F / F11    | フルスクリーン切替     | GPU/非GPU両対応                      |
| D          | デバッグ表示トグル     | 親子プロセス接続線・内部統計補助表示 |
| I          | IPC可視化トグル        | IPCライン/バブル描画                 |
| T          | UI表示トグル           | 情報/ヘルプパネル一括切替            |
| Q          | 群れ強調表示トグル     | 孤立プロセス半透明化                 |
| L          | 表示プロセス数制限切替 | いくつかのプリセット値を循環         |
| S          | ソートフィールド切替   | CPU→MEM→NAME→PID 循環                |
| O          | ソート順序切替         | 昇順/降順                            |
| C          | カメラモード切替       | 自動 / 選択追従 / 手動               |
| R          | カメラリセット         | 位置/ズーム/追従解除                 |
| 左クリック | 魚選択                 | 詳細パネル更新                       |
| 右クリック | 追従ターゲット設定     | 再設定で対象変更                     |
| ホイール   | ズーム                 | ポインタ位置中心スケール             |
| 左ドラッグ | パン                   | 追従解除                             |

### 視覚要素の意味

**色 / 形状**
- 初期色: プロセス名のハッシュから決定
- 形状: ブラウザ/開発ツール/システム系など名称パターンで差異

**サイズ / 発光 / 速度**
- サイズ: メモリ使用量（対数圧縮＋相対シェア補正）
- 発光強度: CPU使用率を指数カーブでマッピング（高負荷ほど強く）
- 速度上限: CPU使用率で指数スケール拡張

**スレッド衛星**
- 最大14個の小衛星ドットが周回（スレッド数に応じて変化）

**特殊エフェクト**
- 大きなメモリ使用（一定閾値超）: 魚の周囲に淡い同心円状の波紋リングがゆっくり脈動
- さらに巨大化（より高い閾値）: 不定期に短い稲妻状の光が周囲に走り、資源突出個体を視覚的に警告
- 目的: リストや数値を見なくても「異様に肥大した/影響力の大きい」プロセスを数秒以内に発見できるようにする

**群れ**
- 目的: 関連するプロセス群を視覚的なまとまりとして把握しやすくするクラスタリング
- 挙動: 距離バランスを保ち整列・凝集する自然な泳ぎを表現
- 強調 (Q): 群れ以外のプロセスを薄く表示し、群れているプロセス際立たせる（分析開始時に有効化推奨）
- 代表的な用途: 大量ワーカー監視 / 短命プロセス生成検知 / 再起動後の再構成観察
- 推奨手順: Q → L → S/O → クリックで詳細

**ライフサイクル**
- 生成直後: スポーンアニメーション（フェード/スケールイン）
- 終了中: フェードアウト
- fork/exec: 一時的な発光や色再生成効果

### コマンドラインオプション

```bash
# ウィンドウサイズを指定
sudo ./.venv/bin/python3 main.py --source ebpf --width 1600 --height 1000

# 表示するプロセス数を制限
sudo ./.venv/bin/python3 main.py --source ebpf --limit 50

# CPU使用率でソート（昇順）
sudo ./.venv/bin/python3 main.py --source ebpf --sort-by cpu --sort-order asc

# メモリ使用率でソート
sudo ./.venv/bin/python3 main.py --source ebpf --sort-by memory

# ヘッドレスモード（GUIなし、統計情報のみ）
sudo ./.venv/bin/python3 main.py --source ebpf --headless --headless-interval 2.0

# psutilモードで実行（root権限不要）
./.venv/bin/python3 main.py --source psutil --limit 50
```

### 利用可能なオプション一覧

| オプション | 説明 | デフォルト値 |
|-----------|------|------------|
| `--width` | ウィンドウの幅 | 1200 |
| `--height` | ウィンドウの高さ | 800 |
| `--limit` | 表示プロセス数の上限 | 制限なし |
| `--sort-by` | ソート基準 (`cpu`, `memory`, `name`, `pid`) | `cpu` |
| `--sort-order` | ソート順序 (`asc`, `desc`) | `desc` |
| `--source` | データソース (`psutil`, `ebpf`) | `ebpf` |
| `--headless` | ヘッドレスモード | false |
| `--headless-interval` | ヘッドレス時の更新間隔（秒） | 1.0 |

## 開発者向け情報

### プロジェクト構造

```
process-aquarium/
├── main.py                    # メインエントリーポイント
├── pyproject.toml            # プロジェクト設定
├── src/
│   ├── core/                 # コア機能
│   │   ├── process_manager.py # プロセス管理
│   │   ├── sources.py        # データソース抽象化（開発者向け内部構造）
│   │   └── types.py          # 型定義
│   └── visuals/              # 視覚化機能
│       ├── aquarium.py       # メイン水族館クラス
│       └── fish.py           # 魚の描画とアニメーション
├── fork_bomb.py              # テスト用大量プロセス生成スクリプト
└── README.md                 # このファイル
```

### テスト用ツール

プロジェクトには大量のプロセスを生成してProcess Aquariumをテストするための `fork_bomb.py` が含まれています：

```bash
# 30個の子プロセスを生成（安全な範囲）
python fork_bomb.py --max-children 30

# 再帰的なプロセス生成（各子プロセスがさらに子を作る）
python fork_bomb.py --recursive --max-children 20

# 指定時間後に自動終了
python fork_bomb.py --duration 60
```

⚠️ **注意**: `fork_bomb.py` は大量のプロセス生成により CPU / メモリ / スレッド数が急増します。実運用環境では使用しないでください。

### 依存関係

- **numpy** (≥2.2.6): 数値計算
- **psutil** (≥7.1.0): システム・プロセス情報取得
- **pygame-ce** (≥2.5.2): グラフィック描画エンジン
- **pytest** (≥8.4.2): テストフレームワーク

### 環境変数

以下の環境変数で動作をカスタマイズできます：

```bash
export AQUARIUM_SOURCE="ebpf"              # データソース
export AQUARIUM_LIMIT="100"                # プロセス表示数制限
export AQUARIUM_SORT_BY="memory"           # ソート基準
export AQUARIUM_SORT_ORDER="desc"          # ソート順序
```

## コントリビューション

1. このリポジトリをフォーク
2. 新しいブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add some amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを作成 (`dev`ブランチに対して)

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。詳細は[LICENSE](LICENSE)ファイルをご覧ください。

## サポート

- **バグレポート**: [GitHub Issues](https://github.com/mouri-lab/process-aquarium/issues)
- **機能リクエスト**: [GitHub Discussions](https://github.com/mouri-lab/process-aquarium/discussions)
- **質問**: Issue またはDiscussionでお気軽にお尋ねください

---

**コンピューターの中で泳ぐプロセスたちを、美しい水族館で観察してみませんか？** 🐠✨
