#!/bin/bash
# Lighter 交易机器人启动脚本

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

echo -e "${GREEN}=== 启动 Lighter 交易机器人 ===${NC}"
echo -e "${BLUE}启动时间: $(date)${NC}"
echo -e "${BLUE}工作目录: $PROJECT_ROOT${NC}"

# 函数：检查并创建日志目录 (已被log_utils.sh中的函数替代)
setup_logging() {
    # 使用新的日志准备函数
    prepare_log_file "$LIGHTER_LOG_FILE" "Lighter"
}

# 函数：检查虚拟环境
check_virtual_env() {
    if [ ! -f "$LIGHTER_ENV_PATH/bin/python3" ]; then
        echo -e "${RED}错误: Lighter 虚拟环境不存在!${NC}"
        echo -e "${YELLOW}请运行: python3 -m venv env${NC}"
        exit 1
    fi
    
    local python_version=$($LIGHTER_ENV_PATH/bin/python3 --version 2>&1)
    echo -e "${CYAN}✅ Lighter 环境: $python_version${NC}"
}

# 函数：检查依赖包
check_dependencies() {
    if [ -f "requirements.txt" ]; then
        echo -e "${CYAN}检查 Lighter 依赖包...${NC}"
        if ! $LIGHTER_ENV_PATH/bin/pip list --format=freeze > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  Lighter 依赖包检查失败${NC}"
        fi
    fi
}

# 函数：检查环境变量文件
check_env_file() {
    if [ ! -f "$LIGHTER_ENV_FILE" ]; then
        echo -e "${RED}错误: 环境变量文件 $LIGHTER_ENV_FILE 不存在!${NC}"
        echo -e "${YELLOW}请创建环境变量文件并配置 Lighter API 密钥${NC}"
        exit 1
    fi
    echo -e "${CYAN}✅ 环境变量文件: $LIGHTER_ENV_FILE${NC}"
}

# 函数：检查进程是否已运行
check_existing_process() {
    local pids=$(pgrep -f "trading_bot.py.*lighter")
    if [ ! -z "$pids" ]; then
        echo -e "${YELLOW}⚠️  发现已运行的 Lighter 机器人进程:${NC}"
        echo -e "${YELLOW}PID: $pids${NC}"
        echo -e "${YELLOW}是否要停止现有进程并重新启动? (y/n)${NC}"
        read -r response
        if [[ "$response" =~ ^[Yy]$ ]]; then
            echo -e "${CYAN}停止现有进程...${NC}"
            kill $pids
            sleep 3
            echo -e "${GREEN}✅ 已停止现有进程${NC}"
        else
            echo -e "${YELLOW}取消启动${NC}"
            exit 0
        fi
    fi
}

# 函数：显示启动参数
show_startup_params() {
    echo -e "${CYAN}=== Lighter 启动参数 ===${NC}"
    echo -e "${BLUE}交易对: $LIGHTER_TICKER${NC}"
    echo -e "${BLUE}数量: $LIGHTER_QUANTITY${NC}"
    echo -e "${BLUE}止盈: $LIGHTER_TAKE_PROFIT${NC}"
    echo -e "${BLUE}方向: $LIGHTER_DIRECTION${NC}"
    echo -e "${BLUE}最大订单数: $LIGHTER_MAX_ORDERS${NC}"
    echo -e "${BLUE}等待时间: $LIGHTER_WAIT_TIME 秒${NC}"
    echo -e "${BLUE}网格步长: $LIGHTER_GRID_STEP%${NC}"
    echo -e "${BLUE}止损价格: $LIGHTER_STOP_PRICE${NC}"
    echo -e "${BLUE}暂停价格: $LIGHTER_PAUSE_PRICE${NC}"
    echo -e "${BLUE}Aster 加速: $LIGHTER_ASTER_BOOST${NC}"
    echo -e "${BLUE}日志文件: logs/$LIGHTER_LOG_FILE${NC}"
    echo -e "${BLUE}回撤监控: $LIGHTER_ENABLE_DRAWDOWN_MONITOR${NC}"
    if [ "$LIGHTER_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
        echo -e "${BLUE}  - 轻度回撤阈值: $LIGHTER_DRAWDOWN_LIGHT_THRESHOLD%${NC}"
        echo -e "${BLUE}  - 中度回撤阈值: $LIGHTER_DRAWDOWN_MEDIUM_THRESHOLD%${NC}"
        echo -e "${BLUE}  - 严重回撤阈值: $LIGHTER_DRAWDOWN_SEVERE_THRESHOLD%${NC}"
    fi
    echo ""
}

# 函数：启动机器人
start_bot() {
    echo -e "${GREEN}🚀 启动 Lighter 交易机器人...${NC}"
    
    # 构建启动命令
    local cmd="$LIGHTER_ENV_PATH/bin/python3 trading_bot.py"
    cmd="$cmd --exchange lighter"
    cmd="$cmd --ticker $LIGHTER_TICKER"
    cmd="$cmd --quantity $LIGHTER_QUANTITY"
    cmd="$cmd --take_profit $LIGHTER_TAKE_PROFIT"
    cmd="$cmd --direction $LIGHTER_DIRECTION"
    cmd="$cmd --max_orders $LIGHTER_MAX_ORDERS"
    cmd="$cmd --wait_time $LIGHTER_WAIT_TIME"
    cmd="$cmd --grid_step $LIGHTER_GRID_STEP"
    cmd="$cmd --stop_price $LIGHTER_STOP_PRICE"
    cmd="$cmd --pause_price $LIGHTER_PAUSE_PRICE"
    cmd="$cmd --aster_boost $LIGHTER_ASTER_BOOST"
    
    # 添加回撤监控参数
    if [ "$LIGHTER_ENABLE_DRAWDOWN_MONITOR" = "true" ]; then
        cmd="$cmd --enable_drawdown_monitor"
        cmd="$cmd --drawdown_light_threshold $LIGHTER_DRAWDOWN_LIGHT_THRESHOLD"
        cmd="$cmd --drawdown_medium_threshold $LIGHTER_DRAWDOWN_MEDIUM_THRESHOLD"
        cmd="$cmd --drawdown_severe_threshold $LIGHTER_DRAWDOWN_SEVERE_THRESHOLD"
    fi
    
    # 启动机器人并重定向输出到日志文件
    local redirect_symbol=$(get_log_redirect)
    echo -e "${CYAN}执行命令: $cmd${NC}"
    echo -e "${CYAN}日志输出: logs/$LIGHTER_LOG_FILE (模式: ${redirect_symbol})${NC}"
    
    # 在日志文件中添加启动标记
    echo "=== $(date '+%Y-%m-%d %H:%M:%S') - Lighter Bot Starting (PID: $$) ===" $redirect_symbol "logs/$LIGHTER_LOG_FILE"
    
    nohup $cmd $redirect_symbol "logs/$LIGHTER_LOG_FILE" 2>&1 &
    local bot_pid=$!
    
    # 等待一下确保进程启动
    sleep 3
    
    # 检查进程是否成功启动
    if kill -0 $bot_pid 2>/dev/null; then
        echo -e "${GREEN}✅ Lighter 机器人启动成功!${NC}"
        echo -e "${GREEN}进程 PID: $bot_pid${NC}"
        echo -e "${CYAN}查看日志: tail -f logs/$LIGHTER_LOG_FILE${NC}"
        echo -e "${CYAN}检查状态: ./scripts/check_lighter.sh${NC}"
        echo -e "${CYAN}停止机器人: ./scripts/stop_lighter.sh${NC}"
        
        # 将PID写入文件以便后续管理
        echo $bot_pid > "logs/lighter_bot.pid"
        echo -e "${CYAN}PID 已保存到: logs/lighter_bot.pid${NC}"
    else
        echo -e "${RED}❌ Lighter 机器人启动失败!${NC}"
        echo -e "${YELLOW}请检查日志文件: logs/$LIGHTER_LOG_FILE${NC}"
        exit 1
    fi
}

# 函数：显示启动后信息
show_post_startup_info() {
    echo ""
    echo -e "${GREEN}=== Lighter 机器人启动完成 ===${NC}"
    echo -e "${CYAN}常用命令:${NC}"
    echo -e "${BLUE}  查看实时日志: tail -f logs/$LIGHTER_LOG_FILE${NC}"
    echo -e "${BLUE}  检查机器人状态: ./scripts/check_lighter.sh${NC}"
    echo -e "${BLUE}  停止机器人: ./scripts/stop_lighter.sh${NC}"
    echo -e "${BLUE}  查看所有机器人: ./scripts/check_bots.sh${NC}"
    echo ""
    echo -e "${YELLOW}⚠️  重要提醒:${NC}"
    echo -e "${YELLOW}  - 请定期检查机器人状态和日志${NC}"
    echo -e "${YELLOW}  - 注意市场风险，合理设置止损${NC}"
    echo -e "${YELLOW}  - 建议启用回撤监控功能${NC}"
    echo ""
}

# 主执行流程
main() {
    setup_logging
    check_virtual_env
    check_dependencies
    check_env_file
    check_existing_process
    show_startup_params
    
    # 确认启动
    echo -e "${YELLOW}确认启动 Lighter 交易机器人? (y/n)${NC}"
    read -r response
    if [[ "$response" =~ ^[Yy]$ ]]; then
        start_bot
        show_post_startup_info
    else
        echo -e "${YELLOW}取消启动${NC}"
        exit 0
    fi
}

# 错误处理
set -e
trap 'echo -e "${RED}脚本执行出错，请检查错误信息${NC}"' ERR

# 执行主函数
main "$@"