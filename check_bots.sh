#!/bin/bash
# 交易机器人状态检查脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${GREEN}=== 交易机器人状态检查 ===${NC}"
echo -e "${BLUE}检查时间: $(date)${NC}"
echo -e "${BLUE}工作目录: $SCRIPT_DIR${NC}"

# 检查虚拟环境状态
echo -e "\n${GREEN}=== 虚拟环境状态 ===${NC}"
if [ -d "./env" ]; then
    echo -e "${GREEN}✅ env 虚拟环境存在${NC}"
    if [ -f "./env/bin/python3" ]; then
        ENV_PYTHON_VERSION=$(./env/bin/python3 --version 2>&1)
        echo -e "${CYAN}   Python 版本: $ENV_PYTHON_VERSION${NC}"
    fi
else
    echo -e "${RED}❌ env 虚拟环境不存在${NC}"
fi

if [ -d "./para_env" ]; then
    echo -e "${GREEN}✅ para_env 虚拟环境存在${NC}"
    if [ -f "./para_env/bin/python3" ]; then
        PARA_PYTHON_VERSION=$(./para_env/bin/python3 --version 2>&1)
        echo -e "${CYAN}   Python 版本: $PARA_PYTHON_VERSION${NC}"
    fi
else
    echo -e "${RED}❌ para_env 虚拟环境不存在${NC}"
fi

# 检查配置文件
echo -e "\n${GREEN}=== 配置文件状态 ===${NC}"
if [ -f ".env" ]; then
    echo -e "${GREEN}✅ .env 配置文件存在${NC}"
    # 检查关键配置项（不显示具体值）
    if grep -q "PARADEX_" .env; then
        echo -e "${CYAN}   包含 Paradex 配置${NC}"
    fi
    if grep -q "GRVT_" .env; then
        echo -e "${CYAN}   包含 GRVT 配置${NC}"
    fi
else
    echo -e "${RED}❌ .env 配置文件不存在${NC}"
fi

# 检查运行中的进程
echo -e "\n${GREEN}=== 运行中的交易机器人 ===${NC}"
RUNNING_PROCESSES=$(ps aux | grep runbot.py | grep -v grep)

if [ -z "$RUNNING_PROCESSES" ]; then
    echo -e "${RED}❌ 没有运行中的交易机器人${NC}"
else
    echo -e "${GREEN}✅ 发现运行中的交易机器人:${NC}"
    echo "$RUNNING_PROCESSES" | while read -r line; do
        PID=$(echo "$line" | awk '{print $2}')
        CMD=$(echo "$line" | awk '{for(i=11;i<=NF;i++) printf "%s ", $i; print ""}')
        
        if [[ "$CMD" == *"paradex"* ]]; then
            echo -e "${CYAN}   🔹 Paradex (PID: $PID)${NC}"
        elif [[ "$CMD" == *"grvt"* ]]; then
            echo -e "${CYAN}   🔹 GRVT (PID: $PID)${NC}"
        else
            echo -e "${CYAN}   🔹 未知交易所 (PID: $PID)${NC}"
        fi
    done
fi

# 检查PID文件
echo -e "\n${GREEN}=== PID 文件状态 ===${NC}"
if [ -f ".paradex_pid" ]; then
    PARADEX_PID=$(cat .paradex_pid)
    if ps -p "$PARADEX_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ Paradex PID 文件有效 (PID: $PARADEX_PID)${NC}"
    else
        echo -e "${YELLOW}⚠️  Paradex PID 文件存在但进程不在运行 (PID: $PARADEX_PID)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  Paradex PID 文件不存在${NC}"
fi

if [ -f ".grvt_pid" ]; then
    GRVT_PID=$(cat .grvt_pid)
    if ps -p "$GRVT_PID" > /dev/null 2>&1; then
        echo -e "${GREEN}✅ GRVT PID 文件有效 (PID: $GRVT_PID)${NC}"
    else
        echo -e "${YELLOW}⚠️  GRVT PID 文件存在但进程不在运行 (PID: $GRVT_PID)${NC}"
    fi
else
    echo -e "${YELLOW}⚠️  GRVT PID 文件不存在${NC}"
fi

# 检查日志文件
echo -e "\n${GREEN}=== 日志文件状态 ===${NC}"
for log_file in "paradex_output.log" "grvt_output.log"; do
    if [ -f "$log_file" ]; then
        SIZE=$(du -h "$log_file" | cut -f1)
        LINES=$(wc -l < "$log_file")
        MODIFIED=$(stat -c %y "$log_file" | cut -d'.' -f1)
        echo -e "${GREEN}✅ $log_file${NC}"
        echo -e "${CYAN}   大小: $SIZE, 行数: $LINES, 修改时间: $MODIFIED${NC}"
        
        # 检查最近的错误
        ERROR_COUNT=$(grep -i "error\|exception\|failed" "$log_file" | tail -5 | wc -l)
        if [ "$ERROR_COUNT" -gt 0 ]; then
            echo -e "${RED}   ⚠️  最近发现 $ERROR_COUNT 个错误${NC}"
        fi
    else
        echo -e "${YELLOW}⚠️  $log_file 不存在${NC}"
    fi
done

# 显示最近的日志条目
echo -e "\n${GREEN}=== 最近的日志条目 ===${NC}"
for log_file in "paradex_output.log" "grvt_output.log"; do
    if [ -f "$log_file" ]; then
        echo -e "\n${PURPLE}📊 $log_file (最后 3 行):${NC}"
        tail -3 "$log_file" | sed 's/^/   /'
    fi
done

# 系统资源使用情况
echo -e "\n${GREEN}=== 系统资源使用 ===${NC}"
if command -v free >/dev/null 2>&1; then
    MEMORY_USAGE=$(free -h | grep '^Mem:' | awk '{print $3"/"$2}')
    echo -e "${CYAN}内存使用: $MEMORY_USAGE${NC}"
fi

if command -v df >/dev/null 2>&1; then
    DISK_USAGE=$(df -h . | tail -1 | awk '{print $3"/"$2" ("$5")"}')
    echo -e "${CYAN}磁盘使用: $DISK_USAGE${NC}"
fi

# 网络连接检查
echo -e "\n${GREEN}=== 网络连接检查 ===${NC}"
if command -v ping >/dev/null 2>&1; then
    if ping -c 1 google.com >/dev/null 2>&1; then
        echo -e "${GREEN}✅ 网络连接正常${NC}"
    else
        echo -e "${RED}❌ 网络连接异常${NC}"
    fi
fi

# 快捷操作提示
echo -e "\n${GREEN}=== 快捷操作 ===${NC}"
echo -e "${YELLOW}启动机器人:${NC} ./start_bots.sh"
echo -e "${YELLOW}停止机器人:${NC} ./stop_bots.sh"
echo -e "${YELLOW}实时监控 Paradex:${NC} tail -f paradex_output.log"
echo -e "${YELLOW}实时监控 GRVT:${NC} tail -f grvt_output.log"
echo -e "${YELLOW}查看错误日志:${NC} grep -i error *.log"

echo -e "\n${GREEN}状态检查完成!${NC}"