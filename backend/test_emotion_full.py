"""测试带情绪分镜表的完整解析"""
import sys, json
sys.path.insert(0, '.')
from app.services.importers import parse_storyboard_table

with open('data/storyboard_dialogues_emotion.txt', encoding='utf-8') as f:
    text = f.read()

shots = parse_storyboard_table(text)
print(f"解析出 {len(shots)} 个镜头\n")

emoji_map = {
    "中性": "😐", "高兴": "😊", "悲伤": "😢", "愤怒": "😠",
    "惊讶": "😲", "恐惧": "😨", "低语": "🤫", "激动": "🤩", "紧张": "😰",
}

total_dlgs = 0
for s in shots:
    dlgs = s.get('dialogues', [])
    total_dlgs += len(dlgs)
    if dlgs:
        print(f"镜{s['shot_no']} ({s.get('shot_size','')}): {len(dlgs)} 条对白")
        for d in dlgs:
            emoji = emoji_map.get(d['emotion'], "❓")
            print(f"  {emoji} [{d['character']}] ({d['emotion']}) {d['text'][:60]}")
    else:
        print(f"镜{s['shot_no']} ({s.get('shot_size','')}): 无对白")

print(f"\n总计对白: {total_dlgs} 条")

# 情绪分布统计
from collections import Counter
emotions = Counter()
for s in shots:
    for d in s.get('dialogues', []):
        emotions[d['emotion']] += 1
print(f"\n情绪分布: {dict(emotions)}")
