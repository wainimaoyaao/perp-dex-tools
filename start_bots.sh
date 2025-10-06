#!/bin/bash
# 交易机器人启动脚本
# 使用两个虚拟环境：env (通用) 和 para_env (Paradex专用)

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 启动交易机器人 ===${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo -e "${BLUE}工作目录: $SCRIPT_DIR${NC}"

# 检查虚拟环境是否存在
if [ ! -f "./env/bin/python3" ]; then
    echo -e "${RED}错误: 虚拟环境 'env' 不存在!${NC}"
    echo -e "${YELLOW}请运行: python3 -m venv env${NC}"
    exit 1
fi

if [ ! -f "./para_env/bin/python3" ]; then
    echo -e "${RED}错误: 虚拟环境 'para_env' 不存在!${NC}"
    echo -e "${YELLOW}请运行: python3 -m venv para_env${NC}"
    exit 1
fi

# 检查 .env 文件是否存在
if [ ! -f ".env" ]; then
    echo -e "${RED}警告: .env 文件不存在!${NC}"
    echo -e "${YELLOW}请确保已配置 API 密钥${NC}"
fi

echo -e "${YELLOW}启动 Paradex 交易机器人 (使用 para_env)...${NC}"

# 启动 Paradex 机器人 (使用 para_env)
nohup ./para_env/bin/python3 runbot.py \
    --exchange paradex \
    --ticker BTC \
    --quantity 0.002 \
    --take-profit 0.005 \
    --max-orders 20 \
    --wait-time 450 \
    --grid-step 0.1 \
    --enable-drawdown-monitor \
    > paradex_output.log 2>&1 &

PARADEX_PID=$!
echo -e "${CYAN}Paradex PID: $PARADEX_PID${NC}"

# 等待一秒确保进程启动
sleep 1

echo -e "${YELLOW}启动 GRVT 交易机器人 (使用 env)...${NC}"

# 启动 GRVT 机器人 (使用 env)
nohup ./env/bin/python3 runbot.py \
    --exchange grvt \
    --ticker BTC \
    --quantity 0.002 \
    --take-profit 0.005 \
    --max-orders 20 \
    --wait-time 450 \
    --grid-step 0.1 \
    --enable-drawdown-monitor \
    > grvt_output.log 2>&1 &

GRVT_PID=$!
echo -e "${CYAN}GRVT PID: $GRVT_PID${NC}"

# 等待进程启动
sleep 3

echo -e "\n${GREEN}=== 运行状态检查 ===${NC}"

# 检查进程是否还在运行
if ps -p $PARADEX_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Paradex 机器人运行中 (PID: $PARADEX_PID)${NC}"
else
    echo -e "${RED}❌ Paradex 机器人启动失败${NC}"
    echo -e "${YELLOW}检查日志: tail -f paradex_output.log${NC}"
fi

if ps -p $GRVT_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ GRVT 机器人运行中 (PID: $GRVT_PID)${NC}"
else
    echo -e "${RED}❌ GRVT 机器人启动失败${NC}"
    echo -e "${YELLOW}检查日志: tail -f grvt_output.log${NC}"
fi

# 显示所有运行中的 runbot.py 进程
echo -e "\n${GREEN}=== 所有运行中的交易机器人 ===${NC}"
RUNNING_BOTS=$(ps aux | grep runbot.py | grep -v grep)
if [ -n "$RUNNING_BOTS" ]; then
    echo "$RUNNING_BOTS"
else
    echo -e "${RED}未发现运行中的交易机器人${NC}"
fi

echo -e "\n${GREEN}=== 日志文件 ===${NC}"
echo -e "${CYAN}Paradex 输出: paradex_output.log${NC}"
echo -e "${CYAN}GRVT 输出: grvt_output.log${NC}"

echo -e "\n${GREEN}=== 监控命令 ===${NC}"
echo -e "${YELLOW}实时监控 Paradex 日志:${NC} tail -f paradex_output.log"
echo -e "${YELLOW}实时监控 GRVT 日志:${NC} tail -f grvt_output.log"
echo -e "${YELLOW}同时监控两个日志:${NC} tail -f paradex_output.log grvt_output.log"
echo -e "${YELLOW}检查机器人状态:${NC} ./check_bots.sh"
echo -e "${YELLOW}停止所有机器人:${NC} ./stop_bots.sh"

# 保存 PID 到文件以便后续管理
echo "$PARADEX_PID" > .paradex_pid
echo "$GRVT_PID" > .grvt_pid

echo -e "\n${GREEN}交易机器人启动完成!${NC}"