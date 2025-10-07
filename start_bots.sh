#!/bin/bash
# 交易机器人启动脚本
# 使用两个虚拟环境：env (通用) 和 para_env (Paradex专用)

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

echo -e "${GREEN}=== 启动交易机器人 ===${NC}"
echo -e "${BLUE}启动时间: $(date)${NC}"

# 获取脚本所在目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

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
    local env_name=$1
    local env_path=$2
    
    if [ ! -f "$env_path/bin/python3" ]; then
        echo -e "${RED}错误: 虚拟环境 '$env_name' 不存在!${NC}"
        echo -e "${YELLOW}请运行: python3 -m venv $env_name${NC}"
        return 1
    fi
    
    # 检查Python版本
    local python_version=$($env_path/bin/python3 --version 2>&1)
    echo -e "${CYAN}✅ $env_name 环境: $python_version${NC}"
    return 0
}

# 函数：检查依赖包
check_dependencies() {
    local env_path=$1
    local requirements_file=$2
    local env_name=$3
    
    if [ -f "$requirements_file" ]; then
        echo -e "${CYAN}检查 $env_name 依赖包...${NC}"
        if ! $env_path/bin/pip list --format=freeze > /dev/null 2>&1; then
            echo -e "${YELLOW}⚠️  $env_name 依赖包检查失败${NC}"
        fi
    fi
}

# 设置日志
setup_logging

# 检查虚拟环境
echo -e "\n${GREEN}=== 环境检查 ===${NC}"
if ! check_virtual_env "env" "./env"; then
    exit 1
fi

if ! check_virtual_env "para_env" "./para_env"; then
    exit 1
fi

# 检查依赖包
check_dependencies "./env" "requirements.txt" "env"
check_dependencies "./para_env" "para_requirements.txt" "para_env"

# 检查配置文件
echo -e "\n${GREEN}=== 配置检查 ===${NC}"
if [ ! -f ".env" ]; then
    echo -e "${RED}错误: .env 文件不存在!${NC}"
    echo -e "${YELLOW}请复制 env_example.txt 为 .env 并配置 API 密钥${NC}"
    exit 1
fi

# 检查关键配置项
if ! grep -q "PARADEX_" .env; then
    echo -e "${YELLOW}⚠️  未找到 Paradex 配置${NC}"
fi

if ! grep -q "GRVT_" .env; then
    echo -e "${YELLOW}⚠️  未找到 GRVT 配置${NC}"
fi

echo -e "${GREEN}✅ 配置文件检查完成${NC}"

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
        ./stop_bots.sh
        sleep 3
    else
        echo -e "${YELLOW}取消启动${NC}"
        exit 0
    fi
fi

# 函数：启动机器人
start_bot() {
    local exchange=$1
    local env_path=$2
    local log_file=$3
    
    echo -e "${YELLOW}启动 $exchange 交易机器人...${NC}"
    
    # 备份旧日志文件
    if [ -f "$log_file" ]; then
        mv "$log_file" "${log_file}.backup.$(date +%Y%m%d_%H%M%S)"
        echo -e "${CYAN}备份旧日志: ${log_file}.backup.$(date +%Y%m%d_%H%M%S)${NC}"
    fi
    
    # 启动机器人
    nohup $env_path/bin/python3 runbot.py \
        --exchange $exchange \
        --ticker BTC \
        --quantity 0.002 \
        --take-profit 0.005 \
        --max-orders 20 \
        --wait-time 450 \
        --grid-step 0.1 \
        --enable-drawdown-monitor \
        > "$log_file" 2>&1 &
    
    local pid=$!
    echo -e "${CYAN}$exchange PID: $pid${NC}"
    
    # 等待进程启动并检查
    sleep 2
    if ps -p $pid > /dev/null 2>&1; then
        echo -e "${GREEN}✅ $exchange 机器人启动成功${NC}"
        echo "$pid" > ".${exchange,,}_pid"
        return $pid
    else
        echo -e "${RED}❌ $exchange 机器人启动失败${NC}"
        echo -e "${YELLOW}检查日志: tail -f $log_file${NC}"
        return 0
    fi
}

echo -e "\n${GREEN}=== 启动机器人 ===${NC}"

# 启动 Paradex 机器人 (使用 para_env)
PARADEX_PID=$(start_bot "paradex" "./para_env" "paradex_output.log")

# 启动 GRVT 机器人 (使用 env)  
GRVT_PID=$(start_bot "grvt" "./env" "grvt_output.log")

# 等待所有进程稳定启动
sleep 3

echo -e "\n${GREEN}=== 运行状态检查 ===${NC}"

# 函数：检查机器人状态
check_bot_status() {
    local exchange=$1
    local pid=$2
    local log_file=$3
    
    if [ "$pid" -eq 0 ]; then
        echo -e "${RED}❌ $exchange 机器人启动失败${NC}"
        echo -e "${YELLOW}   检查日志: tail -f $log_file${NC}"
        return 1
    elif ps -p $pid > /dev/null 2>&1; then
        echo -e "${GREEN}✅ $exchange 机器人运行中 (PID: $pid)${NC}"
        
        # 检查日志中的初始化状态
        if [ -f "$log_file" ]; then
            sleep 1  # 等待日志写入
            local init_status=$(tail -10 "$log_file" | grep -i "initialized\|started\|ready\|connected" | tail -1)
            if [ -n "$init_status" ]; then
                echo -e "${CYAN}   状态: $init_status${NC}"
            fi
            
            # 检查是否有错误
            local errors=$(tail -10 "$log_file" | grep -i "error\|exception\|failed" | wc -l)
            if [ "$errors" -gt 0 ]; then
                echo -e "${YELLOW}   ⚠️  检测到 $errors 个错误，请检查日志${NC}"
            fi
        fi
        return 0
    else
        echo -e "${RED}❌ $exchange 机器人进程已停止 (PID: $pid)${NC}"
        echo -e "${YELLOW}   检查日志: tail -f $log_file${NC}"
        return 1
    fi
}

# 检查各机器人状态
check_bot_status "Paradex" "$PARADEX_PID" "paradex_output.log"
PARADEX_STATUS=$?

check_bot_status "GRVT" "$GRVT_PID" "grvt_output.log"
GRVT_STATUS=$?

# 显示所有运行中的 runbot.py 进程
echo -e "\n${GREEN}=== 所有运行中的交易机器人 ===${NC}"
RUNNING_BOTS=$(ps aux | grep runbot.py | grep -v grep)
if [ -n "$RUNNING_BOTS" ]; then
    echo "$RUNNING_BOTS"
    TOTAL_BOTS=$(echo "$RUNNING_BOTS" | wc -l)
    echo -e "${CYAN}总计: $TOTAL_BOTS 个机器人在运行${NC}"
else
    echo -e "${RED}未发现运行中的交易机器人${NC}"
fi

# 显示日志文件信息
echo -e "\n${GREEN}=== 日志文件 ===${NC}"
for log_file in "paradex_output.log" "grvt_output.log"; do
    if [ -f "$log_file" ]; then
        local size=$(du -h "$log_file" | cut -f1)
        echo -e "${CYAN}$log_file (大小: $size)${NC}"
    else
        echo -e "${YELLOW}$log_file (不存在)${NC}"
    fi
done

# 显示回撤监控状态
echo -e "\n${GREEN}=== 回撤监控状态 ===${NC}"
for log_file in "paradex_output.log" "grvt_output.log"; do
    if [ -f "$log_file" ]; then
        local exchange=$(echo "$log_file" | cut -d'_' -f1)
        local drawdown_status=$(tail -20 "$log_file" | grep -i "drawdown.*monitor\|drawdown.*enabled" | tail -1)
        if [ -n "$drawdown_status" ]; then
            echo -e "${CYAN}$exchange: $drawdown_status${NC}"
        else
            echo -e "${YELLOW}$exchange: 回撤监控状态未知${NC}"
        fi
    fi
done

echo -e "\n${GREEN}=== 监控命令 ===${NC}"
echo -e "${YELLOW}实时监控 Paradex 日志:${NC} tail -f paradex_output.log"
echo -e "${YELLOW}实时监控 GRVT 日志:${NC} tail -f grvt_output.log"
echo -e "${YELLOW}同时监控两个日志:${NC} tail -f paradex_output.log grvt_output.log"
echo -e "${YELLOW}检查机器人状态:${NC} ./check_bots.sh"
echo -e "${YELLOW}停止所有机器人:${NC} ./stop_bots.sh"

# 启动结果总结
echo -e "\n${GREEN}=== 启动结果总结 ===${NC}"
if [ $PARADEX_STATUS -eq 0 ] && [ $GRVT_STATUS -eq 0 ]; then
    echo -e "${GREEN}🎉 所有交易机器人启动成功!${NC}"
elif [ $PARADEX_STATUS -eq 0 ] || [ $GRVT_STATUS -eq 0 ]; then
    echo -e "${YELLOW}⚠️  部分交易机器人启动成功${NC}"
else
    echo -e "${RED}❌ 所有交易机器人启动失败${NC}"
    echo -e "${YELLOW}请检查配置和日志文件${NC}"
fi

echo -e "${BLUE}启动完成时间: $(date)${NC}"