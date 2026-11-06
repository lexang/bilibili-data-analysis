"""仅使用合成数据与模拟API响应；所有测试禁止真实网络连接。"""

import contextlib
import copy
import csv
import io
import importlib.util
import json
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import analyze
import api_example as api


def video(bvid="BV0000000001", mid=1, **values):
    return {"type": "video", "bvid": bvid, "authorMid": mid, "authorName": "同名", **values}


class ExampleTests(unittest.TestCase):
    def setUp(self):
        self.network = patch.object(socket.socket, "connect", side_effect=AssertionError("离线测试禁止联网"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def test_synthetic_fixture_and_source_unchanged(self):
        raw = analyze.DEFAULT_INPUT.read_bytes()
        rows = json.loads(raw)
        original = copy.deepcopy(rows)
        tables, summary = analyze.build_tables(rows)
        self.assertEqual((len(tables["videos"]), len(tables["creators"]), len(tables["review"])), (6, 4, 3))
        self.assertEqual(summary["review_creator_rows"], 3)
        self.assertEqual(summary["missing_counts"]["coins"], 6)
        self.assertEqual(summary["missing_counts"]["shares"], 6)
        self.assertEqual(summary["dataset_kind"], "synthetic_fixture")
        self.assertEqual(rows, original)
        self.assertEqual(analyze.DEFAULT_INPUT.read_bytes(), raw)

    def test_first_bv_wins_and_creators_group_by_id(self):
        rows = [video(views=1000), video(views=9999), video("BV0000000002", mid=2, views=2000)]
        tables, summary = analyze.build_tables(rows)
        self.assertEqual(summary["audit"]["duplicate_bv_rows"], 1)
        self.assertEqual({r["authorMid"] for r in tables["creators"]}, {"1", "2"})
        self.assertEqual(tables["videos"][0]["views"], 1000)

    def test_missing_invalid_and_zero_are_distinct(self):
        rows = [video(views=None, likes=True, favorites="2"), video("BV0000000002", mid=2, views=0, likes=0, coins=float("inf"))]
        tables, _ = analyze.build_tables(rows)
        self.assertIsNone(tables["videos"][0]["likes"])
        self.assertIsNone(next(row for row in tables["creators"] if row["authorMid"] == "1")["observed_likes_sum"])
        self.assertEqual(tables["videos"][1]["views"], 0)
        self.assertIsNone(tables["videos"][1]["coins"])
        self.assertEqual(tables["review"], [])
        for value in [False, True, -1, "1000", float("nan"), float("inf")]:
            self.assertIsNone(analyze.valid_count(value))

    def test_creator_aggregate_records_coverage(self):
        tables, _ = analyze.build_tables([video(views=2000, likes=10), video("BV0000000002", views=None, likes=None)])
        creator = tables["creators"][0]
        self.assertEqual((creator["sample_video_count"], creator["observed_views_sum"], creator["videos_with_views"]), (2, 2000, 1))
        self.assertNotIn("followers", creator)

    def test_id_precision_and_invalid_ids(self):
        big = 9007199254740993
        self.assertEqual(analyze.creator_id(big), str(big))
        self.assertEqual(analyze.creator_id(str(big)), str(big))
        for value in [True, 1.0, 0, "1e3", "", "-2", None]:
            self.assertIsNone(analyze.creator_id(value))
        tables, summary = analyze.build_tables([video(mid=1.0, views=1000)])
        self.assertEqual(len(tables["videos"]), 1)
        self.assertEqual(tables["creators"], [])
        self.assertEqual(summary["audit"]["videos_without_creator_id"], 1)

    def test_invalid_rows_are_audited(self):
        rows = [{"type": "creator"}, {"type": "video", "bvid": "bad"}, video()]
        tables, summary = analyze.build_tables(rows)
        self.assertEqual(len(tables["videos"]), 1)
        self.assertEqual(summary["audit"]["invalid_bv_rows"], 1)
        self.assertEqual(summary["audit"]["non_video_rows"], 1)
        for bad in [{}, [None], [42]]:
            with self.assertRaises(ValueError):
                analyze.build_tables(bad)

    def test_review_sorts_unrounded_ratio(self):
        rows = [video("BV0000000001", views=10002, favorites=100), video("BV0000000002", views=10001, favorites=100)]
        tables, _ = analyze.build_tables(rows)
        self.assertEqual([r["favorite_pct"] for r in tables["review"]], [1.0, 1.0])
        self.assertEqual(tables["review"][0]["bvid"], "BV0000000002")

    def test_empty_input_exports_headers(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "empty.json"
            source.write_text("[]", encoding="utf-8")
            summary = analyze.export_analysis(source, root / "result")
            self.assertEqual(summary["unique_video_rows"], 0)
            with (root / "result/videos.csv").open(encoding="utf-8-sig") as stream:
                self.assertEqual(list(csv.DictReader(stream)), [])

    def test_export_refuses_existing_directory(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "result"
            analyze.export_analysis(analyze.DEFAULT_INPUT, target)
            previous = (target / "videos.csv").read_bytes()
            with self.assertRaises(FileExistsError):
                analyze.export_analysis(analyze.DEFAULT_INPUT, target)
            self.assertEqual((target / "videos.csv").read_bytes(), previous)

    def test_spreadsheet_formula_protection(self):
        for text in ["=1+1", " +cmd", "-cmd", "@SUM(1)", "\ttext"]:
            self.assertEqual(analyze.safe_cell(text), "'" + text)
        self.assertEqual(analyze.safe_cell("普通标题"), "普通标题")
        self.assertEqual(analyze.safe_cell(100), 100)

    @unittest.skipUnless(importlib.util.find_spec("openpyxl") and importlib.util.find_spec("pandas"), "Excel测试需要可选依赖；标准库测试继续")
    def test_excel_contains_text_ids_and_no_formulas(self):
        import openpyxl
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.json"
            source.write_text(json.dumps([video(mid=9007199254740993, title="=1+1", views=2000, likes=0, favorites=2)]), encoding="utf-8")
            analyze.export_analysis(source, root / "result", excel=True)
            book = openpyxl.load_workbook(root / "result/analysis.xlsx")
            self.assertEqual(book.sheetnames, ["videos", "review", "creators"])
            self.assertEqual(book["videos"]["B2"].value, "'=1+1")
            self.assertEqual(book["videos"]["D2"].value, "9007199254740993")
            self.assertFalse(any(cell.data_type == "f" for sheet in book for row in sheet for cell in row))
            book.close()

    def test_dry_run_never_reads_token_or_calls_api(self):
        original_get = api.os.environ.get

        def no_token_read(key, default=None):
            if key == "APIFY_TOKEN":
                raise AssertionError("默认模式不得读token")
            return original_get(key, default)

        with patch.object(api, "request_json", side_effect=AssertionError("默认模式不得调用API")), patch.object(api.os.environ, "get", side_effect=no_token_read), contextlib.redirect_stdout(io.StringIO()) as output:
            api.main([])
        self.assertIn("未联网", output.getvalue())

    def test_paid_run_needs_confirmation_and_token(self):
        with patch.object(api, "request_json", side_effect=AssertionError("门禁失败不得请求")), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                api.main(["--allow-paid-run"])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "result"
            with self.assertRaises(ValueError):
                api.execute_plan(api.make_plan(), "", target)
            self.assertFalse(target.exists())

    def test_plan_bounds_and_no_token_in_url(self):
        plan = api.make_plan()
        self.assertEqual(plan["estimated_result_charge_usd"], "0.040")
        self.assertIn("maxTotalChargeUsd=0.10", plan["url"])
        self.assertIn("restartOnError=false", plan["url"])
        self.assertNotIn("token", plan["url"])
        for values in [("", 20, "0.10"), ("key", 21, "0.10"), ("key", 20, "0.01"), ("key", 20, "0.11"), ("key", 20, "NaN")]:
            with self.assertRaises(ValueError):
                api.make_plan(*values)

    def test_pending_run_does_not_poll_or_start_twice(self):
        run = {"data": {"id": "fakeRun", "actId": api.ACTOR_ID, "status": "RUNNING", "defaultDatasetId": "fakeDataset"}}
        with tempfile.TemporaryDirectory() as folder, patch.object(api, "request_json", return_value=run) as request:
            target = Path(folder) / "result"
            result = api.execute_plan(api.make_plan(), "fake-token", target)
            self.assertEqual(result["state"], "RUNNING")
            self.assertEqual(request.call_count, 1)
            self.assertFalse((target / "results.json").exists())
            self.assertNotIn("fake-token", (target / "run.json").read_text(encoding="utf-8"))

    def test_success_downloads_once_without_assuming_full_results(self):
        run = {"data": {"id": "fakeRun", "actId": api.ACTOR_ID, "status": "SUCCEEDED", "defaultDatasetId": "fakeDataset"}}
        with tempfile.TemporaryDirectory() as folder, patch.object(api, "request_json", side_effect=[run, [video()]]) as request:
            result = api.execute_plan(api.make_plan(), "fake-token", Path(folder) / "result")
            self.assertEqual(result["downloaded_rows"], 1)
            self.assertEqual([call.args[0] for call in request.call_args_list], ["POST", "GET"])

    def test_uncertain_post_keeps_record_and_does_not_retry(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(api, "request_json", side_effect=ValueError("模拟超时")) as request:
            target = Path(folder) / "result"
            with self.assertRaises(ValueError):
                api.execute_plan(api.make_plan(), "fake-token", target)
            self.assertEqual(request.call_count, 1)
            self.assertEqual(json.loads((target / "run.json").read_text(encoding="utf-8"))["state"], "START_UNKNOWN")

    def test_pending_or_failed_status_has_no_download(self):
        for status in ["READY", "FAILED", "TIMED-OUT", "ABORTED"]:
            with tempfile.TemporaryDirectory() as folder, patch.object(api, "request_json", return_value={"data": {"id": "fakeRun", "actId": api.ACTOR_ID, "status": status}}) as request:
                api.execute_plan(api.make_plan(), "fake-token", Path(folder) / "result")
                self.assertEqual(request.call_count, 1)

    def test_untrusted_host_and_redirect_rejected(self):
        with self.assertRaises(ValueError):
            api.request_json("GET", "https://example.com/", "fake-token")
        with self.assertRaises(ValueError):
            api.NoRedirect().redirect_request(None, None, 302, "redirect", {}, "https://example.com")

    def test_csv_preserves_missing_values_and_protects_text(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "test.csv"
            analyze.write_csv(path, [{"title": "=1+1", "views": None, "likes": 0}], ["title", "views", "likes"])
            with path.open(encoding="utf-8-sig") as stream:
                row = next(csv.DictReader(stream))
            self.assertEqual(row, {"title": "'=1+1", "views": "", "likes": "0"})

    def test_incomplete_or_wrong_actor_response_is_rejected(self):
        for data in [{"id": "fakeRun", "actId": "otherActor"}, {"id": "fakeRun", "actId": api.ACTOR_ID, "status": "SUCCEEDED", "defaultDatasetId": "https://example.com"}]:
            with tempfile.TemporaryDirectory() as folder, patch.object(api, "request_json", return_value={"data": data}) as request:
                with self.assertRaises(ValueError):
                    api.execute_plan(api.make_plan(), "fake-token", Path(folder) / "result")
                self.assertEqual(request.call_count, 1)

    def test_existing_api_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(api, "request_json", side_effect=AssertionError("已有目录不得新请求")):
            with self.assertRaises(FileExistsError):
                api.execute_plan(api.make_plan(), "fake-token", Path(folder))

    def test_synthetic_fixture_never_creates_real_links(self):
        tables, _ = analyze.build_tables(json.loads(analyze.DEFAULT_INPUT.read_text(encoding="utf-8")))
        self.assertTrue(all(row["url"] is None and row["is_synthetic"] for row in tables["videos"]))
        self.assertTrue(all(row["profile_url"] is None and row["is_synthetic"] for row in tables["creators"]))

    def test_mixed_synthetic_and_imported_data_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze.build_tables([video(is_synthetic=True), video("BV0000000002")])

    def test_default_export_summary_marks_synthetic_data(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = analyze.export_analysis(analyze.DEFAULT_INPUT, Path(folder) / "result")
            self.assertTrue(summary["source_is_synthetic"])
            self.assertFalse(summary["new_actor_runs"])
            self.assertEqual(summary["audit"], {"non_video_rows": 1, "invalid_bv_rows": 1, "duplicate_bv_rows": 1, "videos_without_creator_id": 0})


if __name__ == "__main__":
    unittest.main()
