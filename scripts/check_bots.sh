#!/bin/bash
# 交易机器人状态检查脚本
# 版本: 2.1
# 功能: 全面检查交易机器人运行状态、配置、日志和系统资源
# 支持独立交易所检查功能

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

# 函数：显示使用说明
show_usage() {
    echo -e "${BOLD}${GREEN}交易机器人状态检查脚本 v2.1${NC}"
    echo -e "${CYAN}用法: $0 [选项]${NC}"
    echo ""
    echo -e "${YELLOW}选项:${NC}"
    echo -e "  ${GREEN}--paradex${NC}     仅检查 Paradex 交易机器人状态"
    echo -e "  ${GREEN}--grvt${NC}        仅检查 GRVT 交易机器人状态"
    echo -e "  ${GREEN}--help${NC}        显示此帮助信息"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo -e "  ${CYAN}$0${NC}            检查所有交易机器人"
    echo -e "  ${CYAN}$0 --paradex${NC}  仅检查 Paradex"
    echo -e "  ${CYAN}$0 --grvt${NC}     仅检查 GRVT"
    echo ""
    echo -e "${YELLOW}独立检查脚本:${NC}"
    echo -e "  ${CYAN}./scripts/check_paradex.sh${NC}  专门检查 Paradex"
    echo -e "  ${CYAN}./scripts/check_grvt.sh${NC}     专门检查 GRVT"
}

# 处理命令行参数
case "$1" in
    --paradex)
        echo -e "${BOLD}${GREEN}=== 调用独立 Paradex 检查脚本 ===${NC}"
        if [ -f "./scripts/check_paradex.sh" ]; then
            chmod +x ./scripts/check_paradex.sh
            ./scripts/check_paradex.sh
        else
            echo -e "${RED}错误: check_paradex.sh 脚本不存在${NC}"
            exit 1
        fi
        exit 0
        ;;
    --grvt)
        echo -e "${BOLD}${GREEN}=== 调用独立 GRVT 检查脚本 ===${NC}"
        if [ -f "./scripts/check_grvt.sh" ]; then
            chmod +x ./scripts/check_grvt.sh
            ./scripts/check_grvt.sh
        else
            echo -e "${RED}错误: check_grvt.sh 脚本不存在${NC}"
            exit 1
        fi
        exit 0
        ;;
    --help|-h)
        show_usage
        exit 0
        ;;
    "")
        # 无参数，继续执行完整检查
        ;;
    *)
        echo -e "${RED}错误: 未知参数 '$1'${NC}"
        echo ""
        show_usage
        exit 1
        ;;
esac

# 全局变量
TOTAL_ISSUES=0
CRITICAL_ISSUES=0

# 函数：记录问题
log_issue() {
    local severity=$1
    local message=$2
    
    TOTAL_ISSUES=$((TOTAL_ISSUES + 1))
    if [ "$severity" = "critical" ]; then
        CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
        echo -e "${RED}❌ [严重] $message${NC}"
    elif [ "$severity" = "warning" ]; then
        echo -e "${YELLOW}⚠️  [警告] $message${NC}"
    else
        echo -e "${CYAN}ℹ️  [信息] $message${NC}"
    fi
}

# 函数：显示成功状态
log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

# 函数：检查进程详细信息
check_process_details() {
    local pid=$1
    local exchange=$2
    
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

echo -e "${BOLD}${GREEN}=== 交易机器人状态检查 ===${NC}"
echo -e "${BLUE}检查时间: $(date)${NC}"
echo -e "${BLUE}工作目录: $SCRIPT_DIR${NC}"
echo -e "${BLUE}脚本版本: 2.0${NC}"

# 检查虚拟环境状态
echo -e "\n${BOLD}${GREEN}=== 虚拟环境状态 ===${NC}"

# 检查 env 虚拟环境
if [ -d "./env" ]; then
    log_success "env 虚拟环境存在"
    if [ -f "./env/bin/python3" ]; then
        ENV_PYTHON_VERSION=$(./env/bin/python3 --version 2>&1)
        echo -e "${CYAN}   Python 版本: $ENV_PYTHON_VERSION${NC}"
        
        # 检查关键依赖
        if [ -f "./requirements.txt" ]; then
            local missing_deps=$(./env/bin/python3 -m pip check 2>&1 | grep -c "No broken requirements found" || echo "0")
            if [ "$missing_deps" -eq 0 ]; then
                log_issue "warning" "env 环境可能存在依赖问题"
            else
                echo -e "${CYAN}   依赖状态: 正常${NC}"
            fi
        fi
    else
        log_issue "critical" "env 环境中缺少 Python 解释器"
    fi
else
    log_issue "critical" "env 虚拟环境不存在"
fi

# 检查 para_env 虚拟环境
if [ -d "./para_env" ]; then
    log_success "para_env 虚拟环境存在"
    if [ -f "./para_env/bin/python3" ]; then
        PARA_PYTHON_VERSION=$(./para_env/bin/python3 --version 2>&1)
        echo -e "${CYAN}   Python 版本: $PARA_PYTHON_VERSION${NC}"
        
        # 检查关键依赖
        if [ -f "./para_requirements.txt" ]; then
            local missing_deps=$(./para_env/bin/python3 -m pip check 2>&1 | grep -c "No broken requirements found" || echo "0")
            if [ "$missing_deps" -eq 0 ]; then
                log_issue "warning" "para_env 环境可能存在依赖问题"
            else
                echo -e "${CYAN}   依赖状态: 正常${NC}"
            fi
        fi
    else
        log_issue "critical" "para_env 环境中缺少 Python 解释器"
    fi
else
    log_issue "critical" "para_env 虚拟环境不存在"
fi

# 检查配置文件
echo -e "\n${BOLD}${GREEN}=== 配置文件状态 ===${NC}"
if [ -f ".env" ]; then
    log_success ".env 配置文件存在"
    
    # 检查关键配置项（不显示具体值）
    local paradex_configs=$(grep -c "PARADEX_" .env 2>/dev/null || echo "0")
    local grvt_configs=$(grep -c "GRVT_" .env 2>/dev/null || echo "0")
    
    if [ "$paradex_configs" -gt 0 ]; then
        echo -e "${CYAN}   Paradex 配置项: $paradex_configs 个${NC}"
    else
        log_issue "warning" "缺少 Paradex 配置"
    fi
    
    if [ "$grvt_configs" -gt 0 ]; then
        echo -e "${CYAN}   GRVT 配置项: $grvt_configs 个${NC}"
    else
        log_issue "warning" "缺少 GRVT 配置"
    fi
    
    # 检查配置文件权限
    local env_perms=$(stat -c "%a" .env 2>/dev/null || echo "unknown")
    if [ "$env_perms" != "600" ] && [ "$env_perms" != "unknown" ]; then
        log_issue "warning" ".env 文件权限不安全 ($env_perms)，建议设置为 600"
    fi
else
    log_issue "critical" ".env 配置文件不存在"
fi

# 检查运行中的进程
echo -e "\n${BOLD}${GREEN}=== 运行中的交易机器人 ===${NC}"
RUNNING_PROCESSES=$(ps aux | grep runbot.py | grep -v grep)

if [ -z "$RUNNING_PROCESSES" ]; then
    log_issue "critical" "没有运行中的交易机器人"
else
    local bot_count=$(echo "$RUNNING_PROCESSES" | wc -l)
    log_success "发现 $bot_count 个运行中的交易机器人"
    
    echo "$RUNNING_PROCESSES" | while read -r line; do
        PID=$(echo "$line" | awk '{print $2}')
        CMD=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf "%s ", $i; print ""}')
        
        if [[ "$CMD" == *"paradex"* ]]; then
            echo -e "${CYAN}   🔹 Paradex (PID: $PID)${NC}"
            check_process_details "$PID" "Paradex"
        elif [[ "$CMD" == *"grvt"* ]]; then
            echo -e "${CYAN}   🔹 GRVT (PID: $PID)${NC}"
            check_process_details "$PID" "GRVT"
        else
            echo -e "${CYAN}   🔹 未知交易所 (PID: $PID)${NC}"
            check_process_details "$PID" "Unknown"
        fi
        echo ""
    done
fi

# 检查PID文件
echo -e "\n${BOLD}${GREEN}=== PID 文件状态 ===${NC}"

# 函数：检查单个 PID 文件
check_pid_file() {
    local exchange=$1
    local pid_file=$2
    
    if [ -f "$pid_file" ]; then
        local pid=$(cat "$pid_file" 2>/dev/null)
        if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
            log_success "$exchange PID 文件有效 (PID: $pid)"
            check_process_details "$pid" "$exchange"
        else
            log_issue "warning" "$exchange PID 文件存在但进程不在运行 (PID: $pid)"
            echo -e "${YELLOW}   建议删除过期的 PID 文件: rm $pid_file${NC}"
        fi
    else
        log_issue "info" "$exchange PID 文件不存在"
    fi
}

check_pid_file "Paradex" ".paradex_pid"
check_pid_file "GRVT" ".grvt_pid"

# 检查日志文件
echo -e "\n${BOLD}${GREEN}=== 日志文件状态 ===${NC}"

# 函数：分析日志文件
analyze_log_file() {
    local log_file=$1
    local exchange=$(echo "$log_file" | cut -d'_' -f1)
    
    if [ -f "$log_file" ]; then
        local size=$(du -h "$log_file" | cut -f1)
        local lines=$(wc -l < "$log_file")
        local modified=$(stat -c %y "$log_file" 2>/dev/null | cut -d'.' -f1 || echo "未知")
        
        log_success "$log_file"
        echo -e "${CYAN}   大小: $size, 行数: $lines${NC}"
        echo -e "${CYAN}   修改时间: $modified${NC}"
        
        # 检查日志文件是否过大
        local size_mb=$(du -m "$log_file" | cut -f1)
        if [ "$size_mb" -gt 100 ]; then
            log_issue "warning" "$log_file 文件过大 (${size}MB)，建议清理"
        fi
        
        # 检查最近的错误
        local recent_errors=$(tail -100 "$log_file" | grep -i "error\|exception\|failed" | wc -l)
        if [ "$recent_errors" -gt 0 ]; then
            log_issue "warning" "$exchange 最近100行中发现 $recent_errors 个错误"
            echo -e "${YELLOW}   最新错误:${NC}"
            tail -100 "$log_file" | grep -i "error\|exception\|failed" | tail -3 | sed 's/^/     /'
        else
            echo -e "${CYAN}   ✅ 最近无错误记录${NC}"
        fi
        
        # 检查日志活跃度
        local last_log_time=$(tail -1 "$log_file" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\} [0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}' | head -1)
        if [ -n "$last_log_time" ]; then
            echo -e "${CYAN}   最后日志时间: $last_log_time${NC}"
        fi
        
    else
        log_issue "warning" "$log_file 不存在"
    fi
    echo ""
}

analyze_log_file "paradex_output.log"
analyze_log_file "grvt_output.log"

# 检查回撤监控状态
echo -e "\n${BOLD}${GREEN}=== 回撤监控状态 ===${NC}"

# 函数：分析回撤监控状态
analyze_drawdown_status() {
    local log_file=$1
    local exchange_name=$(echo "$log_file" | cut -d'_' -f1)
    
    if [ ! -f "$log_file" ]; then
        log_issue "warning" "$exchange_name 日志文件不存在，无法检查回撤状态"
        return
    fi
    
    echo -e "\n${CYAN}🛡️  $exchange_name 回撤监控:${NC}"
    
    # 检查回撤监控是否启用
    local monitor_enabled=$(tail -100 "$log_file" | grep -i "drawdown.*monitor.*enabled\|drawdown.*monitor.*initialized" | tail -1)
    if [ -n "$monitor_enabled" ]; then
        echo -e "${GREEN}   ✅ 回撤监控已启用${NC}"
        echo -e "${CYAN}   状态: $monitor_enabled${NC}"
    else
        log_issue "warning" "$exchange_name 未检测到回撤监控启用信息"
    fi
    
    # 检查当前回撤率
    local current_drawdown=$(tail -50 "$log_file" | grep -i "current.*drawdown.*%\|drawdown.*rate.*%" | tail -1)
    if [ -n "$current_drawdown" ]; then
        echo -e "${CYAN}   当前回撤: $current_drawdown${NC}"
        
        # 提取回撤百分比进行风险评估
        local drawdown_pct=$(echo "$current_drawdown" | grep -o '[0-9]\+\.[0-9]\+%\|[0-9]\+%' | head -1 | tr -d '%')
        if [ -n "$drawdown_pct" ]; then
            if (( $(echo "$drawdown_pct > 15" | bc -l 2>/dev/null || echo "0") )); then
                log_issue "critical" "$exchange_name 回撤率过高: ${drawdown_pct}%"
            elif (( $(echo "$drawdown_pct > 10" | bc -l 2>/dev/null || echo "0") )); then
                log_issue "warning" "$exchange_name 回撤率较高: ${drawdown_pct}%"
            fi
        fi
    else
        log_issue "info" "$exchange_name 未检测到当前回撤信息"
    fi
    
    # 检查警告级别
    local warning_level=$(tail -50 "$log_file" | grep -i "drawdown.*level.*changed\|warning.*level\|risk.*level" | tail -1)
    if [ -n "$warning_level" ]; then
        if [[ "$warning_level" == *"severe"* ]] || [[ "$warning_level" == *"critical"* ]]; then
            log_issue "critical" "$exchange_name 严重警告: $warning_level"
        elif [[ "$warning_level" == *"medium"* ]] || [[ "$warning_level" == *"moderate"* ]]; then
            log_issue "warning" "$exchange_name 中等警告: $warning_level"
        elif [[ "$warning_level" == *"light"* ]] || [[ "$warning_level" == *"low"* ]]; then
            echo -e "${CYAN}   ℹ️  轻度警告: $warning_level${NC}"
        else
            echo -e "${CYAN}   最新状态: $warning_level${NC}"
        fi
    else
        echo -e "${GREEN}   ✅ 无风险警告${NC}"
    fi
    
    # 检查止损执行历史
    local stop_loss_history=$(tail -100 "$log_file" | grep -i "stop.loss.*executed\|stop.loss.*filled\|auto.*stop.loss.*triggered" | tail -1)
    if [ -n "$stop_loss_history" ]; then
        echo -e "${PURPLE}   📋 最近止损: $stop_loss_history${NC}"
    fi
    
    # 检查是否正在执行止损
    local active_stop_loss=$(tail -20 "$log_file" | grep -i "executing.*stop.loss\|placing.*stop.loss\|stop.loss.*pending")
    if [ -n "$active_stop_loss" ]; then
        log_issue "critical" "$exchange_name 正在执行止损操作!"
        echo -e "${RED}   🔄 详情: $active_stop_loss${NC}"
    fi
    
    # 检查回撤监控配置
    local monitor_config=$(tail -100 "$log_file" | grep -i "drawdown.*threshold\|stop.loss.*threshold\|warning.*threshold" | tail -3)
    if [ -n "$monitor_config" ]; then
        echo -e "${CYAN}   配置信息:${NC}"
        echo "$monitor_config" | sed 's/^/     /'
    fi
}

analyze_drawdown_status "paradex_output.log"
analyze_drawdown_status "grvt_output.log"

# 显示最近的日志条目
echo -e "\n${BOLD}${GREEN}=== 最近的日志条目 ===${NC}"
for log_file in "paradex_output.log" "grvt_output.log"; do
    if [ -f "$log_file" ]; then
        local exchange=$(echo "$log_file" | cut -d'_' -f1)
        echo -e "\n${PURPLE}📊 $exchange 最新日志 (最后 3 行):${NC}"
        tail -3 "$log_file" | sed 's/^/   /' | head -3
    else
        log_issue "info" "$log_file 不存在，无法显示最新日志"
    fi
done

# 系统资源使用情况
echo -e "\n${BOLD}${GREEN}=== 系统资源使用 ===${NC}"

# 内存使用检查
if command -v free >/dev/null 2>&1; then
    local memory_info=$(free -h | grep '^Mem:')
    local memory_used=$(echo "$memory_info" | awk '{print $3}')
    local memory_total=$(echo "$memory_info" | awk '{print $2}')
    local memory_percent=$(echo "$memory_info" | awk '{print int($3/$2*100)}')
    
    echo -e "${CYAN}内存使用: $memory_used/$memory_total (${memory_percent}%)${NC}"
    
    if [ "$memory_percent" -gt 90 ]; then
        log_issue "critical" "内存使用率过高: ${memory_percent}%"
    elif [ "$memory_percent" -gt 80 ]; then
        log_issue "warning" "内存使用率较高: ${memory_percent}%"
    fi
else
    log_issue "info" "无法获取内存使用信息"
fi

# 磁盘使用检查
if command -v df >/dev/null 2>&1; then
    local disk_info=$(df -h . | tail -1)
    local disk_used=$(echo "$disk_info" | awk '{print $3}')
    local disk_total=$(echo "$disk_info" | awk '{print $2}')
    local disk_percent=$(echo "$disk_info" | awk '{print $5}' | tr -d '%')
    
    echo -e "${CYAN}磁盘使用: $disk_used/$disk_total (${disk_percent}%)${NC}"
    
    if [ "$disk_percent" -gt 90 ]; then
        log_issue "critical" "磁盘使用率过高: ${disk_percent}%"
    elif [ "$disk_percent" -gt 80 ]; then
        log_issue "warning" "磁盘使用率较高: ${disk_percent}%"
    fi
else
    log_issue "info" "无法获取磁盘使用信息"
fi

# 网络连接检查
echo -e "\n${BOLD}${GREEN}=== 网络连接检查 ===${NC}"
if command -v ping >/dev/null 2>&1; then
    if ping -c 1 -W 3 google.com >/dev/null 2>&1; then
        log_success "网络连接正常"
    else
        log_issue "warning" "网络连接异常，可能影响交易"
    fi
else
    log_issue "info" "无法执行网络连接测试"
fi

# 检查总结
echo -e "\n${BOLD}${GREEN}=== 检查总结 ===${NC}"
if [ $CRITICAL_ISSUES -eq 0 ] && [ $TOTAL_ISSUES -eq 0 ]; then
    echo -e "${GREEN}🎉 系统状态良好，未发现问题${NC}"
elif [ $CRITICAL_ISSUES -eq 0 ]; then
    echo -e "${YELLOW}⚠️  发现 $TOTAL_ISSUES 个非严重问题${NC}"
else
    echo -e "${RED}❌ 发现 $CRITICAL_ISSUES 个严重问题，总计 $TOTAL_ISSUES 个问题${NC}"
    echo -e "${RED}建议立即处理严重问题！${NC}"
fi

# 快捷操作提示
echo -e "\n${BOLD}${GREEN}=== 快捷操作 ===${NC}"
echo -e "${CYAN}=== 启动/停止操作 ===${NC}"
echo -e "${YELLOW}启动所有机器人:${NC} ./scripts/start_bots.sh"
echo -e "${YELLOW}启动 Paradex:${NC} ./scripts/start_paradex.sh"
echo -e "${YELLOW}启动 GRVT:${NC} ./scripts/start_grvt.sh"
echo -e "${YELLOW}停止所有机器人:${NC} ./scripts/stop_bots.sh"
echo -e "${YELLOW}停止 Paradex:${NC} ./scripts/stop_paradex.sh"
echo -e "${YELLOW}停止 GRVT:${NC} ./scripts/stop_grvt.sh"
echo ""
echo -e "${CYAN}=== 状态检查操作 ===${NC}"
echo -e "${YELLOW}检查所有机器人:${NC} ./scripts/check_bots.sh"
echo -e "${YELLOW}检查 Paradex:${NC} ./scripts/check_paradex.sh"
echo -e "${YELLOW}检查 GRVT:${NC} ./scripts/check_grvt.sh"
echo -e "${YELLOW}参数化检查 Paradex:${NC} ./scripts/check_bots.sh --paradex"
echo -e "${YELLOW}参数化检查 GRVT:${NC} ./scripts/check_bots.sh --grvt"
echo ""
echo -e "${CYAN}=== 日志监控操作 ===${NC}"
echo -e "${YELLOW}实时监控 Paradex:${NC} tail -f paradex_output.log"
echo -e "${YELLOW}实时监控 GRVT:${NC} tail -f grvt_output.log"
echo -e "${YELLOW}同时监控两个日志:${NC} tail -f paradex_output.log grvt_output.log"
echo -e "${YELLOW}查看错误日志:${NC} grep -i error *.log | tail -10"
echo -e "${YELLOW}清理过期PID文件:${NC} rm -f .*.pid"

echo -e "\n${BLUE}检查完成时间: $(date)${NC}"
echo -e "${GREEN}状态检查完成!${NC}"