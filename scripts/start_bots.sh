#!/bin/bash
# 交易机器人统一启动脚本
# 调用各个交易所的独立启动脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 启动所有交易机器人 ===${NC}"
echo -e "${BLUE}启动时间: $(date)${NC}"

# 获取项目根目录（脚本所在目录的上级目录）
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo -e "${BLUE}工作目录: $PROJECT_ROOT${NC}"

# 检查独立启动脚本是否存在
echo -e "\n${GREEN}=== 检查启动脚本 ===${NC}"
SCRIPTS_TO_CHECK=("start_paradex.sh" "start_grvt.sh")
MISSING_SCRIPTS=()

for script in "${SCRIPTS_TO_CHECK[@]}"; do
    if [ -f "scripts/$script" ]; then
        echo -e "${GREEN}✅ $script 存在${NC}"
        # 确保脚本有执行权限
        chmod +x "scripts/$script"
    else
        echo -e "${RED}❌ $script 不存在${NC}"
        MISSING_SCRIPTS+=("$script")
    fi
done

if [ ${#MISSING_SCRIPTS[@]} -gt 0 ]; then
    echo -e "${RED}错误: 缺少以下启动脚本:${NC}"
    for script in "${MISSING_SCRIPTS[@]}"; do
        echo -e "  - $script"
    done
    echo -e "${YELLOW}请确保所有独立启动脚本都已创建${NC}"
    exit 1
fi

# 检查是否已有运行中的机器人
echo -e "\n${GREEN}=== 进程检查 ===${NC}"
EXISTING_PROCESSES=$(ps aux | grep runbot.py | grep -v grep)
if [ -n "$EXISTING_PROCESSES" ]; then
    echo -e "${YELLOW}⚠️  检测到已运行的交易机器人:${NC}"
    echo "$EXISTING_PROCESSES"
    echo -e "${YELLOW}是否停止现有机器人并重新启动? (y/N): ${NC}"
    read -r user_input
    if [[ "$user_input" =~ ^[Yy]$ ]]; then
        echo -e "${CYAN}停止现有机器人...${NC}"
        ./scripts/stop_bots.sh
        sleep 3
    else
        echo -e "${YELLOW}取消启动${NC}"
        exit 0
    fi
fi

echo -e "\n${GREEN}=== 启动各交易所机器人 ===${NC}"

# 启动 Paradex 机器人
echo -e "${CYAN}启动 Paradex 机器人...${NC}"
if ./scripts/start_paradex.sh; then
    echo -e "${GREEN}✅ Paradex 机器人启动脚本执行完成${NC}"
    PARADEX_SUCCESS=true
else
    echo -e "${RED}❌ Paradex 机器人启动失败${NC}"
    PARADEX_SUCCESS=false
fi

echo -e "\n${CYAN}等待 3 秒后启动下一个机器人...${NC}"
sleep 3

# 启动 GRVT 机器人
echo -e "${CYAN}启动 GRVT 机器人...${NC}"
if ./scripts/start_grvt.sh; then
    echo -e "${GREEN}✅ GRVT 机器人启动脚本执行完成${NC}"
    GRVT_SUCCESS=true
else
    echo -e "${RED}❌ GRVT 机器人启动失败${NC}"
    GRVT_SUCCESS=false
fi

# 等待所有进程稳定启动
sleep 3

echo -e "\n${GREEN}=== 运行状态检查 ===${NC}"

# 显示所有运行中的 runbot.py 进程
RUNNING_BOTS=$(ps aux | grep runbot.py | grep -v grep)
if [ -n "$RUNNING_BOTS" ]; then
    echo -e "${GREEN}✅ 发现运行中的交易机器人:${NC}"
    echo "$RUNNING_BOTS"
    TOTAL_BOTS=$(echo "$RUNNING_BOTS" | wc -l)
    echo -e "${CYAN}总计: $TOTAL_BOTS 个机器人在运行${NC}"
else
    echo -e "${RED}❌ 未发现运行中的交易机器人${NC}"
fi

# 显示日志文件信息
echo -e "\n${GREEN}=== 日志文件 ===${NC}"
for log_file in "paradex_output.log" "grvt_output.log"; do
    if [ -f "$log_file" ]; then
        size=$(du -h "$log_file" | cut -f1)
        echo -e "${CYAN}$log_file (大小: $size)${NC}"
    else
        echo -e "${YELLOW}$log_file (不存在)${NC}"
    fi
done

echo -e "\n${GREEN}=== 管理命令 ===${NC}"
echo -e "${YELLOW}启动单个机器人:${NC}"
echo -e "  Paradex: ./scripts/start_paradex.sh"
echo -e "  GRVT: ./scripts/start_grvt.sh"
echo -e "${YELLOW}监控日志:${NC}"
echo -e "  Paradex: tail -f paradex_output.log"
echo -e "  GRVT: tail -f grvt_output.log"
echo -e "  同时监控: tail -f paradex_output.log grvt_output.log"
echo -e "${YELLOW}其他命令:${NC}"
echo -e "  检查状态: ./scripts/check_bots.sh"
echo -e "  停止所有: ./scripts/stop_bots.sh"
echo -e "  修改配置: nano scripts/bot_configs.sh"

# 启动结果总结
echo -e "\n${GREEN}=== 启动结果总结 ===${NC}"
if [ "$PARADEX_SUCCESS" = true ] && [ "$GRVT_SUCCESS" = true ]; then
    echo -e "${GREEN}🎉 所有交易机器人启动脚本执行成功!${NC}"
    echo -e "${CYAN}请检查上述进程列表确认机器人是否正常运行${NC}"
elif [ "$PARADEX_SUCCESS" = true ] || [ "$GRVT_SUCCESS" = true ]; then
    echo -e "${YELLOW}⚠️  部分交易机器人启动脚本执行成功${NC}"
    echo -e "${CYAN}请检查失败的机器人日志文件${NC}"
else
    echo -e "${RED}❌ 所有交易机器人启动脚本执行失败${NC}"
    echo -e "${YELLOW}请检查配置和日志文件${NC}"
fi

echo -e "\n${BLUE}启动完成时间: $(date)${NC}"