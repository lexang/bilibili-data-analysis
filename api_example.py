"""付费调用示例：默认只打印计划；本轮仅用模拟响应验证，不实际请求。"""

import argparse
import json
import os
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ACTOR_ID = "qEqOp9akBbapIrsdj"
UNIT_PRICE_USD = Decimal("0.002")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("API返回重定向，已停止；不转发认证信息。")


def request_json(method, url, token, body=None):
    if urlsplit(url).scheme != "https" or urlsplit(url).netloc != "api.apify.com":
        raise ValueError("仅允许Apify官方HTTPS API地址。")
    data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
    request = Request(url, data=data, method=method, headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
    })
    try:
        with build_opener(NoRedirect()).open(request, timeout=75) as response:
            return json.load(response)
    except HTTPError as error:
        raise ValueError(f"API返回HTTP {error.code}；未自动重试。") from None
    except (URLError, TimeoutError, OSError):
        raise ValueError("API连接未完成；POST可能已启动运行。先检查Apify运行后台，不要直接重复启动。") from None


def make_plan(keyword="机械键盘", max_results=20, max_charge="0.10"):
    if not isinstance(keyword, str) or not keyword.strip():
        raise ValueError("关键词不能为空。")
    if type(max_results) is not int or not 1 <= max_results <= 20:
        raise ValueError("此示例只允许1到20条结果。")
    try:
        cap = Decimal(str(max_charge))
    except InvalidOperation:
        raise ValueError("费用上限不是有效数字。") from None
    if not cap.is_finite() or not UNIT_PRICE_USD * max_results <= cap <= Decimal("0.10"):
        raise ValueError("费用上限需覆盖结果估算，且不得超过0.10美元。")
    params = {
        "build": "0.1.4", "memory": 256, "timeout": 120,
        "maxTotalChargeUsd": str(cap), "restartOnError": "false", "waitForFinish": 60,
    }
    return {
        "actor_id": ACTOR_ID,
        "method": "POST",
        "url": f"https://api.apify.com/v2/actors/{ACTOR_ID}/runs?{urlencode(params)}",
        "input": {
            "searchKeywords": [keyword.strip()], "maxResultsPerKeyword": max_results,
            "searchOrder": "totalrank", "enrichSearchResults": False,
            "videoUrls": [], "includePopular": False, "maxPopular": 20,
            "creatorIds": [], "proxyConfiguration": {"useApifyProxy": False},
        },
        "unit_price_usd": str(UNIT_PRICE_USD),
        "estimated_result_charge_usd": str(UNIT_PRICE_USD * max_results),
        "max_total_charge_usd": str(cap),
        "note": "价格为既有标价，不是实时账单；使用前核查商店。作者运行不是客户账单。只发一次POST，无重试、定时、自动轮询或自动中止。",
    }


def execute_plan(plan, token, output):
    """只供完成命令行费用确认后调用；连接失败不重新POST。"""
    if not token or not token.strip():
        raise ValueError("实际运行需要APIFY_TOKEN环境变量。")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"plan": plan, "state": "START_UNKNOWN", "warning": "若启动响应未返回，先检查运行后台；不得直接重复启动。"}
    record = output / "run.json"
    record.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    run = request_json("POST", plan["url"], token, plan["input"])["data"]
    if run.get("actId") != ACTOR_ID or not re.fullmatch(r"[A-Za-z0-9]+", run.get("id", "")):
        raise ValueError("运行响应的Actor或ID异常，已停止；请检查后台，不要再次POST。")
    manifest.update(state=run.get("status"), run_id=run["id"], dataset_id=run.get("defaultDatasetId"))
    record.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if run.get("status") != "SUCCEEDED":
        return manifest
    dataset = run.get("defaultDatasetId", "")
    if not re.fullmatch(r"[A-Za-z0-9]+", dataset):
        raise ValueError("响应缺少有效dataset ID，已停止。")
    limit = plan["input"]["maxResultsPerKeyword"]
    url = f"https://api.apify.com/v2/datasets/{dataset}/items?format=json&offset=0&limit={limit}&clean=false"
    items = request_json("GET", url, token)
    if not isinstance(items, list) or any(not isinstance(row, dict) for row in items) or len(items) > limit:
        raise ValueError("数据集响应格式或数量异常。")
    (output / "results.json").write_text(json.dumps(items, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    manifest.update(downloaded_rows=len(items), warning="SUCCEEDED不证明达到请求数量或字段齐全；请检查results.json。下载不触发第二次Actor运行。")
    record.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="默认仅打印调用计划；付费运行必须显式确认。")
    parser.add_argument("--keyword", default="机械键盘")
    parser.add_argument("--max-results", type=int, default=20)
    parser.add_argument("--max-charge-usd", default="0.10")
    parser.add_argument("--allow-paid-run", action="store_true")
    parser.add_argument("--confirm-unit-price-usd")
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent / "api-output")
    args = parser.parse_args(argv)
    try:
        plan = make_plan(args.keyword, args.max_results, args.max_charge_usd)
        if not args.allow_paid_run:
            print(json.dumps(plan, ensure_ascii=False, indent=2))
            print("仅打印计划：未读取token、未联网、未创建运行或文件。")
            return
        if args.confirm_unit_price_usd is None or Decimal(args.confirm_unit_price_usd) != UNIT_PRICE_USD:
            raise ValueError("实际运行需先核查价格并提供--confirm-unit-price-usd 0.002。")
        print(f"即将发一次付费请求：预计结果费用${plan['estimated_result_charge_usd']}，单次上限${plan['max_total_charge_usd']}。", flush=True)
        result = execute_plan(plan, os.environ.get("APIFY_TOKEN", ""), args.output_dir)
        print(f"运行{result['run_id']}状态{result['state']}；记录已保存。未自动重试或创建日程。")
    except (ValueError, InvalidOperation, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"已停止：{error}\n")


if __name__ == "__main__":
    main()
