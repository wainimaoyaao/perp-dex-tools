#!/bin/bash
# Extended (X10) 交易机器人状态检查脚本

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

# 函数：记录问题
log_issue() {
    echo -e "${RED}❌ $1${NC}"
}

# 函数：显示成功状态
log_success() {
    echo -e "${GREEN}✅ $1${NC}"
}

# 函数：显示警告
log_warning() {
    echo -e "${YELLOW}⚠️  $1${NC}"
}

# 函数：显示信息
log_info() {
    echo -e "${CYAN}ℹ️  $1${NC}"
}

echo -e "${BLUE}=== Extended (X10) 交易机器人状态检查 ===${NC}"
echo -e "${BLUE}检查时间: $(date)${NC}"
echo ""

# 1. 检查进程状态
echo -e "${GREEN}=== 进程状态 ===${NC}"
EXTENDED_PROCESSES=$(ps aux | grep "runbot.py.*extended" | grep -v grep)

if [ -n "$EXTENDED_PROCESSES" ]; then
    log_success "Extended 机器人正在运行"
    echo "$EXTENDED_PROCESSES"
    
    # 获取进程 ID
    EXTENDED_PID=$(echo "$EXTENDED_PROCESSES" | awk '{print $2}')
    echo -e "${CYAN}进程 ID: $EXTENDED_PID${NC}"
    
    # 检查进程运行时间
    PROCESS_TIME=$(ps -o etime= -p "$EXTENDED_PID" 2>/dev/null | tr -d ' ')
    if [ -n "$PROCESS_TIME" ]; then
        echo -e "${CYAN}运行时间: $PROCESS_TIME${NC}"
    fi
    
    # 检查内存使用
    MEMORY_USAGE=$(ps -o rss= -p "$EXTENDED_PID" 2>/dev/null | tr -d ' ')
    if [ -n "$MEMORY_USAGE" ]; then
        MEMORY_MB=$((MEMORY_USAGE / 1024))
        echo -e "${CYAN}内存使用: ${MEMORY_MB}MB${NC}"
    fi
    
else
    log_issue "Extended 机器人未运行"
fi

# 检查 PID 文件
if [ -f ".extended_pid" ]; then
    PID_FILE_CONTENT=$(cat .extended_pid)
    if ps -p "$PID_FILE_CONTENT" > /dev/null 2>&1; then
        log_success "PID 文件有效: $PID_FILE_CONTENT"
    else
        log_warning "PID 文件存在但进程不存在: $PID_FILE_CONTENT"
    fi
else
    log_info "未找到 PID 文件"
fi

echo ""

# 2. 检查日志文件
echo -e "${GREEN}=== 日志状态 ===${NC}"
if [ -f "$EXTENDED_LOG_FILE" ]; then
    log_success "日志文件存在: $EXTENDED_LOG_FILE"
    
    # 检查日志文件大小
    LOG_SIZE=$(ls -lh "$EXTENDED_LOG_FILE" | awk '{print $5}')
    echo -e "${CYAN}日志大小: $LOG_SIZE${NC}"
    
    # 检查最后修改时间
    LOG_MODIFIED=$(stat -f "%Sm" -t "%Y-%m-%d %H:%M:%S" "$EXTENDED_LOG_FILE" 2>/dev/null || stat -c "%y" "$EXTENDED_LOG_FILE" 2>/dev/null | cut -d'.' -f1)
    echo -e "${CYAN}最后修改: $LOG_MODIFIED${NC}"
    
    # 检查最近的日志条目
    echo -e "${CYAN}最近的日志条目:${NC}"
    tail -5 "$EXTENDED_LOG_FILE" | while read -r line; do
        echo -e "  ${line}"
    done
    
    # 检查错误
    ERROR_COUNT=$(grep -i "error\|exception\|failed" "$EXTENDED_LOG_FILE" | wc -l | tr -d ' ')
    if [ "$ERROR_COUNT" -gt 0 ]; then
        log_warning "发现 $ERROR_COUNT 个错误条目"
        echo -e "${YELLOW}最近的错误:${NC}"
        grep -i "error\|exception\|failed" "$EXTENDED_LOG_FILE" | tail -3 | while read -r line; do
            echo -e "  ${line}"
        done
    else
        log_success "未发现错误条目"
    fi
    
else
    log_issue "日志文件不存在: $EXTENDED_LOG_FILE"
fi

echo ""

# 3. 检查配置
echo -e "${GREEN}=== 配置检查 ===${NC}"

# 检查 .env 文件
if [ -f ".env" ]; then
    log_success ".env 文件存在"
    
    # 检查 Extended 配置
    if grep -q "EXTENDED_" .env; then
        log_success "Extended 配置存在"
        
        # 检查必需的配置项
        required_vars=("EXTENDED_VAULT" "EXTENDED_STARK_KEY_PRIVATE" "EXTENDED_STARK_KEY_PUBLIC" "EXTENDED_API_KEY")
        for var in "${required_vars[@]}"; do
            if grep -q "^$var=" .env; then
                log_success "$var 已配置"
            else
                log_issue "$var 未配置"
            fi
        done
    else
        log_issue "未找到 Extended 配置"
    fi
else
    log_issue ".env 文件不存在"
fi

# 检查虚拟环境
if [ -f "$EXTENDED_ENV_PATH/bin/python3" ]; then
    log_success "虚拟环境存在: $EXTENDED_ENV_PATH"
    PYTHON_VERSION=$($EXTENDED_ENV_PATH/bin/python3 --version 2>&1)
    echo -e "${CYAN}Python 版本: $PYTHON_VERSION${NC}"
else
    log_issue "虚拟环境不存在: $EXTENDED_ENV_PATH"
fi

echo ""

# 4. 检查网络连接（如果机器人在运行）
if [ -n "$EXTENDED_PROCESSES" ]; then
    echo -e "${GREEN}=== 网络连接 ===${NC}"
    
    # 检查网络连接（基于日志）
    if [ -f "$EXTENDED_LOG_FILE" ]; then
        RECENT_ACTIVITY=$(tail -20 "$EXTENDED_LOG_FILE" | grep -i "connected\|disconnected\|timeout\|network" | tail -1)
        if [ -n "$RECENT_ACTIVITY" ]; then
            echo -e "${CYAN}最近网络活动: $RECENT_ACTIVITY${NC}"
        fi
        
        # 检查交易活动
        RECENT_TRADES=$(tail -50 "$EXTENDED_LOG_FILE" | grep -i "order\|trade\|position" | wc -l | tr -d ' ')
        if [ "$RECENT_TRADES" -gt 0 ]; then
            log_success "检测到 $RECENT_TRADES 个交易相关活动"
        else
            log_warning "未检测到最近的交易活动"
        fi
    fi
fi

echo ""

# 5. 系统资源检查
echo -e "${GREEN}=== 系统资源 ===${NC}"

# 检查磁盘空间
DISK_USAGE=$(df -h . | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$DISK_USAGE" -lt 90 ]; then
    log_success "磁盘空间充足 (${DISK_USAGE}% 已使用)"
else
    log_warning "磁盘空间不足 (${DISK_USAGE}% 已使用)"
fi

# 检查内存使用
if command -v free >/dev/null 2>&1; then
    MEMORY_INFO=$(free -h | grep "Mem:")
    echo -e "${CYAN}内存状态: $MEMORY_INFO${NC}"
elif command -v vm_stat >/dev/null 2>&1; then
    # macOS
    MEMORY_PRESSURE=$(memory_pressure 2>/dev/null | grep "System-wide memory free percentage" | awk '{print $5}' | sed 's/%//')
    if [ -n "$MEMORY_PRESSURE" ] && [ "$MEMORY_PRESSURE" -gt 10 ]; then
        log_success "内存充足 (${MEMORY_PRESSURE}% 可用)"
    else
        log_warning "内存紧张"
    fi
fi

echo ""

# 6. 总结
echo -e "${GREEN}=== 状态总结 ===${NC}"

if [ -n "$EXTENDED_PROCESSES" ]; then
    echo -e "${GREEN}🟢 Extended 机器人状态: 运行中${NC}"
    
    # 检查是否有严重问题
    CRITICAL_ISSUES=0
    
    if [ ! -f ".env" ] || ! grep -q "EXTENDED_" .env; then
        CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
    fi
    
    if [ ! -f "$EXTENDED_ENV_PATH/bin/python3" ]; then
        CRITICAL_ISSUES=$((CRITICAL_ISSUES + 1))
    fi
    
    if [ "$CRITICAL_ISSUES" -eq 0 ]; then
        echo -e "${GREEN}🟢 配置状态: 正常${NC}"
    else
        echo -e "${RED}🔴 配置状态: 发现 $CRITICAL_ISSUES 个严重问题${NC}"
    fi
    
else
    echo -e "${RED}🔴 Extended 机器人状态: 未运行${NC}"
    echo -e "${YELLOW}建议: 运行 ./scripts/start_extended.sh 启动机器人${NC}"
fi

echo ""
echo -e "${BLUE}=== 可用命令 ===${NC}"
echo -e "${CYAN}启动机器人: ./scripts/start_extended.sh${NC}"
echo -e "${CYAN}停止机器人: ./scripts/stop_extended.sh${NC}"
echo -e "${CYAN}查看日志: tail -f $EXTENDED_LOG_FILE${NC}"
echo -e "${CYAN}重新检查: ./scripts/check_extended.sh${NC}"

echo ""
echo -e "${BLUE}检查完成时间: $(date)${NC}"