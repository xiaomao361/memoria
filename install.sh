#!/bin/bash
# Memoria 一键安装脚本
# 用法：curl -fsSL https://raw.githubusercontent.com/xiaomao361/memoria/main/install.sh | bash

set -e

MEMORIA_DIR="$HOME/.qclaw/skills/memoria"
REPO="git@github.com:xiaomao361/memoria.git"

echo "🚀 开始安装 Memoria..."

# 1. 克隆或更新仓库
if [ -d "$MEMORIA_DIR/.git" ]; then
    echo "📥 更新已有安装..."
    cd "$MEMORIA_DIR"
    git pull --rebase origin main
else
    echo "📥 克隆仓库..."
    mkdir -p "$(dirname "$MEMORIA_DIR")"
    git clone "$REPO" "$MEMORIA_DIR"
    cd "$MEMORIA_DIR"
fi

# 2. 安装 Python 依赖（如有）
if [ -f "requirements.txt" ]; then
    echo "📦 安装依赖..."
    pip3 install -r requirements.txt -q
fi

# 3. 初始化数据目录
echo "🗂️  初始化数据目录..."
mkdir -p "$MEMORIA_DIR/memoria_full"
if [ ! -f "$MEMORIA_DIR/memoria.json" ]; then
    echo '{"memories": [], "version": "1.0"}' > "$MEMORIA_DIR/memoria.json"
fi

# 4. 自动集成到 Claw 配置
echo "🔧 集成到 Claw 配置..."
python3 "$MEMORIA_DIR/scripts/integrate_with_claw.py"

echo ""
echo "✅ Memoria 安装完成！"
echo ""
echo "使用方式："
echo "  检索记忆：python3 ~/.qclaw/skills/memoria/scripts/recall.py --days 7 --limit 5"
echo "  写入记忆：python3 ~/.qclaw/skills/memoria/scripts/remember.py --help"
echo "  同步记忆：python3 ~/.qclaw/skills/memoria/scripts/sync_to_memory.py"
