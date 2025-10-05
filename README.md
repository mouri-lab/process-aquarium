# 🐠 Process Aquarium - プロセス水族館

![Python](https://img.shields.io/badge/Python-3.10+-blue.svg)
![License](https://img.shields.io/badge/License-MIT-green.svg)
![Platform](https://img.shields.io/badge/Platform-Linux-lightgrey.svg)

**システムプロセスを美しい魚として可視化する、インタラクティブな水族館アプリケーション**

Process Aquariumは、コンピューター上で動作するプロセス（プログラム）を水族館の魚として表現し、リアルタイムでモニタリングできる革新的なシステム監視ツールです。従来の味気ないプロセス監視とは一線を画す、視覚的で楽しい体験を提供します。

## 特徴

**美しいビジュアライゼーション**
- 各プロセスが個性豊かな魚として表現される
- CPU使用率やメモリ使用量に応じて魚の動きや色が変化
- リアルタイムで更新される美しい水族館環境

**高性能な監視**
- eBPFベースの高速なプロセス監視
- リアルタイムでのプロセス状態追跡
- 低オーバーヘッドなシステム監視

**柔軟な設定オプション**
- ソート順序の変更（CPU、メモリ、プロセス名、PID）
- 表示プロセス数の制限
- ヘッドレスモードでのコマンドライン実行

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

⚠️ **重要な注意事項**
- **eBPFモード**: カーネルレベルのアクセスが必要なため、`sudo`での実行が必須です
- **システムサイトパッケージ**: `python3-bpfcc`などのシステムパッケージにアクセスするため、仮想環境で`--system-site-packages`オプションを使用しています
- **venvとシステムの整合性**: システム側のPythonパッケージと仮想環境を併用するため、Pythonバージョンの一致が重要です

水族館のウィンドウが開き、システム上で動作しているプロセスが魚として表示されます。

## 使い方

### 基本操作

- **マウス**: 水族館内を自由に観察
- **Esc**: アプリケーションを終了
- **魚をクリック**: プロセス詳細情報を表示

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
│   │   ├── sources.py        # データソース抽象化
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

⚠️ **注意**: `fork_bomb.py`は大量のシステムリソースを消費する可能性があります。テスト環境でのみ使用してください。

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

Process Aquariumの改善にご協力いただける方を歓迎します！

1. このリポジトリをフォーク
2. 新しいブランチを作成 (`git checkout -b feature/amazing-feature`)
3. 変更をコミット (`git commit -m 'Add some amazing feature'`)
4. ブランチにプッシュ (`git push origin feature/amazing-feature`)
5. プルリクエストを作成 (`dev`ブランチに対して)

## ライセンス

このプロジェクトはMITライセンスの下で公開されています。詳細は[LICENSE](LICENSE)ファイルをご覧ください。

## 謝辞

- **numpy**: 高性能な数値計算ライブラリ
- **psutil**: システム情報取得ライブラリ
- **pygame-ce**: グラフィック描画ライブラリ

## サポート

- **バグレポート**: [GitHub Issues](https://github.com/mouri-lab/process-aquarium/issues)
- **機能リクエスト**: [GitHub Discussions](https://github.com/mouri-lab/process-aquarium/discussions)
- **質問**: Issue またはDiscussionでお気軽にお尋ねください

---

**コンピューターの中で泳ぐプロセスたちを、美しい水族館で観察してみませんか？** 🐠✨