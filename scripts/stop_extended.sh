#!/bin/bash
# Extended (X10) 交易机器人停止脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 获取项目根目录（脚本所在目录的上级目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 加载配置文件
source ./scripts/bot_configs.sh

echo -e "${RED}=== 停止 Extended (X10) 交易机器人 ===${NC}"
echo -e "${BLUE}停止时间: $(date)${NC}"

# 函数：记录操作
log_action() {
    echo -e "${CYAN}[$(date '+%Y-%m-%d %H:%M:%S')] $1${NC}"
}

# 检查是否有运行中的 Extended 机器人
log_action "检查运行中的 Extended 机器人进程..."

# 通过进程名查找
EXTENDED_PROCESSES=$(ps aux | grep "runbot.py.*extended" | grep -v grep)

# 通过 PID 文件查找
EXTENDED_PID=""
if [ -f ".extended_pid" ]; then
    EXTENDED_PID=$(cat .extended_pid)
    if ! ps -p "$EXTENDED_PID" > /dev/null 2>&1; then
        log_action "PID 文件中的进程 $EXTENDED_PID 已不存在，清理 PID 文件"
        rm -f .extended_pid
        EXTENDED_PID=""
    fi
fi

# 如果没有找到运行中的进程
if [ -z "$EXTENDED_PROCESSES" ] && [ -z "$EXTENDED_PID" ]; then
    echo -e "${YELLOW}⚠️  未找到运行中的 Extended 机器人${NC}"
    
    # 清理可能存在的 PID 文件
    if [ -f ".extended_pid" ]; then
        rm -f .extended_pid
        log_action "清理过期的 PID 文件"
    fi
    
    echo -e "${GREEN}✅ Extended 机器人已停止${NC}"
    exit 0
fi

# 显示找到的进程
if [ -n "$EXTENDED_PROCESSES" ]; then
    echo -e "${YELLOW}找到以下 Extended 机器人进程:${NC}"
    echo "$EXTENDED_PROCESSES"
fi

if [ -n "$EXTENDED_PID" ]; then
    echo -e "${YELLOW}PID 文件中的进程: $EXTENDED_PID${NC}"
fi

# 确认停止
echo -e "${YELLOW}确认停止 Extended 机器人? (Y/n): ${NC}"
read -r user_input
if [[ "$user_input" =~ ^[Nn]$ ]]; then
    echo -e "${CYAN}取消停止操作${NC}"
    exit 0
fi

# 停止进程
log_action "正在停止 Extended 机器人..."

# 优雅停止（SIGTERM）
if [ -n "$EXTENDED_PID" ]; then
    log_action "发送 SIGTERM 信号到进程 $EXTENDED_PID"
    kill "$EXTENDED_PID" 2>/dev/null
fi

# 通过进程名停止
pkill -f "runbot.py.*extended" 2>/dev/null

# 等待进程停止
log_action "等待进程停止..."
sleep 3

# 检查是否还有残留进程
REMAINING_PROCESSES=$(ps aux | grep "runbot.py.*extended" | grep -v grep)
if [ -n "$REMAINING_PROCESSES" ]; then
    log_action "发现残留进程，强制停止..."
    pkill -9 -f "runbot.py.*extended" 2>/dev/null
    sleep 2
fi

# 最终检查
FINAL_CHECK=$(ps aux | grep "runbot.py.*extended" | grep -v grep)
if [ -z "$FINAL_CHECK" ]; then
    echo -e "${GREEN}✅ Extended 机器人已成功停止${NC}"
    
    # 清理 PID 文件
    if [ -f ".extended_pid" ]; then
        rm -f .extended_pid
        log_action "清理 PID 文件"
    fi
    
    # 显示最后的日志信息
    if [ -f "$EXTENDED_LOG_FILE" ]; then
        echo -e "\n${CYAN}最后的日志信息:${NC}"
        tail -5 "$EXTENDED_LOG_FILE"
    fi
    
else
    echo -e "${RED}❌ 部分 Extended 进程可能仍在运行${NC}"
    echo "$FINAL_CHECK"
    echo -e "${YELLOW}请手动检查并停止残留进程${NC}"
    exit 1
fi

echo -e "\n${GREEN}=== 停止完成 ===${NC}"
echo -e "${BLUE}完成时间: $(date)${NC}"
echo -e "${CYAN}日志文件: $EXTENDED_LOG_FILE${NC}"