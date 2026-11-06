"""离线整理B站视频样本；不联网，不改原数据，不覆盖已有输出目录。"""

import argparse
import csv
import hashlib
import json
import math
import re
from collections import defaultdict
from pathlib import Path


DEFAULT_INPUT = Path(__file__).resolve().parent / "data/synthetic-videos.json"
COUNTS = ["views", "likes", "favorites", "comments", "danmaku", "coins", "shares"]
VIDEO_FIELDS = [
    "bvid", "title", "url", "authorMid", "authorName", "publishedAt",
    *COUNTS, "favorite_pct", "is_synthetic",
]
CREATOR_FIELDS = [
    "authorMid", "authorName", "profile_url", "sample_video_count",
    "observed_views_sum", "videos_with_views", "observed_likes_sum",
    "videos_with_likes", "representative_bvid", "representative_url",
    "representative_views", "has_review_candidate", "profile_status", "is_synthetic",
]
BV_PATTERN = re.compile(r"BV[0-9A-Za-z]{10}\Z")


def valid_count(value):
    """保留有限非负数；不把布尔值、负数或字符串计数当有效指标。"""
    if type(value) not in (int, float) or value < 0:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def creator_id(value):
    """ID不经过浮点转换；只接受正整数或十进制字符串。"""
    if type(value) is int and value > 0:
        return str(value)
    if isinstance(value, str) and re.fullmatch(r"[0-9]+", value) and int(value) > 0:
        return str(int(value))
    return None


def safe_cell(value):
    """在表格副本中保护外部文本，避免被Excel解释为公式；原JSON不变。"""
    if isinstance(value, str) and (value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n"))):
        return "'" + value
    return value


def build_tables(rows, min_views=1000):
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise ValueError("输入必须是JSON对象数组。")
    if type(min_views) is not int or min_views < 1:
        raise ValueError("最少播放数必须为正整数。")
    synthetic = bool(rows) and all(row.get("is_synthetic") is True for row in rows)
    if any(row.get("is_synthetic") is True for row in rows) and not synthetic:
        raise ValueError("不允许混合合成数据与外部数据；请分开分析。")
    seen = set()
    groups = defaultdict(list)
    videos = []
    review = []
    audit = {"non_video_rows": 0, "invalid_bv_rows": 0, "duplicate_bv_rows": 0, "videos_without_creator_id": 0}
    for source in rows:
        if source.get("type") != "video":
            audit["non_video_rows"] += 1
            continue
        bvid = source.get("bvid")
        if not isinstance(bvid, str) or not BV_PATTERN.fullmatch(bvid):
            audit["invalid_bv_rows"] += 1
            continue
        if bvid in seen:
            audit["duplicate_bv_rows"] += 1
            continue
        seen.add(bvid)
        row = {key: source.get(key) for key in VIDEO_FIELDS}
        row["bvid"] = bvid
        row["url"] = None if synthetic else f"https://www.bilibili.com/video/{bvid}"
        row["is_synthetic"] = synthetic
        row["authorMid"] = creator_id(source.get("authorMid"))
        for key in COUNTS:
            row[key] = valid_count(source.get(key))
        row["favorite_pct"] = None
        if row["views"] is not None and row["views"] >= min_views and row["favorites"] is not None:
            row["favorite_pct"] = round(100 * row["favorites"] / row["views"], 2)
            review.append(row)
        videos.append(row)
        if row["authorMid"] is None:
            audit["videos_without_creator_id"] += 1
        else:
            groups[row["authorMid"]].append(row)
    review.sort(key=lambda row: (-row["favorites"] / row["views"], row["bvid"]))
    creators = []
    for mid, items in groups.items():
        measured = [row for row in items if row["views"] is not None]
        representative = min(measured or items, key=lambda row: (-(row["views"] or 0), row["bvid"]))
        views = [row["views"] for row in items if row["views"] is not None]
        likes = [row["likes"] for row in items if row["likes"] is not None]
        creators.append({
            "authorMid": mid, "authorName": representative["authorName"],
            "profile_url": None if synthetic else f"https://space.bilibili.com/{mid}",
            "sample_video_count": len(items),
            "observed_views_sum": sum(views) if views else None,
            "videos_with_views": len(views),
            "observed_likes_sum": sum(likes) if likes else None,
            "videos_with_likes": len(likes),
            "representative_bvid": representative["bvid"],
            "representative_url": representative["url"],
            "representative_views": representative["views"],
            "has_review_candidate": any(row["views"] is not None and row["views"] >= min_views for row in items),
            "profile_status": "合成数据；不指向真实用户" if synthetic else "未访问主页；仅由样本ID生成链接，待人工复核",
            "is_synthetic": synthetic,
        })
    creators.sort(key=lambda row: (row["observed_views_sum"] is None, -(row["observed_views_sum"] or 0), int(row["authorMid"])))
    summary = {
        "input_rows": len(rows), "unique_video_rows": len(videos),
        "creator_rows": len(creators), "review_video_rows": len(review),
        "review_creator_rows": sum(row["has_review_candidate"] for row in creators),
        "min_views": min_views, "missing_counts": {key: sum(row[key] is None for row in videos) for key in COUNTS},
        "audit": audit,
        "dataset_kind": "synthetic_fixture" if synthetic else "user_import",
        "deduplication": "按BV号保留第一条记录，不合并后续快照或补齐缺值",
        "limits": "样本不是全站排名；汇总只包含已有有效值，不是完整UP主指标。收藏/播放比例不是转化率。没有粉丝、全投稿、评论正文、销售或合作推荐。",
        "new_actor_runs": 0, "network_requests": 0,
    }
    return {"videos": videos, "review": review, "creators": creators}, summary


def write_csv(path, rows, fields):
    with path.open("x", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows({key: safe_cell(row.get(key)) for key in fields} for row in rows)


def export_analysis(source, output, min_views=1000, excel=False):
    source, output = Path(source), Path(output)
    raw = source.read_bytes()
    tables, summary = build_tables(json.loads(raw.decode("utf-8-sig")), min_views)
    if excel:
        try:
            import pandas as pd
            import openpyxl  # 在写文件前确认可选依赖存在
        except ImportError as error:
            raise ValueError("Excel导出需要pandas和openpyxl；可先使用无依赖CSV导出。") from error
    output.mkdir(parents=True, exist_ok=False)
    for name, fields in [("videos", VIDEO_FIELDS), ("review", VIDEO_FIELDS), ("creators", CREATOR_FIELDS)]:
        write_csv(output / f"{name}.csv", tables[name], fields)
    if excel:
        with pd.ExcelWriter(output / "analysis.xlsx", engine="openpyxl") as writer:
            for name, fields in [("videos", VIDEO_FIELDS), ("review", VIDEO_FIELDS), ("creators", CREATOR_FIELDS)]:
                frame = pd.DataFrame([{key: safe_cell(row.get(key)) for key in fields} for row in tables[name]], columns=fields, dtype=object)
                frame.to_excel(writer, sheet_name=name, index=False)
    summary["source_sha256"] = hashlib.sha256(raw).hexdigest()
    summary["source_filename"] = source.name
    summary["source_is_synthetic"] = summary["dataset_kind"] == "synthetic_fixture"
    summary["excel_exported"] = excel
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description="离线整理视频样本，生成CSV及可选Excel；默认不联网。")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "output")
    parser.add_argument("--min-views", type=int, default=1000)
    parser.add_argument("--excel", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = export_analysis(args.input, args.output_dir, args.min_views, args.excel)
    except (OSError, ValueError) as error:
        parser.exit(1, f"分析停止：{error}\n")
    nature = "合成演示数据" if result["source_is_synthetic"] else "用户导入数据"
    print(f"已离线整理{nature}：{result['unique_video_rows']}条视频、{result['creator_rows']}个ID分组、{result['review_video_rows']}条复核记录；无新运行。")


if __name__ == "__main__":
    main()
