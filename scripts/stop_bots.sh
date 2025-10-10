#!/bin/bash
# 交易机器人停止脚本 v2.0
# 功能：安全停止交易机器人，包含止损检查、优雅关闭、强制终止等功能
# 支持：Paradex、GRVT 交易机器人的安全停止

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# 加载配置文件
if [ -f "./scripts/bot_configs.sh" ]; then
    source ./scripts/bot_configs.sh
else
    echo -e "${RED}错误: 配置文件 bot_configs.sh 不存在${NC}"
    exit 1
fi

# 全局变量
STOPPED_BOTS=0
FAILED_STOPS=0
FORCE_STOPS=0
SCRIPT_START_TIME=$(date '+%Y-%m-%d %H:%M:%S')

# 显示使用帮助
show_usage() {
    echo -e "${CYAN}${BOLD}交易机器人停止脚本 v2.1${NC}"
    echo -e "${CYAN}用法: $0 [选项]${NC}"
    echo ""
    echo -e "${YELLOW}选项:${NC}"
    echo -e "${YELLOW}  无参数          停止所有交易机器人${NC}"
    echo -e "${YELLOW}  --paradex       仅停止 Paradex 机器人${NC}"
    echo -e "${YELLOW}  --grvt          仅停止 GRVT 机器人${NC}"
    echo -e "${YELLOW}  --extended      仅停止 Extended (X10) 机器人${NC}"
    echo -e "${YELLOW}  --help, -h      显示此帮助信息${NC}"
    echo ""
    echo -e "${CYAN}示例:${NC}"
    echo -e "${CYAN}  $0              # 停止所有机器人${NC}"
    echo -e "${CYAN}  $0 --paradex    # 仅停止 Paradex 机器人${NC}"
    echo -e "${CYAN}  $0 --grvt       # 仅停止 GRVT 机器人${NC}"
    echo -e "${CYAN}  $0 --extended   # 仅停止 Extended 机器人${NC}"
    echo ""
}

# 处理命令行参数
case "$1" in
    --paradex)
        echo -e "${CYAN}调用独立的 Paradex 停止脚本...${NC}"
        if [ -f "./scripts/stop_paradex.sh" ]; then
            exec ./scripts/stop_paradex.sh
        else
            echo -e "${RED}错误: stop_paradex.sh 脚本不存在${NC}"
            exit 1
        fi
        ;;
    --grvt)
        echo -e "${CYAN}调用独立的 GRVT 停止脚本...${NC}"
        if [ -f "./scripts/stop_grvt.sh" ]; then
            exec ./scripts/stop_grvt.sh
        else
            echo -e "${RED}错误: stop_grvt.sh 脚本不存在${NC}"
            exit 1
        fi
        ;;
    --extended)
        echo -e "${CYAN}调用独立的 Extended 停止脚本...${NC}"
        if [ -f "./scripts/stop_extended.sh" ]; then
            exec ./scripts/stop_extended.sh
        else
            echo -e "${RED}错误: stop_extended.sh 脚本不存在${NC}"
            exit 1
        fi
        ;;
    --help|-h)
        show_usage
        exit 0
        ;;
    "")
        # 无参数，继续执行原有的停止所有机器人逻辑
        ;;
    *)
        echo -e "${RED}错误: 未知参数 '$1'${NC}"
        echo ""
        show_usage
        exit 1
        ;;
esac

echo -e "${RED}${BOLD}=== 交易机器人停止脚本 v2.1 ===${NC}"
echo -e "${CYAN}启动时间: $SCRIPT_START_TIME${NC}"
echo -e "${YELLOW}模式: 停止所有交易机器人${NC}"

# 获取项目根目录（脚本所在目录的上级目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 日志记录函数
log_action() {
    local level=$1
    local message=$2
    local timestamp=$(date '+%Y-%m-%d %H:%M:%S')
    
    case $level in
        "SUCCESS")
            echo -e "${GREEN}[SUCCESS] $message${NC}"
            ;;
        "WARNING")
            echo -e "${YELLOW}[WARNING] $message${NC}"
            ;;
        "ERROR")
            echo -e "${RED}[ERROR] $message${NC}"
            ;;
        "INFO")
            echo -e "${CYAN}[INFO] $message${NC}"
            ;;
    esac
    
    # 记录到日志文件
    echo "[$timestamp] [$level] $message" >> stop_bots.log
}

# 函数：检查止损状态
check_stop_loss_status() {
    local log_file=$1
    local bot_name=$2
    
    log_action "INFO" "检查 $bot_name 的止损状态..."
    
    if [ ! -f "$log_file" ]; then
        log_action "WARNING" "$bot_name 日志文件 $log_file 不存在"
        return 0
    fi
    
    # 检查最近是否有止损执行日志（最近50行）
    local recent_stop_loss=$(tail -50 "$log_file" | grep -i "executing.*stop.loss\|placing.*stop.loss\|stop.loss.*order\|severe.*drawdown.*triggered\|emergency.*stop\|risk.*limit.*exceeded" | tail -1)
    
    if [ -n "$recent_stop_loss" ]; then
        log_action "WARNING" "$bot_name 检测到最近的止损活动"
        echo -e "${CYAN}   详情: $recent_stop_loss${NC}"
        
        # 检查止损是否已完成
        local stop_loss_completed=$(tail -20 "$log_file" | grep -i "stop.loss.*filled\|stop.loss.*completed\|graceful.*shutdown\|position.*closed\|order.*executed")
        
        # 检查是否有活跃的止损进程
        local active_stop_loss_process=$(ps aux | grep -i "stop.*loss\|emergency.*stop" | grep -v grep)
        
        if [ -z "$stop_loss_completed" ] || [ -n "$active_stop_loss_process" ]; then
            log_action "ERROR" "$bot_name 止损可能仍在执行中，建议等待完成"
            if [ -n "$active_stop_loss_process" ]; then
                echo -e "${RED}   活跃止损进程: $active_stop_loss_process${NC}"
            fi
            return 1
        else
            log_action "SUCCESS" "$bot_name 止损已完成"
            return 0
        fi
    else
        log_action "INFO" "$bot_name 未检测到最近的止损活动"
    fi
    return 0
}

# 函数：获取进程详细信息
get_process_info() {
    local pid=$1
    if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
        local cpu_usage=$(ps -p "$pid" -o %cpu --no-headers 2>/dev/null | tr -d ' ')
        local mem_usage=$(ps -p "$pid" -o %mem --no-headers 2>/dev/null | tr -d ' ')
        local start_time=$(ps -p "$pid" -o lstart --no-headers 2>/dev/null)
        echo "CPU: ${cpu_usage}%, 内存: ${mem_usage}%, 启动时间: $start_time"
    fi
}

# 函数：优雅停止进程（带止损检查）
graceful_stop() {
    local pid=$1
    local name=$2
    local log_file=$3
    local force_mode=${4:-false}
    
    if [ -z "$pid" ]; then
        log_action "WARNING" "$name PID 为空"
        return 1
    fi
    
    if ! ps -p "$pid" > /dev/null 2>&1; then
        log_action "WARNING" "$name (PID: $pid) 进程不存在或已停止"
        return 0
    fi
    
    # 显示进程信息
    local process_info=$(get_process_info "$pid")
    log_action "INFO" "准备停止 $name (PID: $pid) - $process_info"
    
    # 检查止损状态（除非强制模式）
    if [ "$force_mode" != "true" ] && [ -n "$log_file" ]; then
        if ! check_stop_loss_status "$log_file" "$name"; then
            echo -e "\n${YELLOW}${BOLD}⚠️  警告: $name 可能正在执行止损操作${NC}"
            echo -e "${YELLOW}强制停止可能导致：${NC}"
            echo -e "${YELLOW}  • 止损订单未完成${NC}"
            echo -e "${YELLOW}  • 仓位风险增加${NC}"
            echo -e "${YELLOW}  • 数据不一致${NC}"
            echo -e "\n${YELLOW}选择操作:${NC}"
            echo -e "${YELLOW}  1) 等待止损完成后再停止 (推荐)${NC}"
            echo -e "${YELLOW}  2) 强制停止 (输入 'force')${NC}"
            echo -e "${YELLOW}  3) 跳过此机器人 (按 Enter)${NC}"
            echo -n -e "${YELLOW}请选择: ${NC}"
            read -r user_input
            
            case "$user_input" in
                "force")
                    log_action "WARNING" "用户选择强制停止 $name"
                    FORCE_STOPS=$((FORCE_STOPS + 1))
                    ;;
                "1")
                    log_action "INFO" "等待 $name 止损完成..."
                    # 等待止损完成的逻辑可以在这里添加
                    echo -e "${CYAN}建议手动监控日志: tail -f $log_file${NC}"
                    return 0
                    ;;
                *)
                    log_action "INFO" "跳过停止 $name"
                    return 0
                    ;;
            esac
        fi
    fi
    
    # 开始停止进程
    log_action "INFO" "发送 SIGTERM 信号给 $name (PID: $pid)"
    if ! kill "$pid" 2>/dev/null; then
        log_action "ERROR" "无法发送停止信号给 $name (PID: $pid)"
        FAILED_STOPS=$((FAILED_STOPS + 1))
        return 1
    fi
    
    # 等待进程优雅退出
    local count=0
    local max_wait=20
    while ps -p "$pid" > /dev/null 2>&1 && [ $count -lt $max_wait ]; do
        sleep 1
        count=$((count + 1))
        
        case $count in
            5)
                log_action "INFO" "$name 正在优雅退出..."
                ;;
            10)
                log_action "WARNING" "$name 退出时间较长，继续等待..."
                ;;
            15)
                log_action "WARNING" "$name 即将强制终止..."
                ;;
        esac
    done
    
    # 检查进程是否已停止
    if ps -p "$pid" > /dev/null 2>&1; then
        log_action "WARNING" "$name 未能优雅退出，执行强制终止"
        if kill -9 "$pid" 2>/dev/null; then
            sleep 2
            if ps -p "$pid" > /dev/null 2>&1; then
                log_action "ERROR" "$name 强制终止失败"
                FAILED_STOPS=$((FAILED_STOPS + 1))
                return 1
            else
                log_action "SUCCESS" "$name 已强制终止"
                FORCE_STOPS=$((FORCE_STOPS + 1))
                STOPPED_BOTS=$((STOPPED_BOTS + 1))
            fi
        else
            log_action "ERROR" "无法强制终止 $name (PID: $pid)"
            FAILED_STOPS=$((FAILED_STOPS + 1))
            return 1
        fi
    else
        log_action "SUCCESS" "$name 已优雅停止"
        STOPPED_BOTS=$((STOPPED_BOTS + 1))
    fi
    
    return 0
}

# 函数：清理PID文件
cleanup_pid_file() {
    local pid_file=$1
    local bot_name=$2
    
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ]; then
            if ps -p "$pid" > /dev/null 2>&1; then
                log_action "INFO" "从 $pid_file 发现 $bot_name (PID: $pid)"
                return 0
            else
                log_action "WARNING" "$pid_file 中的PID $pid 对应的进程不存在，清理陈旧文件"
                rm -f "$pid_file"
                return 1
            fi
        else
            log_action "WARNING" "$pid_file 文件为空，清理无效文件"
            rm -f "$pid_file"
            return 1
        fi
    fi
    return 1
}

echo -e "\n${BLUE}${BOLD}=== 第一阶段：从PID文件停止机器人 ===${NC}"

# 从PID文件停止Paradex机器人
if cleanup_pid_file "$PARADEX_PID_FILE" "Paradex 机器人"; then
    PARADEX_PID=$(cat "$PARADEX_PID_FILE")
    if graceful_stop "$PARADEX_PID" "Paradex 机器人" "$PARADEX_LOG_FILE"; then
        rm -f "$PARADEX_PID_FILE"
        log_action "SUCCESS" "已清理 $PARADEX_PID_FILE 文件"
    fi
else
    log_action "INFO" "未发现有效的 Paradex PID 文件"
fi

# 从PID文件停止GRVT机器人
if cleanup_pid_file "$GRVT_PID_FILE" "GRVT 机器人"; then
    GRVT_PID=$(cat "$GRVT_PID_FILE")
    if graceful_stop "$GRVT_PID" "GRVT 机器人" "$GRVT_LOG_FILE"; then
        rm -f "$GRVT_PID_FILE"
        log_action "SUCCESS" "已清理 $GRVT_PID_FILE 文件"
    fi
else
    log_action "INFO" "未发现有效的 GRVT PID 文件"
fi

# 从PID文件停止Extended机器人
if cleanup_pid_file "$EXTENDED_PID_FILE" "Extended 机器人"; then
    EXTENDED_PID=$(cat "$EXTENDED_PID_FILE")
    if graceful_stop "$EXTENDED_PID" "Extended 机器人" "$EXTENDED_LOG_FILE"; then
        rm -f "$EXTENDED_PID_FILE"
        log_action "SUCCESS" "已清理 $EXTENDED_PID_FILE 文件"
    fi
else
    log_action "INFO" "未发现有效的 Extended PID 文件"
fi

echo -e "\n${BLUE}${BOLD}=== 第二阶段：查找并停止所有 runbot.py 进程 ===${NC}"

# 查找所有运行中的 runbot.py 进程
log_action "INFO" "扫描所有运行中的 runbot.py 进程..."
PIDS=$(ps aux | grep runbot.py | grep -v grep | awk '{print $2}')

if [ -z "$PIDS" ]; then
    log_action "SUCCESS" "没有发现运行中的交易机器人进程"
else
    log_action "INFO" "发现运行中的机器人进程: $PIDS"
    
    for PID in $PIDS; do
        # 获取进程命令行信息
        CMDLINE=$(ps -p "$PID" -o cmd --no-headers 2>/dev/null)
        
        if [ -z "$CMDLINE" ]; then
            log_action "WARNING" "无法获取 PID $PID 的命令行信息，进程可能已退出"
            continue
        fi
        
        if [[ "$CMDLINE" == *"runbot.py"* ]]; then
            # 确定机器人类型
            if [[ "$CMDLINE" == *"paradex"* ]]; then
                log_action "INFO" "识别为 Paradex 机器人: $CMDLINE"
                graceful_stop "$PID" "Paradex 机器人" "$PARADEX_LOG_FILE"
            elif [[ "$CMDLINE" == *"grvt"* ]]; then
                log_action "INFO" "识别为 GRVT 机器人: $CMDLINE"
                graceful_stop "$PID" "GRVT 机器人" "$GRVT_LOG_FILE"
            else
                log_action "INFO" "识别为未知类型交易机器人: $CMDLINE"
                graceful_stop "$PID" "交易机器人" ""
            fi
        else
            log_action "WARNING" "PID $PID 不是 runbot.py 进程: $CMDLINE"
        fi
    done
fi

# 函数：检查剩余进程
check_remaining_processes() {
    log_action "INFO" "执行最终进程检查..."
    
    local remaining_pids=$(ps aux | grep runbot.py | grep -v grep | awk '{print $2}')
    local remaining_count=0
    
    if [ -n "$remaining_pids" ]; then
        for pid in $remaining_pids; do
            local cmdline=$(ps -p "$pid" -o cmd --no-headers 2>/dev/null)
            if [ -n "$cmdline" ]; then
                log_action "ERROR" "仍在运行: PID $pid - $cmdline"
                remaining_count=$((remaining_count + 1))
            fi
        done
    fi
    
    return $remaining_count
}

# 函数：显示日志文件信息
show_log_info() {
    echo -e "\n${BLUE}${BOLD}=== 日志文件信息 ===${NC}"
    
    for log_file in "$PARADEX_LOG_FILE" "$GRVT_LOG_FILE"; do
        if [ -f "$log_file" ]; then
            local size=$(du -h "$log_file" | cut -f1)
            local lines=$(wc -l < "$log_file" 2>/dev/null || echo "0")
            local last_modified=$(stat -c %y "$log_file" 2>/dev/null || echo "未知")
            
            echo -e "${CYAN}📄 $log_file${NC}"
            echo -e "${CYAN}   大小: $size, 行数: $lines${NC}"
            echo -e "${CYAN}   最后修改: $last_modified${NC}"
            
            # 检查最后几行是否有错误
            local recent_errors=$(tail -10 "$log_file" | grep -i "error\|exception\|failed" | wc -l)
            if [ "$recent_errors" -gt 0 ]; then
                echo -e "${YELLOW}   ⚠️  最近10行中发现 $recent_errors 个错误${NC}"
            fi
        else
            echo -e "${YELLOW}📄 $log_file - 文件不存在${NC}"
        fi
    done
}

echo -e "\n${BLUE}${BOLD}=== 第三阶段：最终状态检查 ===${NC}"

# 等待进程完全退出
sleep 3

check_remaining_processes
remaining_count=$?

if [ $remaining_count -eq 0 ]; then
    log_action "SUCCESS" "所有交易机器人已成功停止"
else
    log_action "ERROR" "仍有 $remaining_count 个进程在运行"
    echo -e "\n${YELLOW}${BOLD}强制清理选项:${NC}"
    echo -e "${YELLOW}1. 强制终止所有 runbot.py 进程: ${NC}${CYAN}pkill -9 -f runbot.py${NC}"
    echo -e "${YELLOW}2. 查看详细进程信息: ${NC}${CYAN}ps aux | grep runbot.py${NC}"
    echo -e "${YELLOW}3. 重新运行此脚本: ${NC}${CYAN}./scripts/stop_bots.sh${NC}"
fi

# 显示日志文件信息
show_log_info

# 清理陈旧的PID文件
echo -e "\n${BLUE}${BOLD}=== 清理陈旧文件 ===${NC}"
for pid_file in "$PARADEX_PID_FILE" "$GRVT_PID_FILE" "$EXTENDED_PID_FILE"; do
    if [ -f "$pid_file" ]; then
        pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && ! ps -p "$pid" > /dev/null 2>&1; then
            rm -f "$pid_file"
            log_action "SUCCESS" "已清理陈旧的 $pid_file 文件"
        fi
    fi
done

# 显示操作总结
echo -e "\n${GREEN}${BOLD}=== 操作总结 ===${NC}"
echo -e "${GREEN}✅ 成功停止的机器人: $STOPPED_BOTS${NC}"
if [ $FORCE_STOPS -gt 0 ]; then
    echo -e "${YELLOW}⚠️  强制停止的机器人: $FORCE_STOPS${NC}"
fi
if [ $FAILED_STOPS -gt 0 ]; then
    echo -e "${RED}❌ 停止失败的机器人: $FAILED_STOPS${NC}"
fi

local script_end_time=$(date '+%Y-%m-%d %H:%M:%S')
echo -e "${CYAN}开始时间: $SCRIPT_START_TIME${NC}"
echo -e "${CYAN}结束时间: $script_end_time${NC}"

# 快捷操作提示
echo -e "\n${BLUE}${BOLD}=== 快捷操作 ===${NC}"
echo -e "${CYAN}• 检查机器人状态: ${NC}./scripts/check_bots.sh"
echo -e "${CYAN}• 启动所有机器人: ${NC}./scripts/start_bots.sh"
echo -e "${CYAN}• 启动 Paradex: ${NC}./scripts/start_paradex.sh"
echo -e "${CYAN}• 启动 GRVT: ${NC}./scripts/start_grvt.sh"
echo -e "${CYAN}• 启动 Extended: ${NC}./scripts/start_extended.sh"
echo -e "${CYAN}• 停止 Paradex: ${NC}./scripts/stop_paradex.sh"
echo -e "${CYAN}• 停止 GRVT: ${NC}./scripts/stop_grvt.sh"
echo -e "${CYAN}• 停止 Extended: ${NC}./scripts/stop_extended.sh"
echo -e "${CYAN}• 查看实时日志: ${NC}tail -f $PARADEX_LOG_FILE"
echo -e "${CYAN}• 查看错误日志: ${NC}grep -i error *.log | tail -10"
echo -e "${CYAN}• 清理所有日志: ${NC}rm -f *.log"

if [ $remaining_count -eq 0 ] && [ $FAILED_STOPS -eq 0 ]; then
    echo -e "\n${GREEN}${BOLD}🎉 停止操作完全成功！${NC}"
else
    echo -e "\n${YELLOW}${BOLD}⚠️  停止操作完成，但存在问题，请检查上述信息${NC}"
fi