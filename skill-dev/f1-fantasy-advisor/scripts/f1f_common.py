#!/usr/bin/env python3
"""f1-fantasy-advisor 各脚本共享的工具函数与常量（仅标准库）。"""

from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Callable, Iterable, Sequence, TypeVar


ZERO = Decimal("0")
DRIVERS_PER_LINEUP = 5
CONSTRUCTORS_PER_LINEUP = 2
LINEUP_SIZE = DRIVERS_PER_LINEUP + CONSTRUCTORS_PER_LINEUP
DEFAULT_FREE_TRANSFERS = 2
DEFAULT_PENALTY_PER_EXTRA = "10"

T = TypeVar("T")


def decimal_value(raw: object, field: str) -> Decimal:
    """把 CSV、网页或命令行里的数字文本转成 Decimal。"""
    value = "" if raw is None else str(raw).strip()
    value = (
        value.replace("$", "")
        .replace("M", "")
        .replace(",", "")
        .replace("▲", "")
        .replace("▼", "")
        .replace("+", "")
    )
    if value == "":
        raise ValueError(f"Missing numeric value for {field}")
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"Invalid numeric value for {field}: {raw!r}") from exc


def fmt_decimal(value: Decimal, places: str | None = "0.1") -> str:
    """按网页价格/分数习惯格式化 Decimal；places=None 时保留原始精度。"""
    if places is None:
        quantized = value
    else:
        quantized = value.quantize(Decimal(places), rounding=ROUND_HALF_UP)
    if quantized == ZERO:
        return "0"
    if quantized == quantized.to_integral_value():
        return str(quantized.quantize(Decimal("1")))
    return format(quantized.normalize(), "f")


def normalize_name(value: str) -> str:
    """把名称转成适合模糊匹配的小写单空格文本。"""
    return " ".join(value.lower().replace(".", "").split())


def initials_for(value: str) -> str:
    """生成名称首字母缩写，例如 Lewis Hamilton -> lh。"""
    return "".join(part[0] for part in normalize_name(value).split() if part)


def split_ids(value: str) -> list[str]:
    """把逗号、分号、竖线或斜杠分隔的文本拆成列表。"""
    cleaned = value.replace(";", ",").replace("|", ",").replace("/", ",")
    return [item.strip() for item in cleaned.split(",") if item.strip()]


def read_csv(path: Path, required: Sequence[str] | None = None) -> list[dict[str, str]]:
    """读取 CSV 并去掉单元格两端空白；可校验必需列并拒绝畸形行。"""
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return []
        if required:
            missing = [column for column in required if column not in reader.fieldnames]
            if missing:
                raise ValueError(f"{path} is missing columns: {', '.join(missing)}")
        rows: list[dict[str, str]] = []
        for line_number, row in enumerate(reader, start=2):
            if row.get(None):
                raise ValueError(
                    f"{path} row {line_number} has more cells than the header"
                )
            row.pop(None, None)
            rows.append(
                {key: (value or "").strip() for key, value in row.items()}
            )
        return rows


def write_csv(path: Path, fieldnames: list[str], rows: Iterable[dict[str, str]]) -> None:
    """写出 CSV，只保留 fieldnames 中列出的列。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: row.get(field, "") for field in fieldnames})


def load_round_context(official_dir: Path) -> dict[str, str]:
    """读取目标周上下文；没有文件时返回空字典。"""
    path = official_dir / "official_round_context.csv"
    if not path.exists():
        return {}
    rows = read_csv(path)
    return rows[0] if rows else {}


def prompt_loop(prompt_text: str, parse: Callable[[str], T]) -> T:
    """循环读取输入直到 parse 成功；EOF 转成 ValueError 以便干净退出。"""
    while True:
        try:
            raw = input(prompt_text)
        except EOFError as exc:
            raise ValueError("input aborted (EOF)") from exc
        try:
            return parse(raw)
        except ValueError as exc:
            print(f"error: {exc}")
