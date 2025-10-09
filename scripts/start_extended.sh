#!/bin/bash
# Extended (X10) 交易机器人启动脚本

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

# 加载日志工具函数库
source ./scripts/log_utils.sh

echo -e "${GREEN}=== 启动 Extended (X10) 交易机器人 ===${NC}"
echo -e "${BLUE}启动时间: $(date)${NC}"
echo -e "${BLUE}工作目录: $SCRIPT_DIR${NC}"

# 函数：检查并创建日志目录 (已被log_utils.sh中的函数替代)
setup_logging() {
    # 使用新的日志准备函数
    prepare_log_file "$EXTENDED_LOG_FILE" "Extended"
}

# 函数：检查虚拟环境
check_virtual_env() {
    if [ ! -f "$EXTENDED_ENV_PATH/bin/python3" ]; then
        echo -e "${RED}错误: Extended 虚拟环境不存在!${NC}"
        echo -e "${YELLOW}请运行: python3 -m venv env${NC}"
        exit 1
    fi
    
    local python_version=$($EXTENDED_ENV_PATH/bin/python3 --version 2>&1)
    echo -e "${CYAN}✅ Extended 环境: $python_version${NC}"
}

# 函数：检查依赖包
check_dependencies() {
    if [ -f "requirements.txt" ]; then
        echo -e "${CYAN}检查 Extended 依赖包...${NC}"
        if ! $EXTENDED_ENV_PATH/bin/pip list --format=freeze > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  Extended 依赖包检查失败${NC}"
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
    echo -e "${YELLOW}请复制 env_example.txt 为 .env 并配置 Extended API 密钥${NC}"
    exit 1
fi

if ! grep -q "EXTENDED_" .env; then
    echo -e "${RED}错误: 未找到 Extended 配置${NC}"
    echo -e "${YELLOW}请在 .env 文件中添加以下配置:${NC}"
    echo -e "${CYAN}EXTENDED_VAULT=your_vault_address${NC}"
    echo -e "${CYAN}EXTENDED_STARK_KEY_PRIVATE=your_private_key${NC}"
    echo -e "${CYAN}EXTENDED_STARK_KEY_PUBLIC=your_public_key${NC}"
    echo -e "${CYAN}EXTENDED_API_KEY=your_api_key${NC}"
    exit 1
fi

echo -e "${GREEN}✅ Extended 配置检查完成${NC}"

# 检查是否已有运行中的 Extended 机器人
echo -e "\n${GREEN}=== 进程检查 ===${NC}"
EXISTING_EXTENDED=$(ps aux | grep "runbot.py.*extended" | grep -v grep)
if [ -n "$EXISTING_EXTENDED" ]; then
    echo -e "${YELLOW}⚠️  检测到已运行的 Extended 机器人:${NC}"
    echo "$EXISTING_EXTENDED"
    echo -e "${YELLOW}是否停止现有机器人并重新启动? (y/N): ${NC}"
    read -r user_input
    if [[ "$user_input" =~ ^[Yy]$ ]]; then
        echo -e "${CYAN}停止现有 Extended 机器人...${NC}"
        pkill -f "runbot.py.*extended"
        sleep 3
    else
        echo -e "${YELLOW}取消启动${NC}"
        exit 0
    fi
fi

# 启动 Extended 机器人
echo -e "\n${GREEN}=== 启动 Extended 机器人 ===${NC}"
echo -e "${CYAN}配置参数:${NC}"
echo -e "  交易标的: $EXTENDED_TICKER"
echo -e "  数量: $EXTENDED_QUANTITY"
echo -e "  止盈: $EXTENDED_TAKE_PROFIT"
echo -e "  方向: $EXTENDED_DIRECTION"
echo -e "  最大订单: $EXTENDED_MAX_ORDERS"
echo -e "  等待时间: $EXTENDED_WAIT_TIME 秒"
echo -e "  网格步长: $EXTENDED_GRID_STEP%"
echo -e "  停止价格: $EXTENDED_STOP_PRICE"
echo -e "  暂停价格: $EXTENDED_PAUSE_PRICE"
echo -e "  Aster加速: $EXTENDED_ASTER_BOOST"
echo -e "  环境文件: $EXTENDED_ENV_FILE"
echo -e "  回撤监控: $EXTENDED_ENABLE_DRAWDOWN_MONITOR"
if [ "$EXTENDED_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
    echo -e "  轻度回撤阈值: $EXTENDED_DRAWDOWN_LIGHT_THRESHOLD%"
    echo -e "  中度回撤阈值: $EXTENDED_DRAWDOWN_MEDIUM_THRESHOLD%"
    echo -e "  严重回撤阈值: $EXTENDED_DRAWDOWN_SEVERE_THRESHOLD%"
fi

# 备份旧日志文件
if [ -f "$EXTENDED_LOG_FILE" ]; then
    mv "$EXTENDED_LOG_FILE" "${EXTENDED_LOG_FILE}.backup.$(date +%Y%m%d_%H%M%S)"
    echo -e "${CYAN}备份旧日志: ${EXTENDED_LOG_FILE}.backup.$(date +%Y%m%d_%H%M%S)${NC}"
fi

# 构建启动命令
START_CMD="$EXTENDED_ENV_PATH/bin/python3 runbot.py --exchange extended --ticker $EXTENDED_TICKER --quantity $EXTENDED_QUANTITY --take-profit $EXTENDED_TAKE_PROFIT --direction $EXTENDED_DIRECTION --max-orders $EXTENDED_MAX_ORDERS --wait-time $EXTENDED_WAIT_TIME --grid-step $EXTENDED_GRID_STEP --stop-price $EXTENDED_STOP_PRICE --pause-price $EXTENDED_PAUSE_PRICE --env-file $EXTENDED_ENV_FILE"

# 添加可选参数
if [ "$EXTENDED_ASTER_BOOST" = "true" ]; then
    START_CMD="$START_CMD --aster-boost"
fi

if [ "$EXTENDED_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
    START_CMD="$START_CMD --enable-drawdown-monitor --drawdown-light-threshold $EXTENDED_DRAWDOWN_LIGHT_THRESHOLD --drawdown-medium-threshold $EXTENDED_DRAWDOWN_MEDIUM_THRESHOLD --drawdown-severe-threshold $EXTENDED_DRAWDOWN_SEVERE_THRESHOLD"
fi

# 启动机器人
local redirect_symbol=$(get_log_redirect)
echo -e "${YELLOW}启动 Extended 交易机器人...${NC}"
echo -e "${CYAN}日志输出: $EXTENDED_LOG_FILE (模式: ${redirect_symbol})${NC}"

# 在日志文件中添加启动标记
echo "=== $(date '+%Y-%m-%d %H:%M:%S') - Extended Bot Starting (PID: $$) ===" $redirect_symbol "$EXTENDED_LOG_FILE"

nohup $START_CMD $redirect_symbol "$EXTENDED_LOG_FILE" 2>&1 &

EXTENDED_PID=$!
echo -e "${CYAN}Extended PID: $EXTENDED_PID${NC}"

# 等待进程启动并检查
sleep 3
if ps -p $EXTENDED_PID > /dev/null 2>&1; then
    echo -e "${GREEN}✅ Extended 机器人启动成功${NC}"
    echo "$EXTENDED_PID" > ".extended_pid"
    
    # 检查日志中的初始化状态
    if [ -f "$EXTENDED_LOG_FILE" ]; then
        sleep 2
        init_status=$(tail -10 "$EXTENDED_LOG_FILE" | grep -i "initialized\|started\|ready\|connected" | tail -1)
        if [ -n "$init_status" ]; then
            echo -e "${CYAN}状态: $init_status${NC}"
        fi
        
        # 检查是否有错误
        errors=$(tail -10 "$EXTENDED_LOG_FILE" | grep -i "error\|exception\|failed" | wc -l)
        if [ -n "$errors" ] && [ "$errors" -gt 0 ]; then
            echo -e "${YELLOW}⚠️  检测到 $errors 个错误，请检查日志${NC}"
        fi
    fi
else
    echo -e "${RED}❌ Extended 机器人启动失败${NC}"
    echo -e "${YELLOW}检查日志: tail -f $EXTENDED_LOG_FILE${NC}"
    exit 1
fi

echo -e "\n${GREEN}=== 监控命令 ===${NC}"
echo -e "${YELLOW}实时监控日志:${NC} tail -f $EXTENDED_LOG_FILE"
echo -e "${YELLOW}检查进程状态:${NC} ps aux | grep extended"
echo -e "${YELLOW}停止机器人:${NC} ./scripts/stop_extended.sh"

echo -e "\n${GREEN}🎉 Extended (X10) 交易机器人启动完成!${NC}"
echo -e "${BLUE}完成时间: $(date)${NC}"