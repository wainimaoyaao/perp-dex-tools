#!/bin/bash
# Lighter 交易机器人状态检查脚本
# 功能：专门检查 Lighter 交易机器人的运行状态、配置和日志

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
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

# 加载日志工具函数库
if [ -f "scripts/log_utils.sh" ]; then
    source ./scripts/log_utils.sh
else
    echo -e "${YELLOW}警告: 找不到日志工具函数库 scripts/log_utils.sh${NC}"
fi

# 全局变量
TOTAL_ISSUES=0
CRITICAL_ISSUES=0

# 函数：记录问题
log_issue() {
    local severity=$1
    local message=$2
    
    if [ "$severity" = "critical" ]; then
        TOTAL_ISSUES=$((TOTAL_ISSUES + 1))
        CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
        echo -e "${RED}❌ [严重] $message${NC}"
    elif [ "$severity" = "warning" ]; then
        TOTAL_ISSUES=$((TOTAL_ISSUES + 1))
        echo -e "${YELLOW}⚠️  [警告] $message${NC}"
    else
        echo -e "${CYAN}ℹ️  [信息] $message${NC}"
    fi
}

# 函数：显示成功状态
log_success() {
    local message=$1
    echo -e "${GREEN}✅ $message${NC}"
}

# 函数：显示标题
show_header() {
    echo -e "${BLUE}${BOLD}================================================${NC}"
    echo -e "${BLUE}${BOLD}        Lighter 交易机器人状态检查${NC}"
    echo -e "${BLUE}${BOLD}================================================${NC}"
    echo -e "${CYAN}检查时间: $(date '+%Y-%m-%d %H:%M:%S')${NC}"
    echo -e "${CYAN}工作目录: $PROJECT_ROOT${NC}"
    echo ""
}

# 函数：检查进程详细信息
check_process_details() {
    local pid=$1
    
    if [ -z "$pid" ] || ! ps -p "$pid" > /dev/null 2>&1; then
        return 1
    fi
    
    # 获取进程信息
    local cpu_usage=$(ps -p "$pid" -o %cpu --no-headers | tr -d ' ')
    local mem_usage=$(ps -p "$pid" -o %mem --no-headers | tr -d ' ')
    local start_time=$(ps -p "$pid" -o lstart --no-headers)
    local runtime=$(ps -p "$pid" -o etime --no-headers | tr -d ' ')
    
    echo -e "${CYAN}   CPU: ${cpu_usage}%, 内存: ${mem_usage}%${NC}"
    echo -e "${CYAN}   运行时间: $runtime${NC}"
    echo -e "${CYAN}   启动时间: $start_time${NC}"
    
    return 0
}

# 函数：检查进程状态
check_process_status() {
    echo -e "${PURPLE}${BOLD}=== 进程状态检查 ===${NC}"
    
    # 使用与paradex相同的方法检查进程
    LIGHTER_PROCESSES=$(ps aux | grep runbot.py | grep lighter | grep -v grep || true)
    
    if [ -z "$LIGHTER_PROCESSES" ]; then
        log_issue "critical" "Lighter 交易机器人未在运行"
    else
        bot_count=$(echo "$LIGHTER_PROCESSES" | wc -l || echo "0")
        log_success "发现 $bot_count 个运行中的 Lighter 机器人"
        
        echo "$LIGHTER_PROCESSES" | while read -r line; do
            PID=$(echo "$line" | awk '{print $2}')
            CMD=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf "%s ", $i; print ""}')
            
            echo -e "${CYAN}   🔹 Lighter (PID: $PID)${NC}"
            check_process_details "$PID"
            echo ""
        done
    fi
    
    # 检查PID文件
    if [ -f "logs/lighter_bot.pid" ]; then
        local saved_pid=$(cat logs/lighter_bot.pid)
        if kill -0 $saved_pid 2>/dev/null; then
            log_success "PID 文件中的进程 ($saved_pid) 仍在运行"
        else
            log_issue "warning" "PID 文件存在但进程 ($saved_pid) 已停止"
        fi
    else
        log_issue "info" "未找到 PID 文件 (logs/lighter_bot.pid)"
    fi
    
    echo ""
    return 0
}

# 函数：检查配置文件
check_configuration() {
    echo -e "${PURPLE}${BOLD}=== 配置检查 ===${NC}"
    
    # 检查环境变量文件
    if [ -f "$LIGHTER_ENV_FILE" ]; then
        log_success "环境变量文件存在: $LIGHTER_ENV_FILE"
        
        # 检查关键环境变量（不显示具体值）
        if grep -q "LIGHTER_" "$LIGHTER_ENV_FILE" 2>/dev/null; then
            log_success "发现 Lighter 相关环境变量"
        else
            log_issue "warning" "未在环境文件中找到 Lighter 相关配置"
        fi
    else
        log_issue "critical" "环境变量文件不存在: $LIGHTER_ENV_FILE"
    fi
    
    # 检查虚拟环境
    if [ -d "$LIGHTER_ENV_PATH" ]; then
        log_success "虚拟环境目录存在: $LIGHTER_ENV_PATH"
        
        if [ -f "$LIGHTER_ENV_PATH/bin/python3" ]; then
            local python_version=$($LIGHTER_ENV_PATH/bin/python3 --version 2>&1)
            log_success "Python 环境: $python_version"
        else
            log_issue "critical" "虚拟环境中缺少 Python 解释器"
        fi
    else
        log_issue "critical" "虚拟环境目录不存在: $LIGHTER_ENV_PATH"
    fi
    
    # 显示当前配置参数
    echo -e "${CYAN}当前 Lighter 配置参数:${NC}"
    echo -e "${BLUE}  交易对: $LIGHTER_TICKER${NC}"
    echo -e "${BLUE}  数量: $LIGHTER_QUANTITY${NC}"
    echo -e "${BLUE}  止盈: $LIGHTER_TAKE_PROFIT${NC}"
    echo -e "${BLUE}  方向: $LIGHTER_DIRECTION${NC}"
    echo -e "${BLUE}  最大订单数: $LIGHTER_MAX_ORDERS${NC}"
    echo -e "${BLUE}  等待时间: $LIGHTER_WAIT_TIME 秒${NC}"
    echo -e "${BLUE}  网格步长: $LIGHTER_GRID_STEP%${NC}"
    echo -e "${BLUE}  回撤监控: $LIGHTER_ENABLE_DRAWDOWN_MONITOR${NC}"
    
    echo ""
}

# 函数：检查日志文件
check_logs() {
    echo -e "${PURPLE}${BOLD}=== 日志检查 ===${NC}"
    
    local log_file="logs/$LIGHTER_LOG_FILE"
    
    # 检查日志轮转状态（如果log_utils.sh可用）
    if command -v analyze_log_rotation_status >/dev/null 2>&1; then
        echo -e "${CYAN}${BOLD}--- 日志轮转状态 ---${NC}"
        analyze_log_rotation_status "$LIGHTER_LOG_FILE"
        echo ""
    fi
    
    if [ -f "$log_file" ]; then
        log_success "日志文件存在: $log_file"
        
        # 检查日志文件大小
        local file_size=$(stat -f%z "$log_file" 2>/dev/null || stat -c%s "$log_file" 2>/dev/null)
        if [ ! -z "$file_size" ]; then
            local size_mb=$((file_size / 1024 / 1024))
            echo -e "${CYAN}日志文件大小: ${size_mb}MB${NC}"
            
            # 使用配置的最大大小进行检查
            local max_size=${LOG_MAX_SIZE_MB:-50}
            if [ $size_mb -gt $max_size ]; then
                if [ "$LOG_ROTATION_ENABLED" = "true" ]; then
                    log_issue "warning" "日志文件大小 (${size_mb}MB) 超过配置的最大值 (${max_size}MB)，将在下次启动时轮转"
                else
                    log_issue "warning" "日志文件较大 (${size_mb}MB)，建议启用日志轮转或定期清理"
                fi
            fi
        fi
        
        # 检查最近的日志条目
        local last_modified=$(stat -f%m "$log_file" 2>/dev/null || stat -c%Y "$log_file" 2>/dev/null)
        if [ ! -z "$last_modified" ]; then
            local current_time=$(date +%s)
            local time_diff=$((current_time - last_modified))
            
            if [ $time_diff -lt 300 ]; then  # 5分钟内
                log_success "日志文件最近有更新 (${time_diff}秒前)"
            elif [ $time_diff -lt 3600 ]; then  # 1小时内
                local minutes=$((time_diff / 60))
                log_issue "warning" "日志文件 ${minutes}分钟前更新，可能机器人已停止"
            else
                local hours=$((time_diff / 3600))
                log_issue "critical" "日志文件 ${hours}小时前更新，机器人可能已停止"
            fi
        fi
        
        # 显示最近的日志内容
        echo -e "${CYAN}最近的日志内容 (最后10行):${NC}"
        echo -e "${BLUE}----------------------------------------${NC}"
        tail -n 10 "$log_file" 2>/dev/null | while read line; do
            echo -e "${BLUE}$line${NC}"
        done
        echo -e "${BLUE}----------------------------------------${NC}"
        
        # 检查错误信息
        local error_count=$(grep -i "error\|exception\|failed" "$log_file" 2>/dev/null | wc -l)
        if [ $error_count -gt 0 ]; then
            log_issue "warning" "日志中发现 $error_count 个错误/异常"
            echo -e "${YELLOW}最近的错误信息:${NC}"
            grep -i "error\|exception\|failed" "$log_file" 2>/dev/null | tail -n 3 | while read line; do
                echo -e "${YELLOW}  $line${NC}"
            done
        else
            log_success "日志中未发现明显错误"
        fi
        
    else
        log_issue "critical" "日志文件不存在: $log_file"
    fi
    
    echo ""
}

# 函数：检查网络连接
check_network() {
    echo -e "${PURPLE}${BOLD}=== 网络连接检查 ===${NC}"
    
    # 检查基本网络连接
    if ping -c 1 8.8.8.8 >/dev/null 2>&1; then
        log_success "基本网络连接正常"
    else
        log_issue "critical" "网络连接异常"
    fi
    
    # 检查 Lighter API 连接（如果有公开的健康检查端点）
    # 注意：这里需要根据 Lighter 的实际 API 端点进行调整
    echo -e "${CYAN}注意: Lighter API 连接检查需要根据实际 API 端点配置${NC}"
    
    echo ""
}

# 函数：检查系统资源
check_system_resources() {
    echo -e "${PURPLE}${BOLD}=== 系统资源检查 ===${NC}"
    
    # 检查磁盘空间
    local disk_usage=$(df -h . | awk 'NR==2 {print $5}' | sed 's/%//')
    if [ $disk_usage -lt 90 ]; then
        log_success "磁盘空间充足 (已使用 ${disk_usage}%)"
    else
        log_issue "warning" "磁盘空间不足 (已使用 ${disk_usage}%)"
    fi
    
    # 检查内存使用
    if command -v free >/dev/null 2>&1; then
        local mem_usage=$(free | awk 'NR==2{printf "%.0f", $3*100/$2}')
        if [ $mem_usage -lt 90 ]; then
            log_success "内存使用正常 (${mem_usage}%)"
        else
            log_issue "warning" "内存使用较高 (${mem_usage}%)"
        fi
    elif command -v vm_stat >/dev/null 2>&1; then
        # macOS 系统
        log_success "系统资源检查 (macOS)"
    fi
    
    # 检查负载
    if command -v uptime >/dev/null 2>&1; then
        local load_avg=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1}' | sed 's/,//')
        echo -e "${CYAN}系统负载: $load_avg${NC}"
    fi
    
    echo ""
}

# 函数：显示总结
show_summary() {
    echo -e "${BLUE}${BOLD}================================================${NC}"
    echo -e "${BLUE}${BOLD}                检查总结${NC}"
    echo -e "${BLUE}${BOLD}================================================${NC}"
    
    if [ $CRITICAL_ISSUES -eq 0 ] && [ $TOTAL_ISSUES -eq 0 ]; then
        echo -e "${GREEN}${BOLD}🎉 Lighter 机器人状态良好，未发现问题！${NC}"
    elif [ $CRITICAL_ISSUES -eq 0 ]; then
        echo -e "${YELLOW}⚠️  发现 $TOTAL_ISSUES 个警告，但无严重问题${NC}"
    else
        echo -e "${RED}❌ 发现 $CRITICAL_ISSUES 个严重问题，$TOTAL_ISSUES 个总问题${NC}"
        echo -e "${RED}建议立即处理严重问题！${NC}"
    fi
    
    echo ""
    echo -e "${CYAN}常用命令:${NC}"
    echo -e "${BLUE}  查看实时日志: tail -f logs/$LIGHTER_LOG_FILE${NC}"
    echo -e "${BLUE}  启动机器人: ./scripts/start_lighter.sh${NC}"
    echo -e "${BLUE}  停止机器人: ./scripts/stop_lighter.sh${NC}"
    echo -e "${BLUE}  查看所有机器人: ./scripts/check_bots.sh${NC}"
    echo ""
}

# 函数：快速检查模式
quick_check() {
    echo -e "${CYAN}快速检查模式${NC}"
    
    # 使用与主检查相同的方法
    LIGHTER_PROCESSES=$(ps aux | grep runbot.py | grep lighter | grep -v grep || true)
    if [ ! -z "$LIGHTER_PROCESSES" ]; then
        bot_count=$(echo "$LIGHTER_PROCESSES" | wc -l || echo "0")
        echo -e "${GREEN}✅ Lighter 机器人正在运行 ($bot_count 个进程)${NC}"
        
        # 检查最近日志
        local log_file="logs/$LIGHTER_LOG_FILE"
        if [ -f "$log_file" ]; then
            local last_modified=$(stat -f%m "$log_file" 2>/dev/null || stat -c%Y "$log_file" 2>/dev/null)
            local current_time=$(date +%s)
            local time_diff=$((current_time - last_modified))
            
            if [ $time_diff -lt 300 ]; then
                echo -e "${GREEN}✅ 日志活跃 (${time_diff}秒前更新)${NC}"
            else
                echo -e "${YELLOW}⚠️  日志可能不活跃 (${time_diff}秒前更新)${NC}"
            fi
        fi
    else
        echo -e "${RED}❌ Lighter 机器人未运行${NC}"
    fi
}

# 主函数
main() {
    # 检查命令行参数
    if [ "$1" = "--quick" ] || [ "$1" = "-q" ]; then
        quick_check
        exit 0
    fi
    
    show_header
    check_process_status
    check_configuration
    check_logs
    check_network
    check_system_resources
    show_summary
}

# 错误处理
set -e
trap 'echo -e "${RED}检查脚本执行出错${NC}"' ERR

# 显示帮助信息
if [ "$1" = "--help" ] || [ "$1" = "-h" ]; then
    echo "Lighter 交易机器人状态检查脚本"
    echo ""
    echo "用法:"
    echo "  $0                 完整检查"
    echo "  $0 --quick        快速检查"
    echo "  $0 --help         显示帮助"
    echo ""
    exit 0
fi

# 执行主函数
main "$@"