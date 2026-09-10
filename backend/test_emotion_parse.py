"""测试情绪解析功能"""
import sys
sys.path.insert(0, '.')
from app.services.importers import _parse_dialogues

test_cases = [
    # 1. 开头带情绪
    "林渊：（紧张）师父人呢？",
    # 2. 结尾带情绪
    "阿瑶：师兄师兄！（激动）",
    # 3. 无情绪
    "字幕：“当世间再无人记得，历史便真正死去。”",
    # 4. 多角色多情绪
    "林渊：（紧张）师父人呢？\n阿瑶：在后山闭关呢，说让你自己悟。（压低声音）",
    # 5. 混合格式
    "长老：宗主，他们来了！（焦急）这次挡不住了！",
    # 6. 表演提示
    "林渊：（将阿瑶推到身后）闭眼，捂住耳朵。",
    # 7. 英文情绪
    "阿瑶：（happy）我成功了！",
    # 8. 复杂情绪词
    "林北望：（悲恸）守忆宗已经不在了……",
]

print("=" * 70)
for i, tc in enumerate(test_cases, 1):
    print(f"\n测试 {i}: {tc}")
    result = _parse_dialogues(tc)
    for d in result:
        emoji_map = {
            "中性": "😐", "高兴": "😊", "悲伤": "😢", "愤怒": "😠",
            "惊讶": "😲", "恐惧": "😨", "低语": "🤫", "激动": "🤩", "紧张": "😰",
        }
        emoji = emoji_map.get(d["emotion"], "❓")
        print(f"  {emoji} [{d['character']}] ({d['emotion']}) {d['text'][:50]}")
