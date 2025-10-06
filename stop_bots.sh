#!/bin/bash
# 交易机器人停止脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${RED}=== 停止交易机器人 ===${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 函数：优雅停止进程
graceful_stop() {
    local pid=$1
    local name=$2
    
    if [ -n "$pid" ] && ps -p "$pid" > /dev/null 2>&1; then
        echo -e "${YELLOW}停止 $name (PID: $pid)...${NC}"
        kill "$pid"
        
        # 等待进程结束
        local count=0
        while ps -p "$pid" > /dev/null 2>&1 && [ $count -lt 10 ]; do
            sleep 1
            count=$((count + 1))
        done
        
        # 如果进程仍在运行，强制终止
        if ps -p "$pid" > /dev/null 2>&1; then
            echo -e "${RED}强制终止 $name (PID: $pid)${NC}"
            kill -9 "$pid"
        else
            echo -e "${GREEN}✅ $name 已停止${NC}"
        fi
    else
        echo -e "${YELLOW}$name 未运行或PID无效${NC}"
    fi
}

# 从PID文件停止机器人
if [ -f ".paradex_pid" ]; then
    PARADEX_PID=$(cat .paradex_pid)
    graceful_stop "$PARADEX_PID" "Paradex 机器人"
    rm -f .paradex_pid
fi

if [ -f ".grvt_pid" ]; then
    GRVT_PID=$(cat .grvt_pid)
    graceful_stop "$GRVT_PID" "GRVT 机器人"
    rm -f .grvt_pid
fi

# 查找并停止所有 runbot.py 进程
echo -e "\n${YELLOW}查找所有运行中的 runbot.py 进程...${NC}"
PIDS=$(ps aux | grep runbot.py | grep -v grep | awk '{print $2}')

if [ -z "$PIDS" ]; then
    echo -e "${GREEN}✅ 没有发现运行中的交易机器人${NC}"
else
    echo -e "${YELLOW}发现运行中的机器人 PIDs: $PIDS${NC}"
    
    for PID in $PIDS; do
        # 获取进程命令行信息
        CMDLINE=$(ps -p "$PID" -o cmd --no-headers 2>/dev/null)
        
        if [[ "$CMDLINE" == *"runbot.py"* ]]; then
            if [[ "$CMDLINE" == *"paradex"* ]]; then
                graceful_stop "$PID" "Paradex 机器人"
            elif [[ "$CMDLINE" == *"grvt"* ]]; then
                graceful_stop "$PID" "GRVT 机器人"
            else
                graceful_stop "$PID" "交易机器人"
            fi
        fi
    done
fi

# 最终检查
sleep 2
echo -e "\n${GREEN}=== 最终状态检查 ===${NC}"

REMAINING=$(ps aux | grep runbot.py | grep -v grep)
if [ -z "$REMAINING" ]; then
    echo -e "${GREEN}✅ 所有交易机器人已成功停止${NC}"
else
    echo -e "${RED}❌ 仍有进程在运行:${NC}"
    echo "$REMAINING"
    echo -e "\n${YELLOW}如需强制停止，请运行:${NC}"
    echo "pkill -f runbot.py"
fi

# 显示日志文件大小
echo -e "\n${GREEN}=== 日志文件信息 ===${NC}"
if [ -f "paradex_output.log" ]; then
    SIZE=$(du -h paradex_output.log | cut -f1)
    echo -e "${CYAN}Paradex 日志: paradex_output.log ($SIZE)${NC}"
fi

if [ -f "grvt_output.log" ]; then
    SIZE=$(du -h grvt_output.log | cut -f1)
    echo -e "${CYAN}GRVT 日志: grvt_output.log ($SIZE)${NC}"
fi

echo -e "\n${GREEN}停止操作完成!${NC}"