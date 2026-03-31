#!/usr/bin/env python3
"""
Export training data from OpenClaw sessions for LoRA fine-tuning.
Converts conversation history into instruction-following format.

Output format:
{
  "instruction": "user message",
  "output": "assistant response"
}

Usage:
    python3 export_training_data.py                    # Export all sessions
    python3 export_training_data.py --limit 100        # Limit to 100 pairs
    python3 export_training_data.py --output custom.jsonl
    python3 export_training_data.py --filter-tags clara,memoria  # Only specific tags
"""

import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from collections import defaultdict

# Paths
SESSIONS_DIR = Path.home() / ".qclaw/agents/main/sessions"
OUTPUT_DIR = Path.home() / ".qclaw/memoria/training_data"
DEFAULT_OUTPUT = OUTPUT_DIR / "training_data.jsonl"

# Filter patterns (exclude system messages, tool calls, etc.)
EXCLUDE_PATTERNS = [
    "toolCall",
    "toolResult",
    "thinking",
    "system",
    "custom",
]


def load_session(session_path: Path) -> list:
    """Load and parse a session JSONL file."""
    messages = []
    try:
        with open(session_path, 'r', encoding='utf-8') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    msg = json.loads(line)
                    messages.append(msg)
                except json.JSONDecodeError:
                    continue
    except Exception as e:
        print(f"⚠️  Failed to load {session_path}: {e}")
    return messages


def extract_text(content) -> str:
    """Extract text from message content (handles various formats)."""
    if isinstance(content, str):
        return content
    
    if isinstance(content, list):
        texts = []
        for item in content:
            if isinstance(item, dict):
                if item.get("type") == "text":
                    texts.append(item.get("text", ""))
            elif isinstance(item, str):
                texts.append(item)
        return " ".join(texts).strip()
    
    return ""


def extract_pairs(messages: list) -> list:
    """Extract user-assistant pairs from message history."""
    pairs = []
    user_msg = None
    
    for msg in messages:
        msg_type = msg.get("type")
        
        # Skip non-message types
        if msg_type != "message":
            continue
        
        message_data = msg.get("message", {})
        role = message_data.get("role")
        content = message_data.get("content", [])
        
        # Extract text
        text = extract_text(content)
        if not text:
            continue
        
        # Skip if content contains tool calls or system messages
        if isinstance(content, list):
            has_excluded = any(
                item.get("type") in EXCLUDE_PATTERNS 
                for item in content 
                if isinstance(item, dict)
            )
            if has_excluded:
                continue
        
        # 剥离 webchat metadata header，保留正文
        # 格式: "Sender (untrusted metadata):\n```json\n{...}\n```\n\n[时间戳] 正文"
        if "Sender (untrusted metadata)" in text:
            # 找到时间戳行之后的正文
            import re
            match = re.search(r'\[\w{3} \d{4}-\d{2}-\d{2}.*?\]\s*(.*)', text, re.DOTALL)
            if match:
                text = match.group(1).strip()
            else:
                continue  # 找不到正文就跳过

        # Collect user message
        if role == "user":
            user_msg = text
        
        # When we see assistant message, create pair
        elif role == "assistant" and user_msg:
            # Clean up text (remove metadata, truncate)
            user_text = user_msg[:2000].strip()  # 改成 2000
            assistant_text = text[:2000].strip()  # 也改成 2000
            
            # Skip very short responses (改成 50 字最小)
            if len(assistant_text) < 50:
                continue
            
            # Skip if still contains metadata
            if "Sender (untrusted metadata)" in user_text or "Sender (untrusted metadata)" in assistant_text:
                continue
            
            # 检查乱码（非法 UTF-8）
            try:
                user_text.encode('utf-8').decode('utf-8')
                assistant_text.encode('utf-8').decode('utf-8')
            except (UnicodeDecodeError, UnicodeEncodeError):
                continue
            
            pairs.append({
                "instruction": user_text,
                "output": assistant_text
            })
            
            user_msg = None
    
    return pairs


def process_sessions(limit: int = None, filter_tags: list = None) -> list:
    """Process all sessions and extract training pairs."""
    
    if not SESSIONS_DIR.exists():
        print(f"❌ Sessions directory not found: {SESSIONS_DIR}")
        return []
    
    all_pairs = []
    session_files = sorted(SESSIONS_DIR.glob("*.jsonl"))
    
    print(f"🔍 Found {len(session_files)} session files")
    
    for i, session_file in enumerate(session_files, 1):
        print(f"  [{i}/{len(session_files)}] Processing {session_file.name}...")
        
        messages = load_session(session_file)
        pairs = extract_pairs(messages)
        
        all_pairs.extend(pairs)
        
        if limit and len(all_pairs) >= limit:
            all_pairs = all_pairs[:limit]
            break
    
    print(f"\n✨ Extracted {len(all_pairs)} training pairs")
    
    return all_pairs


def save_training_data(pairs: list, output_path: Path):
    """Save training data in JSONL format."""
    
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w', encoding='utf-8') as f:
        for pair in pairs:
            f.write(json.dumps(pair, ensure_ascii=False) + '\n')
    
    print(f"💾 Saved to {output_path}")
    print(f"📊 Total lines: {len(pairs)}")
    
    # Print sample
    if pairs:
        print(f"\n📝 Sample pair:")
        print(f"  Instruction: {pairs[0]['instruction'][:100]}...")
        print(f"  Output: {pairs[0]['output'][:100]}...")


def analyze_data(pairs: list):
    """Analyze training data statistics."""
    
    if not pairs:
        return
    
    instruction_lengths = [len(p["instruction"].split()) for p in pairs]
    output_lengths = [len(p["output"].split()) for p in pairs]
    
    print(f"\n📈 Data Statistics:")
    print(f"  Total pairs: {len(pairs)}")
    print(f"  Avg instruction length: {sum(instruction_lengths) / len(pairs):.1f} words")
    print(f"  Avg output length: {sum(output_lengths) / len(pairs):.1f} words")
    print(f"  Min/Max instruction: {min(instruction_lengths)}/{max(instruction_lengths)} words")
    print(f"  Min/Max output: {min(output_lengths)}/{max(output_lengths)} words")


def main():
    parser = argparse.ArgumentParser(
        description="Export training data from OpenClaw sessions"
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Limit number of training pairs"
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT),
        help="Output file path (JSONL format)"
    )
    parser.add_argument(
        "--filter-tags",
        type=str,
        help="Filter by tags (comma-separated, not yet implemented)"
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        help="Show data statistics"
    )
    
    args = parser.parse_args()
    
    # Process sessions
    pairs = process_sessions(
        limit=args.limit,
        filter_tags=args.filter_tags.split(",") if args.filter_tags else None
    )
    
    if not pairs:
        print("❌ No training pairs extracted")
        return
    
    # Save
    output_path = Path(args.output)
    save_training_data(pairs, output_path)
    
    # Analyze
    if args.analyze:
        analyze_data(pairs)


if __name__ == "__main__":
    main()
