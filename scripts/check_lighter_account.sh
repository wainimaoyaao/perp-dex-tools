#!/bin/bash
# Lighter 账户信息检查脚本

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# 获取项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo -e "${GREEN}=== Lighter 账户信息检查工具 ===${NC}"
echo -e "${BLUE}检查时间: $(date)${NC}"
echo -e "${BLUE}工作目录: $PROJECT_ROOT${NC}"
echo ""

# 检查环境变量文件
if [ ! -f ".env" ]; then
    echo -e "${RED}❌ 错误: .env 文件不存在!${NC}"
    echo -e "${YELLOW}请先创建 .env 文件并配置 Lighter 相关变量${NC}"
    exit 1
fi

# 检查虚拟环境
if [ ! -f "./env/bin/python3" ]; then
    echo -e "${RED}❌ 错误: 虚拟环境不存在!${NC}"
    echo -e "${YELLOW}请运行: python3 -m venv env && source env/bin/activate && pip install -r requirements.txt${NC}"
    exit 1
fi

# 检查必需的环境变量
echo -e "${CYAN}🔍 检查环境变量配置...${NC}"

# 加载环境变量
source .env 2>/dev/null || true

if [ -z "$API_KEY_PRIVATE_KEY" ]; then
    echo -e "${RED}❌ API_KEY_PRIVATE_KEY 未设置${NC}"
    echo -e "${YELLOW}请在 .env 文件中设置: API_KEY_PRIVATE_KEY=your_private_key${NC}"
    exit 1
else
    echo -e "${GREEN}✅ API_KEY_PRIVATE_KEY 已设置${NC}"
fi

if [ -z "$LIGHTER_ACCOUNT_INDEX" ]; then
    echo -e "${YELLOW}⚠️  LIGHTER_ACCOUNT_INDEX 未设置，使用默认值 0${NC}"
    export LIGHTER_ACCOUNT_INDEX=0
else
    echo -e "${GREEN}✅ LIGHTER_ACCOUNT_INDEX = $LIGHTER_ACCOUNT_INDEX${NC}"
fi

if [ -z "$LIGHTER_API_KEY_INDEX" ]; then
    echo -e "${YELLOW}⚠️  LIGHTER_API_KEY_INDEX 未设置，使用默认值 0${NC}"
    export LIGHTER_API_KEY_INDEX=0
else
    echo -e "${GREEN}✅ LIGHTER_API_KEY_INDEX = $LIGHTER_API_KEY_INDEX${NC}"
fi

echo ""
echo -e "${CYAN}🚀 运行账户信息检查工具...${NC}"
echo ""

# 运行账户信息检查工具
./env/bin/python3 get_lighter_account_info.py

exit_code=$?

echo ""
if [ $exit_code -eq 0 ]; then
    echo -e "${GREEN}✅ 账户信息检查完成${NC}"
    echo ""
    echo -e "${CYAN}📝 如何使用检查结果:${NC}"
    echo -e "${BLUE}1. 查看上面输出中的 'Working account indices'${NC}"
    echo -e "${BLUE}2. 在 .env 文件中更新 LIGHTER_ACCOUNT_INDEX${NC}"
    echo -e "${BLUE}3. 重新启动 Lighter 交易机器人${NC}"
    echo ""
    echo -e "${YELLOW}示例 .env 配置:${NC}"
    echo -e "${YELLOW}API_KEY_PRIVATE_KEY=your_private_key_here${NC}"
    echo -e "${YELLOW}LIGHTER_ACCOUNT_INDEX=0  # 使用检查结果中的正确索引${NC}"
    echo -e "${YELLOW}LIGHTER_API_KEY_INDEX=0${NC}"
else
    echo -e "${RED}❌ 账户信息检查失败${NC}"
    echo ""
    echo -e "${CYAN}🔧 故障排除建议:${NC}"
    echo -e "${BLUE}1. 检查 API_KEY_PRIVATE_KEY 是否正确${NC}"
    echo -e "${BLUE}2. 确认网络连接正常${NC}"
    echo -e "${BLUE}3. 验证 Lighter 账户设置是否正确${NC}"
    echo -e "${BLUE}4. 检查是否安装了所有依赖包${NC}"
fi

echo ""
echo -e "${CYAN}📚 相关命令:${NC}"
echo -e "${BLUE}  编辑配置: nano .env${NC}"
echo -e "${BLUE}  启动机器人: ./scripts/start_lighter.sh${NC}"
echo -e "${BLUE}  检查机器人: ./scripts/check_lighter.sh${NC}"