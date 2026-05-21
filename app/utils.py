import re
from typing import Iterable


PUNCT_EDGE_RE = re.compile(r"^[\s\.,!?;:'\"()\[\]{}<>«»]+|[\s\.,!?;:'\"()\[\]{}<>«»]+$")
PUNCT_ANY_RE = re.compile(r"[^\w\s]", flags=re.UNICODE)
MULTISPACE_RE = re.compile(r'\s+')
NUMBER_WORDS_RE = re.compile(
    r'\b(ноль|один|одна|одно|два|две|три|четыре|пять|шесть|семь|восемь|девять|десять)\b'
)
NUMBER_WORDS_MAP = {
    'ноль': '0',
    'один': '1',
    'одна': '1',
    'одно': '1',
    'два': '2',
    'две': '2',
    'три': '3',
    'четыре': '4',
    'пять': '5',
    'шесть': '6',
    'семь': '7',
    'восемь': '8',
    'девять': '9',
    'десять': '10',
}


def normalize_text(text: str) -> str:
    text = text.lower().replace('ё', 'е')
    text = PUNCT_ANY_RE.sub(' ', text)
    text = PUNCT_EDGE_RE.sub('', text)
    text = MULTISPACE_RE.sub(' ', text)
    text = NUMBER_WORDS_RE.sub(lambda m: NUMBER_WORDS_MAP[m.group(1)], text)
    return text.strip()


def unique_hidden_letters(answer: str, opened: Iterable[str]) -> list[str]:
    opened_set = set(opened)
    out: list[str] = []
    seen: set[str] = set()
    for ch in answer:
        low = ch.lower().replace('ё', 'е')
        if not ch.isalnum():
            continue
        if low in opened_set or low in seen:
            continue
        seen.add(low)
        out.append(low)
    return out
