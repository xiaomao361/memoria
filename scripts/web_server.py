#!/usr/bin/env python3
"""
Memoria Web 管理界面

启动:
    python3 web_server.py
    python3 web_server.py --port 8080
    python3 web_server.py --private  # 管理私密区

访问: http://localhost:8000
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "lib"))

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import uvicorn

from lib.manage_ops import (
    load_all_memories, delete_memory, merge_memories, 
    update_tags, find_duplicates, normalize_all_tags, get_stats
)

app = FastAPI(title="Memoria Manager")

# 全局配置
CONFIG = {"private": False}


@app.get("/", response_class=HTMLResponse)
async def index():
    return """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Memoria Manager</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body { 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
            background: #0d1117; 
            color: #c9d1d9;
            line-height: 1.6;
        }
        .container { max-width: 1400px; margin: 0 auto; padding: 20px; }
        header { 
            border-bottom: 1px solid #30363d; 
            padding-bottom: 20px; 
            margin-bottom: 30px;
            display: flex;
            justify-content: space-between;
            align-items: center;
        }
        h1 { color: #58a6ff; font-size: 24px; }
        .stats { 
            display: grid; 
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px; 
            margin-bottom: 30px;
        }
        .stat-card { 
            background: #161b22; 
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
        }
        .stat-card h3 { color: #8b949e; font-size: 12px; text-transform: uppercase; }
        .stat-card .value { font-size: 32px; font-weight: bold; color: #58a6ff; }
        .actions { 
            display: flex; 
            gap: 10px; 
            margin-bottom: 20px;
            flex-wrap: wrap;
        }
        button {
            background: #238636;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
        }
        button:hover { background: #2ea043; }
        button.secondary { background: #1f6feb; }
        button.secondary:hover { background: #388bfd; }
        button.danger { background: #da3633; }
        button.danger:hover { background: #f85149; }
        .search-box {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 10px 15px;
            color: #c9d1d9;
            width: 300px;
            margin-bottom: 20px;
        }
        table {
            width: 100%;
            border-collapse: collapse;
            background: #161b22;
            border-radius: 8px;
            overflow: hidden;
        }
        th, td {
            padding: 12px;
            text-align: left;
            border-bottom: 1px solid #30363d;
        }
        th {
            background: #21262d;
            color: #8b949e;
            font-weight: 500;
            font-size: 12px;
            text-transform: uppercase;
        }
        tr:hover { background: #1c2128; }
        .tag {
            display: inline-block;
            background: #388bfd33;
            color: #58a6ff;
            padding: 2px 8px;
            border-radius: 12px;
            font-size: 12px;
            margin-right: 4px;
        }
        .id { font-family: monospace; color: #8b949e; font-size: 12px; }
        .summary { max-width: 400px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
        .modal {
            display: none;
            position: fixed;
            top: 0; left: 0; width: 100%; height: 100%;
            background: rgba(0,0,0,0.8);
            z-index: 100;
            justify-content: center;
            align-items: center;
        }
        .modal.active { display: flex; }
        .modal-content {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 12px;
            padding: 30px;
            max-width: 600px;
            width: 90%;
            max-height: 80vh;
            overflow-y: auto;
        }
        .modal h2 { margin-bottom: 20px; color: #f85149; }
        .form-group { margin-bottom: 15px; }
        .form-group label { display: block; margin-bottom: 5px; color: #8b949e; }
        .form-group input, .form-group textarea {
            width: 100%;
            background: #0d1117;
            border: 1px solid #30363d;
            border-radius: 6px;
            padding: 10px;
            color: #c9d1d9;
        }
        .toast {
            position: fixed;
            bottom: 20px;
            right: 20px;
            background: #238636;
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            display: none;
        }
        .toast.error { background: #da3633; }
        .toast.show { display: block; }
        .dupe-row { background: #da36331a !important; }
        .checkbox { width: 20px; }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🧠 Memoria Manager</h1>
            <span id="zone-badge">Public Zone</span>
        </header>
        
        <div class="stats" id="stats">
            <div class="stat-card">
                <h3>Total Memories</h3>
                <div class="value" id="stat-total">-</div>
            </div>
            <div class="stat-card">
                <h3>In Hot Cache</h3>
                <div class="value" id="stat-hot">-</div>
            </div>
            <div class="stat-card">
                <h3>Duplicates</h3>
                <div class="value" id="stat-dupes">-</div>
            </div>
            <div class="stat-card">
                <h3>Need Tag Fix</h3>
                <div class="value" id="stat-tags">-</div>
            </div>
        </div>
        
        <div class="actions">
            <button onclick="loadMemories()">🔄 Refresh</button>
            <button class="secondary" onclick="showDupes()">🔍 Find Duplicates</button>
            <button class="secondary" onclick="normalizeTags()">🏷️ Normalize Tags</button>
            <button class="danger" onclick="showDeleteSelected()">🗑️ Delete Selected</button>
        </div>
        
        <input type="text" class="search-box" id="search" placeholder="Search memories..." onkeyup="filterMemories()">
        
        <table>
            <thead>
                <tr>
                    <th class="checkbox"><input type="checkbox" id="select-all" onchange="toggleSelectAll()"></th>
                    <th>ID</th>
                    <th>Summary</th>
                    <th>Tags</th>
                    <th>Source</th>
                    <th>Actions</th>
                </tr>
            </thead>
            <tbody id="memories-list">
            </tbody>
        </table>
    </div>
    
    <div class="modal" id="dupe-modal">
        <div class="modal-content">
            <h2>Duplicate Detection</h2>
            <div id="dupe-list"></div>
            <button onclick="closeModal()">Close</button>
        </div>
    </div>
    
    <div class="toast" id="toast"></div>
    
    <script>
        let allMemories = [];
        let selectedIds = new Set();
        
        async function loadMemories() {
            const res = await fetch('/api/memories');
            allMemories = await res.json();
            renderMemories(allMemories);
            updateStats();
        }
        
        function renderMemories(memories) {
            const tbody = document.getElementById('memories-list');
            tbody.innerHTML = memories.map(m => `
                <tr data-id="${m.memory_id}">
                    <td><input type="checkbox" ${selectedIds.has(m.memory_id) ? 'checked' : ''} onchange="toggleSelect('${m.memory_id}')"></td>
                    <td class="id">${m.memory_id.slice(0, 8)}</td>
                    <td class="summary" title="${m.summary || ''}">${m.summary || '(no summary)'}</td>
                    <td>${(m.tags || []).map(t => `<span class="tag">${t}</span>`).join('')}</td>
                    <td>${m.source || '-'}</td>
                    <td>
                        <button class="danger" onclick="deleteMemory('${m.memory_id}')">Delete</button>
                    </td>
                </tr>
            `).join('');
        }
        
        function filterMemories() {
            const query = document.getElementById('search').value.toLowerCase();
            const filtered = allMemories.filter(m => 
                (m.summary || '').toLowerCase().includes(query) ||
                (m.tags || []).some(t => t.toLowerCase().includes(query))
            );
            renderMemories(filtered);
        }
        
        function toggleSelect(id) {
            if (selectedIds.has(id)) selectedIds.delete(id);
            else selectedIds.add(id);
        }
        
        function toggleSelectAll() {
            const checked = document.getElementById('select-all').checked;
            if (checked) {
                allMemories.forEach(m => selectedIds.add(m.memory_id));
            } else {
                selectedIds.clear();
            }
            renderMemories(allMemories);
        }
        
        async function updateStats() {
            const res = await fetch('/api/stats');
            const stats = await res.json();
            document.getElementById('stat-total').textContent = stats.total;
            document.getElementById('stat-hot').textContent = stats.hot_cache;
            
            const dupeRes = await fetch('/api/dupes?threshold=1.0');
            const dupes = await dupeRes.json();
            document.getElementById('stat-dupes').textContent = dupes.length;
        }
        
        async function deleteMemory(id) {
            if (!confirm('Delete this memory?')) return;
            const res = await fetch(`/api/memories/${id}`, { method: 'DELETE' });
            const result = await res.json();
            if (result.success) {
                showToast('Deleted successfully');
                loadMemories();
            } else {
                showToast(result.message, true);
            }
        }
        
        async function showDupes() {
            const res = await fetch('/api/dupes?threshold=0.8');
            const dupes = await res.json();
            const list = document.getElementById('dupe-list');
            if (dupes.length === 0) {
                list.innerHTML = '<p>No duplicates found!</p>';
            } else {
                list.innerHTML = dupes.map(d => `
                    <div style="margin-bottom: 15px; padding: 15px; background: #0d1117; border-radius: 6px;">
                        <div style="color: #f85149; font-weight: bold;">${(d.similarity * 100).toFixed(0)}% Similar</div>
                        <div style="font-size: 12px; color: #8b949e; margin-top: 5px;">${d.id1.slice(0, 8)} ↔ ${d.id2.slice(0, 8)}</div>
                        <div style="margin-top: 10px;">${d.summary1}</div>
                        <div style="margin-top: 5px; color: #8b949e;">${d.summary2}</div>
                        <button class="danger" style="margin-top: 10px;" onclick="mergeDupes('${d.id1}', '${d.id2}')">Merge</button>
                    </div>
                `).join('');
            }
            document.getElementById('dupe-modal').classList.add('active');
        }
        
        async function mergeDupes(id1, id2) {
            const content = prompt('Enter merged content:');
            if (!content) return;
            const res = await fetch('/api/merge', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ id1, id2, content })
            });
            const result = await res.json();
            if (result.success) {
                showToast('Merged successfully');
                closeModal();
                loadMemories();
            } else {
                showToast(result.message, true);
            }
        }
        
        async function normalizeTags() {
            if (!confirm('Normalize all tags to lowercase?')) return;
            const res = await fetch('/api/normalize-tags', { method: 'POST' });
            const result = await res.json();
            showToast(`Normalized ${result.changed} memories`);
            loadMemories();
        }
        
        async function showDeleteSelected() {
            if (selectedIds.size === 0) {
                showToast('No memories selected', true);
                return;
            }
            if (!confirm(`Delete ${selectedIds.size} selected memories?`)) return;
            
            let deleted = 0;
            for (const id of selectedIds) {
                const res = await fetch(`/api/memories/${id}`, { method: 'DELETE' });
                const result = await res.json();
                if (result.success) deleted++;
            }
            selectedIds.clear();
            showToast(`Deleted ${deleted} memories`);
            loadMemories();
        }
        
        function closeModal() {
            document.getElementById('dupe-modal').classList.remove('active');
        }
        
        function showToast(msg, error = false) {
            const toast = document.getElementById('toast');
            toast.textContent = msg;
            toast.className = error ? 'toast error show' : 'toast show';
            setTimeout(() => toast.classList.remove('show'), 3000);
        }
        
        loadMemories();
    </script>
</body>
</html>"""


@app.get("/api/memories")
async def api_memories():
    memories = load_all_memories(private=CONFIG["private"])
    return memories


@app.get("/api/stats")
async def api_stats():
    return get_stats(private=CONFIG["private"])


@app.get("/api/dupes")
async def api_dupes(threshold: float = 0.8):
    return find_duplicates(threshold=threshold, private=CONFIG["private"])


@app.delete("/api/memories/{memory_id}")
async def api_delete(memory_id: str):
    result = delete_memory(memory_id, private=CONFIG["private"])
    return result


@app.post("/api/merge")
async def api_merge(request: Request):
    data = await request.json()
    result = merge_memories(
        data["id1"], 
        data["id2"], 
        data.get("content", ""),
        private=CONFIG["private"]
    )
    return result


@app.post("/api/normalize-tags")
async def api_normalize():
    result = normalize_all_tags(private=CONFIG["private"], dry_run=False)
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--private", action="store_true")
    args = parser.parse_args()
    
    CONFIG["private"] = args.private
    
    if args.private:
        print("🔒 Private Zone Mode")
    else:
        print("🌐 Public Zone Mode")
    
    print(f"Starting server at http://localhost:{args.port}")
    uvicorn.run(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
