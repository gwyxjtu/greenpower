"""Parse and write 8760-hour load / PV / wind CSV templates."""
from __future__ import annotations

import csv
import io
from pathlib import Path

import numpy as np

EXPECTED_LEN = 8760
LEAP_LEN = 8784

HOUR_ALIASES = {"小时", "hour", "t", "时段", "index"}
LOAD_ALIASES = {"负荷（MW）", "负荷(MW)", "负荷兆瓦", "负荷", "load", "load_mw", "功率", "mw"}
PV_ALIASES = {"光伏出力系数", "光伏", "pv", "pv_cf", "alpha_pv", "出力系数"}
WT_ALIASES = {"风电出力系数", "风电", "wt", "wind", "wind_cf", "alpha_wt"}
KIND_ALIASES = {"load": LOAD_ALIASES, "pv": PV_ALIASES, "wt": WT_ALIASES}
KIND_HEADER = {
    "load": ("小时", "负荷（MW）"),
    "pv": ("小时", "光伏出力系数"),
    "wt": ("小时", "风电出力系数"),
}
KIND_LABEL = {"load": "负荷", "pv": "光伏", "wt": "风电"}


class SeriesFormatError(ValueError):
    pass


def _norm_name(name):
    return str(name).strip().lstrip("\ufeff").lower()


def _read_table(data):
    if isinstance(data, (bytes, bytearray)):
        text = data.decode("utf-8-sig")
    elif isinstance(data, Path):
        text = data.read_text(encoding="utf-8-sig")
    elif isinstance(data, str) and len(data) < 4096 and Path(data).is_file():
        text = Path(data).read_text(encoding="utf-8-sig")
    else:
        text = str(data)
    sample = text.lstrip()
    if not sample:
        raise SeriesFormatError("文件是空的。")
    reader = csv.reader(io.StringIO(text))
    rows = [row for row in reader if any(cell.strip() for cell in row)]
    if not rows:
        raise SeriesFormatError("文件里没有有效数据行。")
    return rows


def _pick_value_col(header, kind):
    names = [_norm_name(h) for h in header]
    aliases = {_norm_name(a) for a in KIND_ALIASES[kind]}
    hour_aliases = {_norm_name(a) for a in HOUR_ALIASES}
    for i, name in enumerate(names):
        if name in aliases:
            return i
    if len(header) == 1:
        return 0
    if len(header) >= 2 and names[0] in hour_aliases:
        return 1
    if len(header) == 2:
        return 1
    raise SeriesFormatError(
        f"{KIND_LABEL[kind]}表缺少数值列。请使用模板表头："
        f"{KIND_HEADER[kind][0]},{KIND_HEADER[kind][1]}"
    )


def parse_series(data, kind, expected_len=EXPECTED_LEN):
    """
    Return a 1-D float array of length expected_len.
    kind: 'load' (MW), 'pv' or 'wt' (capacity factor 0-1).
    """
    if kind not in KIND_ALIASES:
        raise SeriesFormatError("内部错误：未知时序类型。")
    rows = _read_table(data)
    header = rows[0]
    try:
        float(str(header[0]).strip())
        body = rows
        value_col = 0 if len(header) == 1 else 1
    except ValueError:
        body = rows[1:]
        value_col = _pick_value_col(header, kind)

    if len(body) == LEAP_LEN:
        raise SeriesFormatError("检测到 8784 行（闰年）。请删除 2 月 29 日，只保留 8760 小时。")
    if len(body) != expected_len:
        raise SeriesFormatError(
            f"{KIND_LABEL[kind]}应为 {expected_len} 行，当前是 {len(body)} 行。"
        )

    values = []
    for i, row in enumerate(body):
        if value_col >= len(row) or str(row[value_col]).strip() == "":
            raise SeriesFormatError(f"{KIND_LABEL[kind]}第 {i + 1} 行缺少数值。")
        try:
            values.append(float(str(row[value_col]).strip()))
        except ValueError:
            raise SeriesFormatError(f"{KIND_LABEL[kind]}第 {i + 1} 行不是数字：{row[value_col]}")
    arr = np.asarray(values, dtype=float)
    if not np.isfinite(arr).all():
        raise SeriesFormatError(f"{KIND_LABEL[kind]}含有非有限数值。")
    if kind == "load":
        if arr.min() < -1e-6:
            raise SeriesFormatError("负荷不能为负数。")
        arr = np.clip(arr, 0.0, None)
    else:
        if arr.min() < -1e-6 or arr.max() > 1.0 + 1e-6:
            raise SeriesFormatError(
                f"{KIND_LABEL[kind]}出力系数必须在 0 到 1 之间（当前最小 {arr.min():.4f}，最大 {arr.max():.4f}）。"
            )
        arr = np.clip(arr, 0.0, 1.0)
    return arr


def write_template_csv(kind, values=None):
    hour_h, value_h = KIND_HEADER[kind]
    if values is None:
        values = np.zeros(EXPECTED_LEN)
    values = np.asarray(values, dtype=float)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow([hour_h, value_h])
    for i, v in enumerate(values):
        writer.writerow([i, f"{float(v):.6g}"])
    return buf.getvalue()


def summarize(kind, values):
    arr = np.asarray(values, dtype=float)
    if kind == "load":
        return (
            f"已读取 {len(arr)} 小时；最小 {arr.min():.2f} MW，"
            f"最大 {arr.max():.2f} MW，平均 {arr.mean():.2f} MW。"
        )
    hours = float(arr.sum())
    return (
        f"已读取 {len(arr)} 小时；出力系数最小 {arr.min():.3f}、最大 {arr.max():.3f}，"
        f"年等效利用小时约 {hours:.0f} 小时。"
    )
