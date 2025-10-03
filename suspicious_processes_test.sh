#!/bin/bash
# 簡単な怪しいプロセステスト用スクリプト

# デフォルト値
DEFAULT_COUNT=15
DEFAULT_DURATION=30

# 使用方法表示
show_usage() {
    echo "使用方法: $0 [オプション] [テストモード]"
    echo ""
    echo "オプション:"
    echo "  -c, --count COUNT      生成するプロセス数 (デフォルト: $DEFAULT_COUNT)"
    echo "  -d, --duration DURATION 実行時間（秒） (デフォルト: $DEFAULT_DURATION)"
    echo "  -h, --help             この使用方法を表示"
    echo ""
    echo "テストモード:"
    echo "  all        全てのテスト (デフォルト)"
    echo "  fork       フォーク爆弾のみ"
    echo "  mass       大量プロセス生成のみ"
    echo "  network    ネットワーク通信のみ"
    echo "  names      プロセス名変更のみ"
    echo "  rapid      高速生成削除のみ"
    echo "  cpu        CPU集約的処理のみ"
    echo ""
    echo "実行例:"
    echo "  $0 --count 50 --duration 60 mass"
    echo "  $0 -c 30 fork"
    exit 0
}

# パラメータ解析
PROCESS_COUNT=$DEFAULT_COUNT
DURATION=$DEFAULT_DURATION
MODE="all"

while [[ $# -gt 0 ]]; do
    case $1 in
        -c|--count)
            PROCESS_COUNT="$2"
            shift 2
            ;;
        -d|--duration)
            DURATION="$2"
            shift 2
            ;;
        -h|--help)
            show_usage
            ;;
        all|fork|mass|network|names|rapid|cpu)
            MODE="$1"
            shift
            ;;
        *)
            echo "❌ 不明なオプション: $1"
            show_usage
            ;;
    esac
done

echo "🚀 怪しいプロセステスト開始"
echo "   プロセス数: $PROCESS_COUNT, 実行時間: ${DURATION}秒, モード: $MODE"
echo "=" * 50

# 1. フォーク爆弾（制御された）
echo "💣 フォーク爆弾テスト"
fork_bomb() {
    local depth=$1
    local max_depth=3
    
    if [ $depth -ge $max_depth ]; then
        return
    fi
    
    echo "  🔥 Fork depth: $depth, PID: $$"
    
    if [ $depth -lt $((max_depth - 1)) ]; then
        (fork_bomb $((depth + 1))) &
        (fork_bomb $((depth + 1))) &
    fi
    
    sleep $((RANDOM % 3 + 2))
}

# 2. 大量プロセス生成
mass_processes() {
    local count=${1:-$PROCESS_COUNT}
    echo "🏭 大量プロセス生成テスト ($count プロセス)"
    
    for ((i=1; i<=count; i++)); do
        (
            exec -a "mass_process_$i" bash -c "
                echo '  🔧 Mass process $i started, PID: $$'
                sleep \$((RANDOM % 20 + 10))  # 10-30秒に延長
                echo '  ✅ Mass process $i completed'
            "
        ) &
        sleep 0.1
    done
}

# 3. プロセス名変更テスト
name_changer() {
    local count=${1:-$((PROCESS_COUNT / 3))}
    echo "🎭 プロセス名変更テスト ($count プロセス)"
    
    local names=("definitely_not_malware" "system_update" "legitimate_process" "chrome_helper" "kernel_worker" "security_daemon" "backup_service" "network_monitor")
    
    for ((i=1; i<=count; i++)); do
        local name_index=$((i % ${#names[@]}))
        local name="${names[$name_index]}_$i"
        exec -a "$name" bash -c "
            echo '  🎪 Process name changed to: $name, PID: $$'
            sleep \$((RANDOM % 15 + 15))  # 15-30秒に延長
        " &
        sleep 0.5
    done
}

# 4. 高速生成削除
rapid_spawn() {
    local cycles=${1:-3}
    local spawn_count=${2:-$((PROCESS_COUNT / 5))}
    echo "⚡ 高速プロセス生成削除テスト ($cycles サイクル, $spawn_count プロセス/サイクル)"
    
    for ((cycle=1; cycle<=cycles; cycle++)); do
        echo "  🔄 Cycle $cycle"
        
        # 高速生成
        for ((i=1; i<=spawn_count; i++)); do
            (
                exec -a "rapid_${cycle}_${i}" bash -c "
                    sleep \$((RANDOM % 10 + 5))  # 5-15秒に延長
                "
            ) &
        done
        
        sleep 2
        echo "  ✅ Cycle $cycle completed"
        sleep 1
    done
}

# 5. CPU集約的プロセス
cpu_intensive() {
    local count=${1:-$((PROCESS_COUNT / 10))}
    local duration=${2:-$DURATION}
    echo "💻 CPU集約的プロセステスト ($count ワーカー, ${duration}秒)"
    
    for ((i=1; i<=count; i++)); do
        (
            exec -a "cpu_intensive_$i" bash -c "
                echo '  🔥 CPU intensive worker $i started, PID: $$'
                # CPU集約的な処理をシミュレート（計算量を大幅に増加）
                local iterations=\$((duration * 100000))  # 10倍に増加
                for ((j=1; j<=iterations; j++)); do
                    result=\$((j * j))
                    # 少し休憩してCPU時間を他に譲る
                    if [ \$((j % 10000)) -eq 0 ]; then
                        sleep 0.001
                    fi
                    if [ \$((j % (iterations/4))) -eq 0 ]; then
                        echo '    📊 Worker $i: progress \$((j*100/iterations))%'
                    fi
                done
                echo '  ✅ CPU intensive worker $i completed'
            "
        ) &
        sleep 0.2
    done
}

# 6. ネットワーク通信シミュレート
network_test() {
    local duration=${1:-$((DURATION / 3))}
    echo "🌐 ネットワーク通信テスト (${duration}秒)"
    
    (
        exec -a "network_scanner" bash -c "
            echo '  🔌 Network scanner started, PID: $$'
            local end_time=\$((SECONDS + duration))
            # 各種ポートへの接続試行をシミュレート
            while [ \$SECONDS -lt \$end_time ]; do
                for port in 22 80 443 8080 3306 5432; do
                    [ \$SECONDS -ge \$end_time ] && break
                    timeout 1 bash -c '</dev/tcp/127.0.0.1/\$port' 2>/dev/null && \
                        echo '    ✅ Port \$port: open' || \
                        echo '    ❌ Port \$port: closed/filtered'
                    sleep 0.5
                done
            done
            echo '  🏁 Network scanner completed'
        "
    ) &
}

# 実行
trap 'echo "🛑 テストが中断されました"; exit 0' INT

case "$MODE" in
    "fork")
        fork_bomb 0 &
        ;;
    "mass")
        mass_processes $PROCESS_COUNT
        ;;
    "names")
        name_changer $PROCESS_COUNT
        ;;
    "rapid")
        rapid_spawn 3 $((PROCESS_COUNT / 5))
        ;;
    "cpu")
        cpu_intensive $((PROCESS_COUNT / 10)) $DURATION
        ;;
    "network")
        network_test $DURATION
        ;;
    "all"|*)
        fork_bomb 0 &
        sleep 2
        mass_processes $((PROCESS_COUNT / 3))
        sleep 3
        name_changer $((PROCESS_COUNT / 3))
        sleep 2
        rapid_spawn 3 $((PROCESS_COUNT / 5))
        sleep 2
        cpu_intensive $((PROCESS_COUNT / 10)) $((DURATION / 3))
        sleep 1
        network_test $((DURATION / 3))
        ;;
esac

echo "⏳ テスト実行中... (最大 ${DURATION}秒, Ctrl+C で停止)"

# タイムアウト付きで待機
timeout $DURATION bash -c 'wait' 2>/dev/null || true

echo "🎉 テスト完了!"