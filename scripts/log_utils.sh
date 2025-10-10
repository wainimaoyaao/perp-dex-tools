#!/bin/bash
# 日志管理工具函数库
# 提供日志轮转、清理、分析等通用功能

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
WHITE='\033[1;37m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# 加载配置文件
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/bot_configs.sh"

# 确保logs目录存在
ensure_logs_directory() {
    if [ ! -d "logs" ]; then
        mkdir -p logs
        echo -e "${CYAN}创建logs目录${NC}"
    fi
}

# 获取文件大小(MB)
get_file_size_mb() {
    local file="$1"
    if [ -f "$file" ]; then
        if [[ "$OSTYPE" == "darwin"* ]]; then
            # macOS
            stat -f%z "$file" | awk '{print int($1/1024/1024)}'
        else
            # Linux
            stat -c%s "$file" | awk '{print int($1/1024/1024)}'
        fi
    else
        echo "0"
    fi
}

# 压缩日志文件
compress_log_file() {
    local file="$1"
    
    if [ "$LOG_COMPRESS" = "true" ] && command -v gzip >/dev/null 2>&1; then
        if [ -f "$file" ]; then
            echo -e "${CYAN}压缩日志文件: $file${NC}"
            gzip "$file"
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}✓ 压缩完成: ${file}.gz${NC}"
                return 0
            else
                echo -e "${RED}✗ 压缩失败: $file${NC}"
                return 1
            fi
        fi
    fi
    return 0
}

# 日志轮转函数
rotate_log_if_needed() {
    local log_file="$1"
    local exchange_name="$2"
    
    # 检查是否启用日志轮转
    if [ "$LOG_ROTATION_ENABLED" != "true" ]; then
        return 0
    fi
    
    # 确保logs目录存在
    ensure_logs_directory
    
    # 完整的日志文件路径
    local full_log_path="$log_file"
    
    if [ -f "$full_log_path" ]; then
        local current_size_mb=$(get_file_size_mb "$full_log_path")
        
        if [ "$current_size_mb" -gt "$LOG_MAX_SIZE_MB" ]; then
            local timestamp=$(date +%Y%m%d_%H%M%S)
            local log_name="${log_file%.log}"
            local backup_file="logs/${log_name}_${timestamp}.log"
            
            echo -e "${YELLOW}📋 ${exchange_name} 日志文件过大 (${current_size_mb}MB > ${LOG_MAX_SIZE_MB}MB)${NC}"
            echo -e "${CYAN}🔄 正在轮转日志文件...${NC}"
            
            # 移动当前日志文件
            mv "$full_log_path" "$backup_file"
            if [ $? -eq 0 ]; then
                echo -e "${GREEN}✓ 已备份到: $backup_file${NC}"
                
                # 压缩备份文件
                compress_log_file "$backup_file"
                
                # 创建新的日志文件并添加轮转标记
                echo "=== $(date '+%Y-%m-%d %H:%M:%S') - Log rotated from ${log_file} ===" > "$full_log_path"
                
                return 0
            else
                echo -e "${RED}✗ 日志轮转失败${NC}"
                return 1
            fi
        fi
    fi
    
    return 0
}

# 清理旧日志文件
cleanup_old_logs() {
    local log_prefix="$1"
    local exchange_name="$2"
    
    if [ "$LOG_AUTO_CLEANUP" != "true" ]; then
        return 0
    fi
    
    ensure_logs_directory
    
    echo -e "${CYAN}🧹 清理 ${exchange_name} 超过 $LOG_KEEP_DAYS 天的旧日志...${NC}"
    
    local cleaned_count=0
    
    # 查找并删除旧的日志文件
    find logs/ -name "${log_prefix}_*.log*" -mtime +$LOG_KEEP_DAYS -type f 2>/dev/null | while read -r old_log; do
        if [ -f "$old_log" ]; then
            local file_size=$(du -h "$old_log" 2>/dev/null | cut -f1)
            echo -e "${YELLOW}🗑️  删除旧日志: $old_log ($file_size)${NC}"
            rm -f "$old_log"
            cleaned_count=$((cleaned_count + 1))
        fi
    done
    
    if [ $cleaned_count -gt 0 ]; then
        echo -e "${GREEN}✓ 已清理 $cleaned_count 个旧日志文件${NC}"
    fi
}

# 启动时清理日志
cleanup_logs_on_start() {
    local log_file="$1"
    local exchange_name="$2"
    
    if [ "$LOG_CLEANUP_ON_START" = "true" ]; then
        local full_log_path="$log_file"
        if [ -f "$full_log_path" ]; then
            echo -e "${YELLOW}🧹 启动时清理 ${exchange_name} 日志文件${NC}"
            rm -f "$full_log_path"
        fi
    fi
}

# 准备日志文件(在启动bot之前调用)
prepare_log_file() {
    local log_file="$1"
    local exchange_name="$2"
    
    ensure_logs_directory
    
    # 获取日志文件前缀(去掉.log扩展名)
    local log_prefix="${log_file%.log}"
    
    # 启动时清理(如果启用)
    cleanup_logs_on_start "$log_file" "$exchange_name"
    
    # 日志轮转检查
    rotate_log_if_needed "$log_file" "$exchange_name"
    
    # 清理旧日志
    cleanup_old_logs "$log_prefix" "$exchange_name"
    
    # 确保日志文件存在
    local full_log_path="$log_file"
    if [ ! -f "$full_log_path" ]; then
        touch "$full_log_path"
    fi
}

# 获取日志重定向符号
get_log_redirect() {
    if [ "$LOG_APPEND_MODE" = "true" ]; then
        echo ">>"
    else
        echo ">"
    fi
}

# 分析日志轮转状态
analyze_log_rotation_status() {
    local log_file="$1"
    local exchange_name="$2"
    
    ensure_logs_directory
    
    local log_prefix="${log_file%.log}"
    # 检查日志文件是否在当前目录或logs目录
    local full_log_path=""
    if [ -f "$log_file" ]; then
        full_log_path="$log_file"
    elif [ -f "$log_file" ]; then
        full_log_path="$log_file"
    else
        full_log_path="$log_file"  # 默认使用传入的路径
    fi
    
    echo -e "${PURPLE}${BOLD}=== ${exchange_name} 日志轮转状态 ===${NC}"
    
    # 当前日志文件状态
    if [ -f "$full_log_path" ]; then
        local current_size_mb=$(get_file_size_mb "$full_log_path")
        local line_count=$(wc -l < "$full_log_path" 2>/dev/null || echo "0")
        local last_modified=$(ls -la "$full_log_path" | awk '{print $6, $7, $8}')
        
        echo -e "${CYAN}📄 当前日志: $log_file${NC}"
        echo -e "${BLUE}   大小: ${current_size_mb}MB | 行数: ${line_count} | 修改时间: ${last_modified}${NC}"
        
        if [ "$current_size_mb" -gt $((LOG_MAX_SIZE_MB * 80 / 100)) ]; then
            echo -e "${YELLOW}⚠️  当前日志接近轮转阈值 (${LOG_MAX_SIZE_MB}MB)${NC}"
        fi
    else
        echo -e "${RED}❌ 当前日志文件不存在: $log_file${NC}"
    fi
    
    # 历史日志文件
    local archived_logs=$(find logs/ -name "${log_prefix}_*.log*" -type f 2>/dev/null | wc -l)
    if [ "$archived_logs" -gt 0 ]; then
        echo -e "${CYAN}📚 历史日志文件: $archived_logs 个${NC}"
        echo -e "${BLUE}最近的历史日志:${NC}"
        find logs/ -name "${log_prefix}_*.log*" -type f 2>/dev/null | sort -r | head -3 | while read -r log; do
            local size=$(du -h "$log" 2>/dev/null | cut -f1)
            local mod_time=$(ls -la "$log" | awk '{print $6, $7, $8}')
            echo -e "${BLUE}   📋 $log ($size) - $mod_time${NC}"
        done
    else
        echo -e "${CYAN}📚 无历史日志文件${NC}"
    fi
    
    # 总日志大小
    local total_size=$(du -sh logs/${log_prefix}* 2>/dev/null | awk '{sum+=$1} END {print (sum ? sum"B" : "0B")}' || echo "0B")
    echo -e "${CYAN}💾 总日志大小: ${total_size}${NC}"
    
    # 配置信息
    echo -e "${PURPLE}⚙️  日志配置:${NC}"
    echo -e "${BLUE}   轮转阈值: ${LOG_MAX_SIZE_MB}MB | 保留天数: ${LOG_KEEP_DAYS}天${NC}"
    echo -e "${BLUE}   压缩: ${LOG_COMPRESS} | 自动清理: ${LOG_AUTO_CLEANUP} | 追加模式: ${LOG_APPEND_MODE}${NC}"
}

# 手动轮转指定交易所的日志
manual_rotate_log() {
    local log_file="$1"
    local exchange_name="$2"
    
    echo -e "${CYAN}🔄 手动轮转 ${exchange_name} 日志文件...${NC}"
    
    # 检查是否启用日志轮转
    if [ "$LOG_ROTATION_ENABLED" != "true" ]; then
        echo -e "${YELLOW}⚠️ 日志轮转未启用${NC}"
        return 1
    fi
    
    # 确保logs目录存在
    ensure_logs_directory
    
    # 检查日志文件是否存在（支持多个路径）
    local source_file=""
    if [ -f "$log_file" ]; then
        source_file="$log_file"
    elif [ -f "$log_file" ]; then
        source_file="$log_file"
    else
        echo -e "${RED}✗ 日志文件不存在: $log_file${NC}"
        return 1
    fi
    
    # 生成备份文件名
    local timestamp=$(date +%Y%m%d_%H%M%S)
    local log_name=$(basename "${log_file%.log}")
    local backup_file="logs/${log_name}_${timestamp}.log"
    
    echo -e "${CYAN}📋 轮转日志文件: $source_file -> $backup_file${NC}"
    
    # 移动当前日志文件到备份位置
    mv "$source_file" "$backup_file"
    if [ $? -eq 0 ]; then
        echo -e "${GREEN}✓ 已备份到: $backup_file${NC}"
        
        # 压缩备份文件
        compress_log_file "$backup_file"
        
        # 创建新的日志文件并添加轮转标记
        echo "=== $(date '+%Y-%m-%d %H:%M:%S') - Log rotated from ${source_file} ===" > "$source_file"
        
        echo -e "${GREEN}✓ ${exchange_name} 日志轮转完成${NC}"
        return 0
    else
        echo -e "${RED}✗ 日志轮转失败${NC}"
        return 1
    fi
}

# 显示所有交易所的日志状态概览
show_all_logs_overview() {
    echo -e "${PURPLE}${BOLD}=== 所有交易所日志状态概览 ===${NC}"
    
    # 定义所有交易所及其日志文件
    local exchanges=(
        "Paradex:$PARADEX_LOG_FILE"
        "GRVT:$GRVT_LOG_FILE"
        "Extended:$EXTENDED_LOG_FILE"
        "Lighter:$LIGHTER_LOG_FILE"
    )
    
    for exchange_info in "${exchanges[@]}"; do
        local exchange_name="${exchange_info%%:*}"
        local log_file="${exchange_info##*:}"
        local full_log_path="$log_file"
        
        if [ -f "$full_log_path" ]; then
            local size_mb=$(get_file_size_mb "$full_log_path")
            local status_color="${GREEN}"
            local status_icon="✓"
            
            if [ "$size_mb" -gt "$LOG_MAX_SIZE_MB" ]; then
                status_color="${RED}"
                status_icon="⚠️"
            elif [ "$size_mb" -gt $((LOG_MAX_SIZE_MB * 80 / 100)) ]; then
                status_color="${YELLOW}"
                status_icon="⚠️"
            fi
            
            echo -e "${status_color}${status_icon} ${exchange_name}: ${size_mb}MB${NC}"
        else
            echo -e "${RED}❌ ${exchange_name}: 日志文件不存在${NC}"
        fi
    done
    
    echo -e "${CYAN}💡 使用 './scripts/check_<exchange>.sh' 查看详细状态${NC}"
}