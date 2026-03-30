#!/usr/bin/env python3
"""
Memoria 自动更新脚本

由 heartbeat 触发，检查并自动更新 Memoria 到最新版本。
"""

import subprocess
import sys
from pathlib import Path

def check_for_updates():
    """检查是否有更新"""
    repo_path = Path.home() / ".qclaw/skills/memoria"
    
    if not (repo_path / ".git").exists():
        return False
    
    # 获取远程最新 commit
    subprocess.run(["git", "fetch"], cwd=repo_path, capture_output=True)
    
    local_hash = subprocess.run(
        ["git", "rev-parse", "HEAD"], 
        cwd=repo_path, 
        capture_output=True, 
        text=True
    ).stdout.strip()
    
    remote_hash = subprocess.run(
        ["git", "rev-parse", "origin/main"], 
        cwd=repo_path, 
        capture_output=True, 
        text=True
    ).stdout.strip()
    
    return local_hash != remote_hash

def auto_update():
    """自动更新"""
    print("🔄 检查 Memoria 更新...")
    
    if check_for_updates():
        print("📥 发现新版本，正在更新...")
        repo_path = Path.home() / ".qclaw/skills/memoria"
        
        # 1. 拉取最新代码
        result = subprocess.run(
            ["git", "pull", "--rebase", "origin", "main"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"❌ 更新失败: {result.stderr}")
            return False
        
        # 2. 重新安装依赖
        result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-e", "."],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"❌ 依赖安装失败: {result.stderr}")
            return False
        
        # 3. 重新集成配置
        result = subprocess.run(
            [sys.executable, "scripts/integrate_with_claw.py", "--auto"],
            cwd=repo_path,
            capture_output=True,
            text=True
        )
        
        if result.returncode != 0:
            print(f"❌ 配置集成失败: {result.stderr}")
            return False
        
        print("✅ Memoria 更新完成！")
        return True
    else:
        print("📭 已是最新版本")
        return True

def main():
    """主函数"""
    try:
        success = auto_update()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"❌ 自动更新出错: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()