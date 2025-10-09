#!/bin/bash
# 交易机器人日志管理脚本
# 版本: 1.0
# 功能: 统一管理所有交易机器人的日志文件
# 支持日志轮转、清理、查看、分析等功能

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
PURPLE='\033[0;35m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# 获取项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

# 加载配置和工具库
source "$SCRIPT_DIR/bot_configs.sh"
source "$SCRIPT_DIR/log_utils.sh"

# 全局变量
TOTAL_ISSUES=0
CRITICAL_ISSUES=0

# 函数：记录问题
log_issue() {
    local level=$1
    local message=$2
    
    case $level in
        "critical")
            echo -e "${RED}❌ [严重] $message${NC}"
            ((CRITICAL_ISSUES++))
            ((TOTAL_ISSUES++))
            ;;
        "warning")
            echo -e "${YELLOW}⚠️  [警告] $message${NC}"
            ((TOTAL_ISSUES++))
            ;;
        "info")
            echo -e "${CYAN}ℹ️  [信息] $message${NC}"
            ;;
    esac
}

# 函数：记录成功
log_success() {
    local message=$1
    echo -e "${GREEN}✅ $message${NC}"
}

# 函数：显示使用说明
show_usage() {
    echo -e "${BOLD}${GREEN}交易机器人日志管理脚本 v1.0${NC}"
    echo -e "${CYAN}用法: $0 [命令] [选项]${NC}"
    echo ""
    echo -e "${YELLOW}命令:${NC}"
    echo -e "  ${GREEN}status${NC}        显示所有日志文件状态"
    echo -e "  ${GREEN}rotate${NC}        手动执行日志轮转"
    echo -e "  ${GREEN}clean${NC}         清理旧日志文件"
    echo -e "  ${GREEN}view${NC}          查看日志文件"
    echo -e "  ${GREEN}analyze${NC}       分析日志内容"
    echo -e "  ${GREEN}config${NC}        显示/修改日志配置"
    echo -e "  ${GREEN}help${NC}          显示此帮助信息"
    echo ""
    echo -e "${YELLOW}选项:${NC}"
    echo -e "  ${GREEN}--bot <name>${NC}   指定机器人 (paradex|grvt|extended|lighter)"
    echo -e "  ${GREEN}--lines <n>${NC}    显示行数 (默认: 50)"
    echo -e "  ${GREEN}--days <n>${NC}     保留天数 (默认: 7)"
    echo -e "  ${GREEN}--force${NC}        强制执行操作"
    echo ""
    echo -e "${YELLOW}示例:${NC}"
    echo -e "  ${CYAN}$0 status${NC}                    显示所有日志状态"
    echo -e "  ${CYAN}$0 rotate --bot paradex${NC}     轮转 Paradex 日志"
    echo -e "  ${CYAN}$0 view --bot grvt --lines 100${NC}  查看 GRVT 最后100行"
    echo -e "  ${CYAN}$0 clean --days 3${NC}           清理3天前的日志"
    echo -e "  ${CYAN}$0 analyze --bot extended${NC}   分析 Extended 日志"
}

# 函数：获取日志文件列表
get_log_files() {
    local bot_filter=$1
    local log_files=()
    
    case $bot_filter in
        "paradex")
            log_files=("$PARADEX_LOG_FILE")
            ;;
        "grvt")
            log_files=("$GRVT_LOG_FILE")
            ;;
        "extended")
            log_files=("$EXTENDED_LOG_FILE")
            ;;
        "lighter")
            log_files=("$LIGHTER_LOG_FILE")
            ;;
        *)
            log_files=("$PARADEX_LOG_FILE" "$GRVT_LOG_FILE" "$EXTENDED_LOG_FILE" "$LIGHTER_LOG_FILE")
            ;;
    esac
    
    echo "${log_files[@]}"
}

# 函数：显示日志状态
show_log_status() {
    local bot_filter=$1
    local log_files=($(get_log_files "$bot_filter"))
    
    echo -e "${BOLD}${GREEN}=== 日志文件状态 ===${NC}"
    
    for log_file in "${log_files[@]}"; do
        if [ -z "$log_file" ]; then
            continue
        fi
        
        local bot_name=$(basename "$log_file" | cut -d'_' -f1)
        echo -e "\n${PURPLE}📊 $bot_name 日志状态:${NC}"
        
        if [ -f "$log_file" ]; then
            local size=$(du -h "$log_file" | cut -f1)
            local size_mb=$(du -m "$log_file" | cut -f1)
            local lines=$(wc -l < "$log_file")
            local modified=$(stat -f %Sm -t "%Y-%m-%d %H:%M:%S" "$log_file" 2>/dev/null || stat -c %y "$log_file" 2>/dev/null | cut -d'.' -f1)
            
            log_success "文件存在: $log_file"
            echo -e "${CYAN}   大小: $size (${size_mb}MB), 行数: $lines${NC}"
            echo -e "${CYAN}   修改时间: $modified${NC}"
            
            # 检查日志轮转状态
            if command -v analyze_log_rotation_status >/dev/null 2>&1; then
                analyze_log_rotation_status "$log_file"
            fi
            
            # 检查文件大小
            local max_size_mb=${LOG_MAX_SIZE_MB:-100}
            if [ "${LOG_ROTATION_ENABLED:-false}" = "true" ]; then
                if [ "$size_mb" -gt "$((max_size_mb * 2))" ]; then
                    log_issue "warning" "文件过大 (${size_mb}MB)，超过轮转阈值的2倍"
                fi
            else
                if [ "$size_mb" -gt "$max_size_mb" ]; then
                    log_issue "warning" "文件过大 (${size_mb}MB)，建议启用日志轮转"
                fi
            fi
            
            # 检查最近错误
            local recent_errors=$(tail -100 "$log_file" | grep -i "error\|exception\|failed" | wc -l)
            if [ "$recent_errors" -gt 0 ]; then
                log_issue "warning" "最近100行中发现 $recent_errors 个错误"
            else
                echo -e "${GREEN}   ✅ 最近无错误记录${NC}"
            fi
            
        else
            log_issue "warning" "日志文件不存在: $log_file"
        fi
    done
}

# 函数：执行日志轮转
rotate_logs() {
    local bot_filter=$1
    local force=$2
    local log_files=($(get_log_files "$bot_filter"))
    
    echo -e "${BOLD}${GREEN}=== 执行日志轮转 ===${NC}"
    
    if [ "${LOG_ROTATION_ENABLED:-false}" != "true" ]; then
        log_issue "warning" "日志轮转未启用，请先在配置中启用"
        return 1
    fi
    
    for log_file in "${log_files[@]}"; do
        if [ -z "$log_file" ] || [ ! -f "$log_file" ]; then
            continue
        fi
        
        local bot_name=$(basename "$log_file" | cut -d'_' -f1)
        echo -e "\n${PURPLE}🔄 轮转 $bot_name 日志:${NC}"
        
        local size_mb=$(du -m "$log_file" | cut -f1)
        local max_size_mb=${LOG_MAX_SIZE_MB:-100}
        
        if [ "$force" = "true" ] || [ "$size_mb" -gt "$max_size_mb" ]; then
            if manual_rotate_log "$log_file" "$bot"; then
                log_success "$bot_name 日志轮转完成"
            else
                log_issue "critical" "$bot_name 日志轮转失败"
            fi
        else
            echo -e "${CYAN}   文件大小 (${size_mb}MB) 未超过阈值 (${max_size_mb}MB)，跳过轮转${NC}"
        fi
    done
}

# 函数：清理旧日志
clean_old_logs() {
    local days=${1:-7}
    local force=$2
    
    echo -e "${BOLD}${GREEN}=== 清理旧日志文件 ===${NC}"
    echo -e "${CYAN}清理 $days 天前的日志文件...${NC}"
    
    local logs_dir="logs"
    if [ ! -d "$logs_dir" ]; then
        log_issue "warning" "日志目录不存在: $logs_dir"
        return 1
    fi
    
    # 查找旧的轮转日志文件
    local old_files=$(find "$logs_dir" -name "*.log.*" -type f -mtime +$days 2>/dev/null)
    
    if [ -z "$old_files" ]; then
        log_success "没有找到需要清理的旧日志文件"
        return 0
    fi
    
    echo -e "${YELLOW}找到以下旧日志文件:${NC}"
    echo "$old_files" | sed 's/^/   /'
    
    if [ "$force" != "true" ]; then
        echo -e "\n${YELLOW}确认删除这些文件吗? (y/N): ${NC}"
        read -r confirm
        if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
            echo -e "${CYAN}操作已取消${NC}"
            return 0
        fi
    fi
    
    local deleted_count=0
    while IFS= read -r file; do
        if [ -f "$file" ]; then
            rm "$file" && ((deleted_count++))
            echo -e "${GREEN}   已删除: $file${NC}"
        fi
    done <<< "$old_files"
    
    log_success "已删除 $deleted_count 个旧日志文件"
}

# 函数：查看日志
view_logs() {
    local bot_filter=$1
    local lines=${2:-50}
    local log_files=($(get_log_files "$bot_filter"))
    
    echo -e "${BOLD}${GREEN}=== 查看日志内容 ===${NC}"
    
    for log_file in "${log_files[@]}"; do
        if [ -z "$log_file" ] || [ ! -f "$log_file" ]; then
            continue
        fi
        
        local bot_name=$(basename "$log_file" | cut -d'_' -f1)
        echo -e "\n${PURPLE}📋 $bot_name 最新 $lines 行日志:${NC}"
        echo -e "${CYAN}文件: $log_file${NC}"
        echo -e "${YELLOW}$(printf '=%.0s' {1..80})${NC}"
        
        tail -n "$lines" "$log_file" | sed 's/^/   /'
        
        echo -e "${YELLOW}$(printf '=%.0s' {1..80})${NC}"
    done
}

# 函数：分析日志
analyze_logs() {
    local bot_filter=$1
    local log_files=($(get_log_files "$bot_filter"))
    
    echo -e "${BOLD}${GREEN}=== 日志内容分析 ===${NC}"
    
    for log_file in "${log_files[@]}"; do
        if [ -z "$log_file" ] || [ ! -f "$log_file" ]; then
            continue
        fi
        
        local bot_name=$(basename "$log_file" | cut -d'_' -f1)
        echo -e "\n${PURPLE}🔍 $bot_name 日志分析:${NC}"
        
        # 统计信息
        local total_lines=$(wc -l < "$log_file")
        local error_count=$(grep -i "error" "$log_file" | wc -l)
        local warning_count=$(grep -i "warning" "$log_file" | wc -l)
        local exception_count=$(grep -i "exception" "$log_file" | wc -l)
        
        echo -e "${CYAN}   总行数: $total_lines${NC}"
        echo -e "${CYAN}   错误数: $error_count${NC}"
        echo -e "${CYAN}   警告数: $warning_count${NC}"
        echo -e "${CYAN}   异常数: $exception_count${NC}"
        
        # 最近错误
        if [ "$error_count" -gt 0 ]; then
            echo -e "${YELLOW}   最近3个错误:${NC}"
            grep -i "error\|exception\|failed" "$log_file" | tail -3 | sed 's/^/     /'
        fi
        
        # 交易统计
        local trade_count=$(grep -i "trade\|order\|fill" "$log_file" | wc -l)
        if [ "$trade_count" -gt 0 ]; then
            echo -e "${CYAN}   交易相关记录: $trade_count${NC}"
        fi
        
        # 连接状态
        local connection_issues=$(grep -i "connection\|disconnect\|timeout" "$log_file" | wc -l)
        if [ "$connection_issues" -gt 0 ]; then
            echo -e "${YELLOW}   连接问题: $connection_issues${NC}"
        fi
    done
}

# 函数：显示配置
show_config() {
    echo -e "${BOLD}${GREEN}=== 日志配置信息 ===${NC}"
    
    echo -e "${CYAN}日志轮转配置:${NC}"
    echo -e "   启用状态: ${LOG_ROTATION_ENABLED:-false}"
    echo -e "   最大大小: ${LOG_MAX_SIZE_MB:-100}MB"
    echo -e "   保留数量: ${LOG_KEEP_COUNT:-5}"
    echo -e "   压缩启用: ${LOG_COMPRESS:-true}"
    
    echo -e "\n${CYAN}日志文件路径:${NC}"
    echo -e "   Paradex: ${PARADEX_LOG_FILE:-未配置}"
    echo -e "   GRVT: ${GRVT_LOG_FILE:-未配置}"
    echo -e "   Extended: ${EXTENDED_LOG_FILE:-未配置}"
    echo -e "   Lighter: ${LIGHTER_LOG_FILE:-未配置}"
    
    echo -e "\n${CYAN}日志目录:${NC}"
    if [ -d "logs" ]; then
        local log_count=$(find logs -name "*.log*" -type f | wc -l)
        local total_size=$(du -sh logs 2>/dev/null | cut -f1)
        echo -e "   目录: logs/ (存在)"
        echo -e "   文件数: $log_count"
        echo -e "   总大小: $total_size"
    else
        echo -e "   目录: logs/ (不存在)"
    fi
}

# 主函数
main() {
    local command=$1
    shift
    
    # 解析参数
    local bot_filter=""
    local lines=50
    local days=7
    local force=false
    
    while [[ $# -gt 0 ]]; do
        case $1 in
            --bot)
                bot_filter=$2
                shift 2
                ;;
            --lines)
                lines=$2
                shift 2
                ;;
            --days)
                days=$2
                shift 2
                ;;
            --force)
                force=true
                shift
                ;;
            *)
                echo -e "${RED}未知参数: $1${NC}"
                show_usage
                exit 1
                ;;
        esac
    done
    
    # 执行命令
    case $command in
        "status")
            show_log_status "$bot_filter"
            ;;
        "rotate")
            rotate_logs "$bot_filter" "$force"
            ;;
        "clean")
            clean_old_logs "$days" "$force"
            ;;
        "view")
            view_logs "$bot_filter" "$lines"
            ;;
        "analyze")
            analyze_logs "$bot_filter"
            ;;
        "config")
            show_config
            ;;
        "help"|"--help"|"-h"|"")
            show_usage
            ;;
        *)
            echo -e "${RED}未知命令: $command${NC}"
            show_usage
            exit 1
            ;;
    esac
    
    # 显示总结
    if [ "$TOTAL_ISSUES" -gt 0 ]; then
        echo -e "\n${BOLD}${YELLOW}=== 操作总结 ===${NC}"
        if [ "$CRITICAL_ISSUES" -gt 0 ]; then
            echo -e "${RED}发现 $CRITICAL_ISSUES 个严重问题，总计 $TOTAL_ISSUES 个问题${NC}"
        else
            echo -e "${YELLOW}发现 $TOTAL_ISSUES 个非严重问题${NC}"
        fi
    fi
}

# 检查参数并执行
if [ $# -eq 0 ]; then
    show_usage
    exit 0
fi

main "$@"