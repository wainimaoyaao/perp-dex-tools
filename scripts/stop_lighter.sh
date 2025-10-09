#!/bin/bash
# Lighter 交易机器人停止脚本
# 功能：安全停止 Lighter 交易机器人

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# 获取项目根目录（脚本所在目录的上级目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 加载配置文件
if [ -f "scripts/bot_configs.sh" ]; then
    source ./scripts/bot_configs.sh
else
    echo -e "${RED}错误: 找不到配置文件 scripts/bot_configs.sh${NC}"
    exit 1
fi

echo -e "${RED}${BOLD}=== Lighter 交易机器人停止脚本 ===${NC}"
echo -e "${CYAN}停止时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"

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
    if [ -d "logs" ]; then
        echo "[$timestamp] [$level] $message" >> "logs/lighter_stop.log"
    fi
}

# 函数：查找 Lighter 机器人进程
find_lighter_processes() {
    local pids=$(pgrep -f "trading_bot.py.*lighter")
    echo "$pids"
}

# 函数：从PID文件获取进程ID
get_pid_from_file() {
    if [ -f "logs/lighter_bot.pid" ]; then
        local pid=$(cat logs/lighter_bot.pid)
        if kill -0 $pid 2>/dev/null; then
            echo "$pid"
        else
            log_action "WARNING" "PID文件中的进程 ($pid) 已不存在"
            return 1
        fi
    else
        log_action "INFO" "未找到PID文件"
        return 1
    fi
}

# 函数：显示进程信息
show_process_info() {
    local pids=$1
    
    if [ -z "$pids" ]; then
        log_action "INFO" "未找到运行中的 Lighter 机器人进程"
        return 1
    fi
    
    log_action "INFO" "发现以下 Lighter 机器人进程:"
    
    for pid in $pids; do
        echo -e "${CYAN}  PID: $pid${NC}"
        
        # 显示进程启动时间
        local start_time=$(ps -o lstart= -p $pid 2>/dev/null)
        if [ ! -z "$start_time" ]; then
            echo -e "${CYAN}    启动时间: $start_time${NC}"
        fi
        
        # 显示进程运行时间
        local etime=$(ps -o etime= -p $pid 2>/dev/null)
        if [ ! -z "$etime" ]; then
            echo -e "${CYAN}    运行时间: $etime${NC}"
        fi
        
        # 显示内存使用
        local memory=$(ps -o rss= -p $pid 2>/dev/null)
        if [ ! -z "$memory" ]; then
            local memory_mb=$((memory / 1024))
            echo -e "${CYAN}    内存使用: ${memory_mb}MB${NC}"
        fi
        
        # 显示命令行（截取部分）
        local cmdline=$(ps -o args= -p $pid 2>/dev/null | cut -c1-80)
        if [ ! -z "$cmdline" ]; then
            echo -e "${CYAN}    命令: $cmdline...${NC}"
        fi
        
        echo ""
    done
}

# 函数：优雅停止进程
graceful_stop() {
    local pid=$1
    local timeout=${2:-30}  # 默认30秒超时
    
    log_action "INFO" "尝试优雅停止进程 $pid (SIGTERM)"
    
    # 发送SIGTERM信号
    if kill -TERM $pid 2>/dev/null; then
        log_action "SUCCESS" "已发送SIGTERM信号到进程 $pid"
        
        # 等待进程结束
        local count=0
        while [ $count -lt $timeout ]; do
            if ! kill -0 $pid 2>/dev/null; then
                log_action "SUCCESS" "进程 $pid 已优雅停止"
                return 0
            fi
            
            sleep 1
            count=$((count + 1))
            
            # 每5秒显示一次等待信息
            if [ $((count % 5)) -eq 0 ]; then
                log_action "INFO" "等待进程 $pid 停止... (${count}/${timeout}秒)"
            fi
        done
        
        log_action "WARNING" "进程 $pid 在 $timeout 秒内未能优雅停止"
        return 1
    else
        log_action "ERROR" "无法发送SIGTERM信号到进程 $pid"
        return 1
    fi
}

# 函数：强制停止进程
force_stop() {
    local pid=$1
    
    log_action "WARNING" "强制停止进程 $pid (SIGKILL)"
    
    if kill -KILL $pid 2>/dev/null; then
        sleep 2
        if ! kill -0 $pid 2>/dev/null; then
            log_action "SUCCESS" "进程 $pid 已被强制停止"
            return 0
        else
            log_action "ERROR" "无法强制停止进程 $pid"
            return 1
        fi
    else
        log_action "ERROR" "无法发送SIGKILL信号到进程 $pid"
        return 1
    fi
}

# 函数：清理PID文件
cleanup_pid_file() {
    if [ -f "logs/lighter_bot.pid" ]; then
        local pid=$(cat logs/lighter_bot.pid)
        if ! kill -0 $pid 2>/dev/null; then
            rm -f "logs/lighter_bot.pid"
            log_action "SUCCESS" "已清理无效的PID文件"
        else
            log_action "WARNING" "PID文件中的进程仍在运行，保留PID文件"
        fi
    fi
}

# 函数：停止所有Lighter进程
stop_all_processes() {
    local force_mode=$1
    local timeout=${2:-30}
    
    # 查找所有Lighter进程
    local pids=$(find_lighter_processes)
    
    if [ -z "$pids" ]; then
        log_action "INFO" "未找到运行中的 Lighter 机器人进程"
        cleanup_pid_file
        return 0
    fi
    
    # 显示进程信息
    show_process_info "$pids"
    
    # 确认停止
    if [ "$force_mode" != "force" ]; then
        echo -e "${YELLOW}确认停止以上 Lighter 机器人进程? (y/n)${NC}"
        read -r response
        if [[ ! "$response" =~ ^[Yy]$ ]]; then
            log_action "INFO" "用户取消停止操作"
            exit 0
        fi
    fi
    
    local stopped_count=0
    local failed_count=0
    
    # 逐个停止进程
    for pid in $pids; do
        echo -e "${CYAN}正在停止进程 $pid...${NC}"
        
        if graceful_stop $pid $timeout; then
            stopped_count=$((stopped_count + 1))
        else
            # 优雅停止失败，尝试强制停止
            if force_stop $pid; then
                stopped_count=$((stopped_count + 1))
            else
                failed_count=$((failed_count + 1))
                log_action "ERROR" "无法停止进程 $pid"
            fi
        fi
    done
    
    # 清理PID文件
    cleanup_pid_file
    
    # 显示结果
    echo ""
    log_action "INFO" "停止操作完成"
    log_action "SUCCESS" "成功停止: $stopped_count 个进程"
    if [ $failed_count -gt 0 ]; then
        log_action "ERROR" "停止失败: $failed_count 个进程"
    fi
    
    return $failed_count
}

# 函数：显示最后的日志
show_final_logs() {
    local log_file="logs/$LIGHTER_LOG_FILE"
    
    if [ -f "$log_file" ]; then
        echo -e "${CYAN}=== 最后的日志记录 (最后10行) ===${NC}"
        echo -e "${BLUE}----------------------------------------${NC}"
        tail -n 10 "$log_file" 2>/dev/null | while read line; do
            echo -e "${BLUE}$line${NC}"
        done
        echo -e "${BLUE}----------------------------------------${NC}"
        echo ""
    fi
}

# 函数：显示停止后信息
show_post_stop_info() {
    echo -e "${GREEN}=== Lighter 机器人停止完成 ===${NC}"
    echo -e "${CYAN}停止时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo ""
    echo -e "${CYAN}常用命令:${NC}"
    echo -e "${BLUE}  检查机器人状态: ./scripts/check_lighter.sh${NC}"
    echo -e "${BLUE}  启动机器人: ./scripts/start_lighter.sh${NC}"
    echo -e "${BLUE}  查看日志: tail -f logs/$LIGHTER_LOG_FILE${NC}"
    echo -e "${BLUE}  查看所有机器人: ./scripts/check_bots.sh${NC}"
    echo ""
    echo -e "${YELLOW}注意: 停止机器人可能会影响正在进行的交易${NC}"
    echo -e "${YELLOW}建议在停止前检查是否有未完成的订单${NC}"
    echo ""
}

# 函数：快速停止模式
quick_stop() {
    log_action "INFO" "快速停止模式"
    
    local pids=$(find_lighter_processes)
    if [ -z "$pids" ]; then
        log_action "INFO" "未找到运行中的 Lighter 机器人进程"
        return 0
    fi
    
    for pid in $pids; do
        log_action "INFO" "快速停止进程 $pid"
        if kill -TERM $pid 2>/dev/null; then
            sleep 3
            if ! kill -0 $pid 2>/dev/null; then
                log_action "SUCCESS" "进程 $pid 已停止"
            else
                kill -KILL $pid 2>/dev/null
                log_action "SUCCESS" "进程 $pid 已强制停止"
            fi
        fi
    done
    
    cleanup_pid_file
}

# 主函数
main() {
    local force_mode=""
    local quick_mode=""
    local timeout=30
    
    # 解析命令行参数
    while [[ $# -gt 0 ]]; do
        case $1 in
            --force|-f)
                force_mode="force"
                shift
                ;;
            --quick|-q)
                quick_mode="quick"
                shift
                ;;
            --timeout|-t)
                timeout="$2"
                shift 2
                ;;
            --help|-h)
                echo "Lighter 交易机器人停止脚本"
                echo ""
                echo "用法:"
                echo "  $0                    交互式停止"
                echo "  $0 --force           强制停止（无确认）"
                echo "  $0 --quick           快速停止"
                echo "  $0 --timeout 60      设置超时时间（秒）"
                echo "  $0 --help            显示帮助"
                echo ""
                exit 0
                ;;
            *)
                log_action "ERROR" "未知参数: $1"
                exit 1
                ;;
        esac
    done
    
    # 执行停止操作
    if [ "$quick_mode" = "quick" ]; then
        quick_stop
    else
        stop_all_processes "$force_mode" "$timeout"
    fi
    
    # 显示最后的日志和停止后信息
    if [ "$quick_mode" != "quick" ]; then
        show_final_logs
        show_post_stop_info
    fi
}

# 错误处理
set -e
trap 'log_action "ERROR" "脚本执行出错"' ERR

# 执行主函数
main "$@"