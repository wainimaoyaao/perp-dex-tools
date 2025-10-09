#!/bin/bash
# GRVT 交易机器人状态检查脚本
# 功能：专门检查 GRVT 交易机器人的运行状态、配置和日志

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
    echo -e "${GREEN}✅ $1${NC}"
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

echo -e "${BOLD}${GREEN}=== GRVT 交易机器人状态检查 ===${NC}"
echo -e "${BLUE}检查时间: $(date)${NC}"
echo -e "${BLUE}工作目录: $SCRIPT_DIR${NC}"

# 检查 GRVT 虚拟环境
echo -e "\n${BOLD}${GREEN}=== GRVT 虚拟环境状态 ===${NC}"
if [ -d "$GRVT_ENV_PATH" ]; then
    log_success "GRVT 虚拟环境存在: $GRVT_ENV_PATH"
    if [ -f "$GRVT_ENV_PATH/bin/python3" ]; then
        PYTHON_VERSION=$($GRVT_ENV_PATH/bin/python3 --version 2>&1)
        echo -e "${CYAN}   Python 版本: $PYTHON_VERSION${NC}"
        
        # 检查关键依赖
        if [ -f "./grvt_requirements.txt" ]; then
            missing_deps=$($GRVT_ENV_PATH/bin/python3 -m pip check 2>&1 | grep -c "No broken requirements found" || echo "0")
            if [ -n "$missing_deps" ] && [ "$missing_deps" -eq 0 ]; then
                log_issue "warning" "GRVT 环境可能存在依赖问题"
            else
                echo -e "${CYAN}   依赖状态: 正常${NC}"
            fi
        fi
    else
        log_issue "critical" "GRVT 环境中缺少 Python 解释器"
    fi
else
    log_issue "critical" "GRVT 虚拟环境不存在: $GRVT_ENV_PATH"
fi

# 检查 GRVT 配置
echo -e "\n${BOLD}${GREEN}=== GRVT 配置状态 ===${NC}"
if [ -f "$GRVT_ENV_FILE" ]; then
    log_success "GRVT 环境文件存在: $GRVT_ENV_FILE"
    
    # 检查关键配置项（不显示具体值）
    grvt_configs=$(grep -c "GRVT_" "$GRVT_ENV_FILE" 2>/dev/null || echo "0")
    
    if [ "$grvt_configs" -gt 0 ]; then
        echo -e "${CYAN}   GRVT 配置项: $grvt_configs 个${NC}"
    else
        log_issue "warning" "环境文件中缺少 GRVT 配置"
    fi
    
    # 检查配置文件权限
    env_perms=$(stat -c "%a" "$GRVT_ENV_FILE" 2>/dev/null || echo "unknown")
    if [ "$env_perms" != "600" ] && [ "$env_perms" != "unknown" ]; then
        log_issue "warning" "环境文件权限不安全 ($env_perms)，建议设置为 600"
    fi
else
    log_issue "critical" "GRVT 环境文件不存在: $GRVT_ENV_FILE"
fi

# 显示当前配置（隐藏敏感信息）
echo -e "\n${CYAN}当前 GRVT 配置:${NC}"
echo -e "${CYAN}   交易对: $GRVT_TICKER${NC}"
echo -e "${CYAN}   数量: $GRVT_QUANTITY${NC}"
echo -e "${CYAN}   止盈: $GRVT_TAKE_PROFIT${NC}"
echo -e "${CYAN}   方向: $GRVT_DIRECTION${NC}"
echo -e "${CYAN}   最大订单: $GRVT_MAX_ORDERS${NC}"
echo -e "${CYAN}   等待时间: $GRVT_WAIT_TIME${NC}"
echo -e "${CYAN}   网格步长: $GRVT_GRID_STEP${NC}"
echo -e "${CYAN}   止损价格: $GRVT_STOP_PRICE${NC}"
echo -e "${CYAN}   暂停价格: $GRVT_PAUSE_PRICE${NC}"
echo -e "${CYAN}   Aster 加速: $GRVT_ASTER_BOOST${NC}"
echo -e "${CYAN}   回撤监控: $GRVT_ENABLE_DRAWDOWN_MONITOR${NC}"

# 检查运行中的 GRVT 进程
echo -e "\n${BOLD}${GREEN}=== GRVT 进程状态 ===${NC}"
GRVT_PROCESSES=$(ps aux | grep runbot.py | grep grvt | grep -v grep)

if [ -z "$GRVT_PROCESSES" ]; then
    log_issue "critical" "GRVT 交易机器人未在运行"
else
    bot_count=$(echo "$GRVT_PROCESSES" | wc -l)
    log_success "发现 $bot_count 个运行中的 GRVT 机器人"
    
    echo "$GRVT_PROCESSES" | while read -r line; do
        PID=$(echo "$line" | awk '{print $2}')
        CMD=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf "%s ", $i; print ""}')
        
        echo -e "${CYAN}   🔹 GRVT (PID: $PID)${NC}"
        check_process_details "$PID"
        echo ""
    done
fi

# 检查 GRVT PID 文件
echo -e "\n${BOLD}${GREEN}=== GRVT PID 文件状态 ===${NC}"
if [ -f ".grvt_pid" ]; then
    pid=$(cat .grvt_pid 2>/dev/null)
    if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
        log_success "GRVT PID 文件有效 (PID: $pid)"
        check_process_details "$pid"
    else
        log_issue "warning" "GRVT PID 文件存在但进程不在运行 (PID: $pid)"
        echo -e "${YELLOW}   建议删除过期的 PID 文件: rm .grvt_pid${NC}"
    fi
else
    log_issue "info" "GRVT PID 文件不存在"
fi

# 检查 GRVT 日志文件
echo -e "\n${BOLD}${GREEN}=== GRVT 日志状态 ===${NC}"

# 检查日志轮转状态（如果log_utils.sh可用）
if command -v analyze_log_rotation_status >/dev/null 2>&1; then
    echo -e "${CYAN}${BOLD}--- 日志轮转状态 ---${NC}"
    analyze_log_rotation_status "$GRVT_LOG_FILE"
    echo ""
fi

if [ -f "$GRVT_LOG_FILE" ]; then
    size=$(du -h "$GRVT_LOG_FILE" | cut -f1)
    lines=$(wc -l < "$GRVT_LOG_FILE")
    modified=$(stat -c %y "$GRVT_LOG_FILE" 2>/dev/null | cut -d'.' -f1 || echo "未知")
    
    log_success "$GRVT_LOG_FILE"
    echo -e "${CYAN}   大小: $size, 行数: $lines${NC}"
    echo -e "${CYAN}   修改时间: $modified${NC}"
    
    # 检查日志文件是否过大
    size_mb=$(du -m "$GRVT_LOG_FILE" | cut -f1)
    if [ -n "$size_mb" ]; then
        local max_size=${LOG_MAX_SIZE_MB:-50}
        if [ "$size_mb" -gt $max_size ]; then
            if [ "$LOG_ROTATION_ENABLED" = "true" ]; then
                log_issue "warning" "日志文件大小 (${size_mb}MB) 超过配置的最大值 (${max_size}MB)，将在下次启动时轮转"
            else
                log_issue "warning" "日志文件过大 (${size_mb}MB)，建议启用日志轮转或定期清理"
            fi
        fi
    fi
    
    # 检查最近的错误
    recent_errors=$(tail -100 "$GRVT_LOG_FILE" | grep -i "error\|exception\|failed" | wc -l)
    if [ -n "$recent_errors" ] && [ "$recent_errors" -gt 0 ]; then
        log_issue "warning" "最近100行中发现 $recent_errors 个错误"
        echo -e "${YELLOW}   最新错误:${NC}"
        tail -100 "$GRVT_LOG_FILE" | grep -i "error\|exception\|failed" | tail -3 | sed 's/^/     /'
    else
        echo -e "${CYAN}   ✅ 最近无错误记录${NC}"
    fi
    
    # 检查日志活跃度
    last_log_time=$(tail -1 "$GRVT_LOG_FILE" | grep -o '[0-9]\{4\}-[0-9]\{2\}-[0-9]\{2\} [0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}' | head -1)
    if [ -n "$last_log_time" ]; then
        echo -e "${CYAN}   最后日志时间: $last_log_time${NC}"
    fi
    
else
    log_issue "warning" "GRVT 日志文件不存在: $GRVT_LOG_FILE"
fi

# 检查 GRVT 回撤监控状态
echo -e "\n${BOLD}${GREEN}=== GRVT 回撤监控状态 ===${NC}"
if [ "$GRVT_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
    log_success "GRVT 回撤监控已启用"
    echo -e "${CYAN}   轻度阈值: ${GRVT_DRAWDOWN_LIGHT_THRESHOLD}%${NC}"
    echo -e "${CYAN}   中度阈值: ${GRVT_DRAWDOWN_MEDIUM_THRESHOLD}%${NC}"
    echo -e "${CYAN}   严重阈值: ${GRVT_DRAWDOWN_SEVERE_THRESHOLD}%${NC}"
    
    if [ -f "$GRVT_LOG_FILE" ]; then
        # 检查当前回撤率
        current_drawdown=$(tail -50 "$GRVT_LOG_FILE" | grep -i "current.*drawdown.*%\|drawdown.*rate.*%" | tail -1)
        if [ -n "$current_drawdown" ]; then
            echo -e "${CYAN}   当前回撤: $current_drawdown${NC}"
            
            drawdown_pct=$(echo "$current_drawdown" | grep -o '[0-9]\+\.[0-9]\+%\|[0-9]\+%' | head -1 | tr -d '%')
            if [ -n "$drawdown_pct" ]; then
                if (( $(echo "$drawdown_pct > 15" | bc -l 2>/dev/null || echo "0") )); then
                    log_issue "critical" "GRVT 回撤率过高: ${drawdown_pct}%"
                elif (( $(echo "$drawdown_pct > 10" | bc -l 2>/dev/null || echo "0") )); then
                    log_issue "warning" "GRVT 回撤率较高: ${drawdown_pct}%"
                fi
            fi
        else
            log_issue "info" "未检测到当前回撤信息"
        fi
        
        # 检查是否正在执行止损
        active_stop_loss=$(tail -20 "$GRVT_LOG_FILE" | grep -i "executing.*stop.loss\|placing.*stop.loss\|stop.loss.*pending")
        if [ -n "$active_stop_loss" ]; then
            log_issue "critical" "GRVT 正在执行止损操作!"
            echo -e "${RED}   🔄 详情: $active_stop_loss${NC}"
        fi
    fi
else
    log_issue "info" "GRVT 回撤监控未启用"
fi

# 显示最近的 GRVT 日志条目
echo -e "\n${BOLD}${GREEN}=== GRVT 最新日志 ===${NC}"
if [ -f "$GRVT_LOG_FILE" ]; then
    echo -e "${PURPLE}📊 最新日志 (最后 5 行):${NC}"
    tail -5 "$GRVT_LOG_FILE" | sed 's/^/   /'
else
    log_issue "info" "GRVT 日志文件不存在，无法显示最新日志"
fi

# 检查总结
echo -e "\n${BOLD}${GREEN}=== GRVT 检查总结 ===${NC}"
if [ $CRITICAL_ISSUES -eq 0 ] && [ $TOTAL_ISSUES -eq 0 ]; then
    echo -e "${GREEN}🎉 GRVT 状态良好，未发现问题${NC}"
elif [ $CRITICAL_ISSUES -eq 0 ]; then
    echo -e "${YELLOW}⚠️  GRVT 发现 $TOTAL_ISSUES 个非严重问题${NC}"
else
    echo -e "${RED}❌ GRVT 发现 $CRITICAL_ISSUES 个严重问题，总计 $TOTAL_ISSUES 个问题${NC}"
    echo -e "${RED}建议立即处理严重问题！${NC}"
fi

# GRVT 快捷操作提示
echo -e "\n${BOLD}${GREEN}=== GRVT 快捷操作 ===${NC}"
echo -e "${YELLOW}启动 GRVT:${NC} ./scripts/start_grvt.sh"
echo -e "${YELLOW}停止 GRVT:${NC} ./scripts/stop_grvt.sh"
echo -e "${YELLOW}重新检查 GRVT:${NC} ./scripts/check_grvt.sh"
echo -e "${YELLOW}实时监控日志:${NC} tail -f $GRVT_LOG_FILE"
echo -e "${YELLOW}查看错误日志:${NC} grep -i error $GRVT_LOG_FILE | tail -10"
echo -e "${YELLOW}清理 PID 文件:${NC} rm -f .grvt_pid"
echo -e "${YELLOW}编辑配置:${NC} nano scripts/bot_configs.sh"

echo -e "\n${BLUE}GRVT 检查完成时间: $(date)${NC}"
echo -e "${GREEN}GRVT 状态检查完成!${NC}"