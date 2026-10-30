"""文本输入清洗：去控制字符/空字节，防存储型脏数据"""


def clean(s: str, max_len: int = 500) -> str:
    if not isinstance(s, str):
        return ""
    out = []
    for ch in s:
        if ch in ("\t", "\n", "\r") or ord(ch) > 31:
            out.append(ch)
    return "".join(out).strip()[:max_len]


def csv_safe(value) -> str:
    """防 CSV 公式注入：Excel 把以 = + - @ 制表符开头的单元格当公式执行"""
    s = str(value)
    return "'" + s if s[:1] in ("=", "+", "-", "@", "\t") else s
