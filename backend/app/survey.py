"""平台发展问卷的题目定义与答案校验

题目只在这里定义一次：公开页从 /api/survey/schema 取题并渲染，
管理后台也按同一份定义把存下来的答案翻译成可读文本，前后端不会漂移。
"""
import json

SURVEY_VERSION = 1
SURVEY_INTRO = "这份问卷用来了解大家对平台发展的真实想法，大约需要两分钟，所有题目仅用于产品改进。"

QUESTIONS = [
    {
        "key": "frequency",
        "title": "你使用本站的频率",
        "type": "single",
        "required": True,
        "options": [
            {"value": "daily", "label": "几乎每天"},
            {"value": "weekly", "label": "每周多次"},
            {"value": "monthly", "label": "每周一次"},
            {"value": "occasionally", "label": "偶尔使用"},
            {"value": "new", "label": "刚加入不久"},
        ],
    },
    {
        "key": "modules",
        "title": "你最常使用哪些模块",
        "type": "multi",
        "required": True,
        "min": 1,
        "max": 6,
        "options": [
            {"value": "weather", "label": "航情与航路查询"},
            {"value": "events", "label": "连飞活动"},
            {"value": "airlines", "label": "虚拟航司经营"},
            {"value": "career", "label": "飞行生涯与成就"},
            {"value": "service", "label": "工单与申请"},
            {"value": "shop", "label": "商城与钱包"},
        ],
    },
    {
        "key": "satisfaction",
        "title": "你对平台整体的满意度",
        "type": "rating",
        "required": True,
        "min": 1,
        "max": 5,
        "lowLabel": "还有差距",
        "highLabel": "非常满意",
    },
    {
        "key": "priorities",
        "title": "你最希望平台优先发展的方向",
        "type": "multi",
        "required": True,
        "min": 1,
        "max": 3,
        "hint": "最多选三项",
        "options": [
            {"value": "atc", "label": "连飞活动与管制"},
            {"value": "economy", "label": "航司经营与经济系统"},
            {"value": "tools", "label": "航路与签派工具"},
            {"value": "training", "label": "培训与考核体系"},
            {"value": "community", "label": "社区与内容"},
            {"value": "mobile", "label": "移动端体验"},
        ],
    },
    {
        "key": "wishlist",
        "title": "你希望新增或改进什么功能",
        "type": "text",
        "required": True,
        "minLength": 5,
        "maxLength": 500,
        "placeholder": "例如：希望增加机组排班，或者让航路查询支持更多机型",
    },
    {
        "key": "advice",
        "title": "对平台发展还有什么建议",
        "type": "text",
        "required": False,
        "maxLength": 1000,
        "placeholder": "选填，任何想法都可以写在这里",
    },
]

QUESTIONS_BY_KEY = {q["key"]: q for q in QUESTIONS}


def public_schema() -> dict:
    """给公开页的题目结构，不含任何服务端字段"""
    return {
        "version": SURVEY_VERSION,
        "intro": SURVEY_INTRO,
        "questions": QUESTIONS,
    }


def _option_map(question: dict) -> dict:
    return {o["value"]: o["label"] for o in question.get("options", [])}


def validate_answers(raw) -> dict:
    """校验并归一化答案；非法输入抛 ValueError，消息可直接展示"""
    if not isinstance(raw, dict):
        raise ValueError("答案格式不正确")
    normalized: dict = {}
    for question in QUESTIONS:
        key = question["key"]
        value = raw.get(key)
        qtype = question["type"]
        required = question.get("required", False)
        if qtype == "single":
            if value in (None, ""):
                if required:
                    raise ValueError(f"请完成「{question['title']}」")
                continue
            if value not in _option_map(question):
                raise ValueError(f"「{question['title']}」的选项不支持")
            normalized[key] = value
        elif qtype == "multi":
            if value in (None, "", []):
                if required:
                    raise ValueError(f"请完成「{question['title']}」")
                continue
            if not isinstance(value, list):
                raise ValueError(f"「{question['title']}」的答案格式不正确")
            options = _option_map(question)
            picked = []
            for item in value:
                if item not in options:
                    raise ValueError(f"「{question['title']}」的选项不支持")
                if item not in picked:
                    picked.append(item)
            if "min" in question and len(picked) < question["min"]:
                raise ValueError(f"「{question['title']}」至少选择 {question['min']} 项")
            if "max" in question and len(picked) > question["max"]:
                raise ValueError(f"「{question['title']}」最多选择 {question['max']} 项")
            normalized[key] = picked
        elif qtype == "rating":
            if value in (None, ""):
                if required:
                    raise ValueError(f"请完成「{question['title']}」")
                continue
            try:
                score = int(value)
            except (TypeError, ValueError):
                raise ValueError(f"「{question['title']}」的答案格式不正确")
            if not question["min"] <= score <= question["max"]:
                raise ValueError(f"「{question['title']}」的取值超出范围")
            normalized[key] = score
        elif qtype == "text":
            text = (value or "").strip() if isinstance(value, str) else ""
            if not text:
                if required:
                    raise ValueError(f"请完成「{question['title']}」")
                continue
            if len(text) < question.get("minLength", 0):
                raise ValueError(f"「{question['title']}」至少填写 {question['minLength']} 个字")
            if len(text) > question["maxLength"]:
                raise ValueError(f"「{question['title']}」最多填写 {question['maxLength']} 个字")
            normalized[key] = text
        else:
            raise ValueError("题目类型不受支持")
    return normalized


def describe_answers(answers: dict) -> list:
    """把存下来的答案翻译成管理后台可读的条目"""
    items = []
    for question in QUESTIONS:
        key = question["key"]
        if key not in answers:
            continue
        value = answers[key]
        qtype = question["type"]
        if qtype == "single":
            display = _option_map(question).get(value, str(value))
        elif qtype == "multi":
            labels = _option_map(question)
            display = "、".join(labels.get(v, str(v)) for v in value)
        elif qtype == "rating":
            display = f"{value} 分"
        else:
            display = str(value)
        items.append({
            "key": key,
            "title": question["title"],
            "type": qtype,
            "value": value,
            "display": display,
        })
    return items


def parse_answers(text: str) -> dict:
    try:
        data = json.loads(text or "{}")
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def priority_counts(rows: list) -> list:
    """按优先级题统计各方向被选中的次数，用于管理后台概览"""
    question = QUESTIONS_BY_KEY["priorities"]
    labels = _option_map(question)
    counts = {o["value"]: 0 for o in question["options"]}
    for answers in rows:
        for value in answers.get("priorities") or []:
            if value in counts:
                counts[value] += 1
    return [
        {"value": value, "label": labels[value], "count": count}
        for value, count in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
