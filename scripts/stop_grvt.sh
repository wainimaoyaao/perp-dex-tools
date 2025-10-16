#!/bin/bash
# GRVT 交易机器人停止脚本
# 功能：安全停止 GRVT 交易机器人

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

echo -e "${RED}${BOLD}=== GRVT 交易机器人停止脚本 ===${NC}"
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
    echo "[$timestamp] [$level] $message" >> logs/stop_grvt.log
}

# 检查 GRVT 机器人进程
check_grvt_processes() {
    log_action "INFO" "检查 GRVT 机器人进程..."
    
    # 查找包含 "grvt" 的 runbot.py 进程
    GRVT_PIDS=$(pgrep -f "runbot.py.*grvt" 2>/dev/null)
    
    # 如果启用了对冲功能，也检查对冲相关进程
    if [ "$GRVT_ENABLE_HEDGE" = "true" ]; then
        log_action "INFO" "对冲功能已启用，检查对冲相关进程..."
        # 查找可能的对冲进程（基于对冲交易所）
        HEDGE_PIDS=$(pgrep -f "runbot.py.*${GRVT_HEDGE_EXCHANGE}" 2>/dev/null)
        if [ -n "$HEDGE_PIDS" ]; then
            log_action "INFO" "发现对冲相关进程: $HEDGE_PIDS"
            # 将对冲进程PID添加到GRVT_PIDS中
            GRVT_PIDS="$GRVT_PIDS $HEDGE_PIDS"
        fi
    fi
    
    if [ -z "$GRVT_PIDS" ]; then
        log_action "INFO" "未发现运行中的 GRVT 机器人进程"
        return 1
    else
        log_action "INFO" "发现 GRVT 相关进程: $GRVT_PIDS"
        return 0
    fi
}

# 优雅停止 GRVT 机器人
graceful_stop_grvt() {
    log_action "INFO" "开始优雅停止 GRVT 机器人..."
    
    local pids=$1
    local stopped_count=0
    
    for pid in $pids; do
        if kill -TERM "$pid" 2>/dev/null; then
            log_action "INFO" "向进程 $pid 发送 SIGTERM 信号"
            
            # 等待进程优雅退出 (最多30秒)
            local wait_count=0
            while [ $wait_count -lt 30 ]; do
                if ! kill -0 "$pid" 2>/dev/null; then
                    log_action "SUCCESS" "进程 $pid 已优雅停止"
                    ((stopped_count++))
                    break
                fi
                sleep 1
                ((wait_count++))
            done
            
            # 如果进程仍在运行，强制终止
            if kill -0 "$pid" 2>/dev/null; then
                log_action "WARNING" "进程 $pid 未在30秒内停止，强制终止..."
                if kill -KILL "$pid" 2>/dev/null; then
                    log_action "SUCCESS" "进程 $pid 已强制终止"
                    ((stopped_count++))
                else
                    log_action "ERROR" "无法终止进程 $pid"
                fi
            fi
        else
            log_action "ERROR" "无法向进程 $pid 发送停止信号"
        fi
    done
    
    return $stopped_count
}

# 清理 PID 文件
cleanup_pid_files() {
    log_action "INFO" "清理 GRVT PID 文件..."
    
    if [ -f "grvt_bot.pid" ]; then
        rm -f "grvt_bot.pid"
        log_action "SUCCESS" "已删除 grvt_bot.pid"
    fi
}

# 显示日志文件信息
show_log_info() {
    log_action "INFO" "GRVT 日志文件信息:"
    
    if [ -f "$GRVT_LOG_FILE" ]; then
        local log_size=$(du -h "$GRVT_LOG_FILE" | cut -f1)
        local last_modified=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$GRVT_LOG_FILE" 2>/dev/null || stat -c "%y" "$GRVT_LOG_FILE" 2>/dev/null | cut -d'.' -f1)
        echo -e "${CYAN}  日志文件: $GRVT_LOG_FILE${NC}"
        echo -e "${CYAN}  文件大小: $log_size${NC}"
        echo -e "${CYAN}  最后修改: $last_modified${NC}"
        
        # 显示最后几行日志
        echo -e "${YELLOW}最后10行日志:${NC}"
        tail -10 "$GRVT_LOG_FILE" | while read line; do
            echo -e "${BLUE}  $line${NC}"
        done
    else
        log_action "WARNING" "日志文件 $GRVT_LOG_FILE 不存在"
    fi
}

# 主停止流程
main() {
    echo -e "${YELLOW}正在停止 GRVT 交易机器人...${NC}"
    
    # 检查进程
    if ! check_grvt_processes; then
        echo -e "${GREEN}GRVT 机器人未在运行${NC}"
        cleanup_pid_files
        exit 0
    fi
    
    # 获取进程ID
    GRVT_PIDS=$(pgrep -f "runbot.py.*grvt" 2>/dev/null)
    
    # 显示将要停止的进程
    echo -e "${YELLOW}将要停止的 GRVT 相关进程:${NC}"
    for pid in $GRVT_PIDS; do
        cmd=$(ps -p "$pid" -o command= 2>/dev/null)
        if echo "$cmd" | grep -q "grvt"; then
            echo -e "${CYAN}  PID: $pid - [主进程] $cmd${NC}"
        elif [ "$GRVT_ENABLE_HEDGE" = "true" ] && echo "$cmd" | grep -q "$GRVT_HEDGE_EXCHANGE"; then
            echo -e "${CYAN}  PID: $pid - [对冲进程] $cmd${NC}"
        else
            echo -e "${CYAN}  PID: $pid - $cmd${NC}"
        fi
    done
    
    # 询问用户确认
    echo -e "${YELLOW}确认停止 GRVT 机器人? (y/N):${NC}"
    read -r confirmation
    
    if [[ ! "$confirmation" =~ ^[Yy]$ ]]; then
        log_action "INFO" "用户取消停止操作"
        exit 0
    fi
    
    # 执行停止
    graceful_stop_grvt "$GRVT_PIDS"
    local stopped_count=$?
    
    # 清理文件
    cleanup_pid_files
    
    # 最终检查
    sleep 2
    if check_grvt_processes; then
        log_action "ERROR" "仍有 GRVT 相关进程在运行"
        echo -e "${RED}停止失败！仍有进程在运行${NC}"
        exit 1
    else
        log_action "SUCCESS" "所有 GRVT 相关进程已成功停止"
        if [ "$GRVT_ENABLE_HEDGE" = "true" ]; then
            echo -e "${GREEN}✅ GRVT 机器人及对冲进程已成功停止${NC}"
        else
            echo -e "${GREEN}✅ GRVT 机器人已成功停止${NC}"
        fi
    fi
    
    # 显示日志信息
    echo ""
    show_log_info
    
    # 显示管理命令
    echo ""
    echo -e "${CYAN}${BOLD}管理命令:${NC}"
    echo -e "${YELLOW}  启动 GRVT:        ./scripts/start_grvt.sh${NC}"
    echo -e "${YELLOW}  查看日志:         tail -f $GRVT_LOG_FILE${NC}"
    echo -e "${YELLOW}  检查进程:         pgrep -f 'runbot.py.*grvt'${NC}"
    echo -e "${YELLOW}  查看配置:         cat scripts/bot_configs.sh | grep GRVT${NC}"
    
    echo ""
    echo -e "${GREEN}${BOLD}GRVT 停止操作完成！${NC}"
}

# 执行主函数
main "$@"