#!/bin/bash
# GRVT 交易机器人启动脚本

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

echo -e "${GREEN}=== 启动 GRVT 交易机器人 ===${NC}"
echo -e "${BLUE}启动时间: $(date)${NC}"
echo -e "${BLUE}工作目录: $SCRIPT_DIR${NC}"

# 函数：检查并创建日志目录
setup_logging() {
    if [ ! -d "logs" ]; then
        mkdir -p logs
        echo -e "${CYAN}创建日志目录: logs/${NC}"
    fi
}

# 函数：检查虚拟环境
check_virtual_env() {
    if [ ! -f "$GRVT_ENV_PATH/bin/python3" ]; then
        echo -e "${RED}错误: GRVT 虚拟环境不存在!${NC}"
        echo -e "${YELLOW}请运行: python3 -m venv env${NC}"
        exit 1
    fi
    
    local python_version=$($GRVT_ENV_PATH/bin/python3 --version 2>&1)
    echo -e "${CYAN}✅ GRVT 环境: $python_version${NC}"
}

# 函数：检查依赖包
check_dependencies() {
    if [ -f "requirements.txt" ]; then
        echo -e "${CYAN}检查 GRVT 依赖包...${NC}"
        if ! $GRVT_ENV_PATH/bin/pip list --format=freeze > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  GRVT 依赖包检查失败${NC}"
        fi
    fi
}

# 设置日志
setup_logging

# 检查虚拟环境
echo -e "\n${GREEN}=== 环境检查 ===${NC}"
check_virtual_env

# 检查依赖包
check_dependencies

# 检查配置文件
echo -e "\n${GREEN}=== 配置检查 ===${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}错误: .env 文件不存在!${NC}"
    echo -e "${YELLOW}请复制 env_example.txt 为 .env 并配置 GRVT API 密钥${NC}"
    exit 1
fi

if ! grep -q "GRVT_" .env; then
    echo -e "${RED}错误: 未找到 GRVT 配置${NC}"
    exit 1
fi

echo -e "${GREEN}✅ GRVT 配置检查完成${NC}"

# 检查是否已有运行中的 GRVT 机器人
echo -e "\n${GREEN}=== 进程检查 ===${NC}"
EXISTING_GRVT=$(ps aux | grep "runbot.py.*grvt" | grep -v grep)
if [ -n "$EXISTING_GRVT" ]; then
    echo -e "${YELLOW}⚠️  检测到已运行的 GRVT 机器人:${NC}"
    echo "$EXISTING_GRVT"
    echo -e "${YELLOW}是否停止现有机器人并重新启动? (y/N): ${NC}"
    read -r user_input
    if [[ "$user_input" =~ ^[Yy]$ ]]; then
        echo -e "${CYAN}停止现有 GRVT 机器人...${NC}"
        pkill -f "runbot.py.*grvt"
        sleep 3
    else
        echo -e "${YELLOW}取消启动${NC}"
        exit 0
    fi
fi

# 启动 GRVT 机器人
echo -e "\n${GREEN}=== 启动 GRVT 机器人 ===${NC}"
echo -e "${CYAN}配置参数:${NC}"
echo -e "  交易标的: $GRVT_TICKER"
echo -e "  数量: $GRVT_QUANTITY"
echo -e "  止盈: $GRVT_TAKE_PROFIT"
echo -e "  方向: $GRVT_DIRECTION"
echo -e "  最大订单: $GRVT_MAX_ORDERS"
echo -e "  等待时间: $GRVT_WAIT_TIME 秒"
echo -e "  网格步长: $GRVT_GRID_STEP%"
echo -e "  停止价格: $GRVT_STOP_PRICE"
echo -e "  暂停价格: $GRVT_PAUSE_PRICE"
echo -e "  Aster加速: $GRVT_ASTER_BOOST"
echo -e "  环境文件: $GRVT_ENV_FILE"
echo -e "  回撤监控: $GRVT_ENABLE_DRAWDOWN_MONITOR"
if [ "$GRVT_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
    echo -e "  轻度回撤阈值: $GRVT_DRAWDOWN_LIGHT_THRESHOLD%"
    echo -e "  中度回撤阈值: $GRVT_DRAWDOWN_MEDIUM_THRESHOLD%"
    echo -e "  严重回撤阈值: $GRVT_DRAWDOWN_SEVERE_THRESHOLD%"
fi

# 备份旧日志文件
if [ -f "$GRVT_LOG_FILE" ]; then
    mv "$GRVT_LOG_FILE" "${GRVT_LOG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    echo -e "${CYAN}备份旧日志: ${GRVT_LOG_FILE}.backup.$(date +%Y%m%d_%H%M%S)${NC}"
fi

# 构建启动命令
START_CMD="$GRVT_ENV_PATH/bin/python3 runbot.py --exchange grvt --ticker $GRVT_TICKER --quantity $GRVT_QUANTITY --take-profit $GRVT_TAKE_PROFIT --direction $GRVT_DIRECTION --max-orders $GRVT_MAX_ORDERS --wait-time $GRVT_WAIT_TIME --grid-step $GRVT_GRID_STEP --stop-price $GRVT_STOP_PRICE --pause-price $GRVT_PAUSE_PRICE --env-file $GRVT_ENV_FILE"

# 添加可选参数
if [ "$GRVT_ASTER_BOOST" = "true" ]; then
    START_CMD="$START_CMD --aster-boost"
fi

if [ "$GRVT_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
    START_CMD="$START_CMD --enable-drawdown-monitor --drawdown-light-threshold $GRVT_DRAWDOWN_LIGHT_THRESHOLD --drawdown-medium-threshold $GRVT_DRAWDOWN_MEDIUM_THRESHOLD --drawdown-severe-threshold $GRVT_DRAWDOWN_SEVERE_THRESHOLD"
fi

# 启动机器人
echo -e "${YELLOW}启动 GRVT 交易机器人...${NC}"
nohup $START_CMD > "$GRVT_LOG_FILE" 2>&1 &

GRVT_PID=$!
echo -e "${CYAN}GRVT PID: $GRVT_PID${NC}"

# 等待进程启动并检查
sleep 3
if ps -p $GRVT_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ GRVT 机器人启动成功${NC}"
    echo "$GRVT_PID" > ".grvt_pid"
    
    # 检查日志中的初始化状态
    if [ -f "$GRVT_LOG_FILE" ]; then
        sleep 2
        local init_status=$(tail -10 "$GRVT_LOG_FILE" | grep -i "initialized\|started\|ready\|connected" | tail -1)
        if [ -n "$init_status" ]; then
            echo -e "${CYAN}状态: $init_status${NC}"
        fi
        
        # 检查是否有错误
        local errors=$(tail -10 "$GRVT_LOG_FILE" | grep -i "error\|exception\|failed" | wc -l)
        if [ "$errors" -gt 0 ]; then
            echo -e "${YELLOW}⚠️  检测到 $errors 个错误，请检查日志${NC}"
        fi
    fi
else
    echo -e "${RED}❌ GRVT 机器人启动失败${NC}"
    echo -e "${YELLOW}检查日志: tail -f $GRVT_LOG_FILE${NC}"
    exit 1
fi

echo -e "\n${GREEN}=== 监控命令 ===${NC}"
echo -e "${YELLOW}实时监控日志:${NC} tail -f $GRVT_LOG_FILE"
echo -e "${YELLOW}检查进程状态:${NC} ps aux | grep grvt"
echo -e "${YELLOW}停止机器人:${NC} ./scripts/stop_grvt.sh"

echo -e "\n${GREEN}🎉 GRVT 交易机器人启动完成!${NC}"
echo -e "${BLUE}完成时间: $(date)${NC}"