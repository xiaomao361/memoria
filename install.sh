#!/bin/bash
# Memoria 一键安装脚本
# 用法：curl -fsSL https://raw.githubusercontent.com/xiaomao361/memoria/main/install.sh | bash
#
# 多 Claw 安装（指定 workspace）：
#   WORKSPACE=~/.qclaw/agents/vera/workspace bash install.sh

set -e

# 解析配置
MEMORIA_DIR="${MEMORIA_DIR:-$HOME/.qclaw/skills/memoria}"
WORKSPACE="${WORKSPACE:-$HOME/.qclaw/workspace}"
REPO="${REPO:-git@github.com:xiaomao361/memoria.git}"

echo "🚀 开始安装 Memoria..."
echo "   数据目录: $MEMORIA_DIR"
echo "   工作空间: $WORKSPACE"
echo ""

# 1. 克隆或更新仓库
if [ -d "$MEMORIA_DIR/.git" ]; then
    echo "📥 更新已有安装..."
    cd "$MEMORIA_DIR"
    git pull --rebase origin main || echo "⚠️  更新失败，继续使用本地版本"
else
    echo "📥 克隆仓库..."
    mkdir -p "$(dirname "$MEMORIA_DIR")"
    git clone "$REPO" "$MEMORIA_DIR" || {
        echo "❌ 克隆失败，请检查网络或仓库地址"
        exit 1
    }
    cd "$MEMORIA_DIR"
fi

# 2. 初始化数据目录
echo "🗂️  初始化数据目录..."
mkdir -p "$MEMORIA_DIR/archive"
if [ ! -f "$MEMORIA_DIR/memoria.json" ]; then
    echo '{"memories": [], "version": "3.0"}' > "$MEMORIA_DIR/memoria.json"
    echo "✅ 已创建 memoria.json"
fi

# 3. 集成到 Claw 配置
echo "🔧 集成到 Claw 配置..."
export WORKSPACE
python3 "$MEMORIA_DIR/scripts/integrate_with_claw.py"

echo ""
echo "✅ Memoria 安装完成！"
echo ""
echo "使用方式："
echo "  检索记忆：python3 $MEMORIA_DIR/scripts/recall.py --days 7 --limit 5 --simple"
echo "  写入记忆：python3 $MEMORIA_DIR/scripts/remember.py --help"
echo ""
echo "多 Claw 使用示例："
echo "  export MEMORIA_DIR=~/.qclaw/agents/vera/memoria"
echo "  export WORKSPACE=~/.qclaw/agents/vera/workspace"
echo "  python3 \$MEMORIA_DIR/scripts/recall.py"
