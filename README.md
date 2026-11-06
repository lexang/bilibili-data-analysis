# Bilibili data analysis with Python

Analyze a Bilibili-format JSON export offline and write video, review and creator-summary tables. The default command uses clearly marked synthetic data, so you can try the code without an account, a token or a paid run. CSV export needs only Python's standard library; Excel export uses Pandas and openpyxl.

This example is maintained alongside the developer's paid Bilibili Scraper on Apify. Use an export you are allowed to process, or start with the included fabricated fixture. No scraped dataset or original author-test records are bundled.

Actor:

https://apify.com/zlexang/bilibili-scraper-no-login

Existing keyword task:

https://apify.com/zlexang/bilibili-scraper-no-login/examples/bzhan-guan-jian-ci-sou-suo-shi-li-zui-duo-20tiao

## Try the synthetic example

Use Python 3.10 or later. From this directory:

```shell
python analyze.py
python -m unittest -v test_example
```

The default input, `data/synthetic-videos.json`, contains nine fabricated records for duplicate IDs, missing values and spreadsheet-text handling. It produces six video rows, four creator-ID groups and three review rows. These are test counts, not real videos, customers or recommendations. Synthetic outputs are marked as such and contain no Bilibili video or profile links.

Tests block real socket connections. Without the optional Excel dependencies, the Excel test is skipped and the standard-library tests still run. No test starts an Actor.

## Analyze your own export

Provide a JSON array of video objects using this Actor's fields:

```shell
python analyze.py --input path/to/videos.json --output-dir my-analysis
```

The analysis reads the file; it does not visit video or profile URLs. Real inputs must not carry `is_synthetic: true`, and mixed synthetic/real files are rejected. The output directory must be new: existing results are never overwritten.

| File | Contents |
| --- | --- |
| `videos.csv` | Unique BV IDs, available counts and source links |
| `review.csv` | Videos with at least 1,000 views and known favorites, sorted by favorites/views |
| `creators.csv` | ID-based sample groups, observed sums, coverage and representative videos |
| `summary.json` | Input hash, synthetic/imported label, missing counts and skipped-row audit |

Duplicates keep the first BV record; later snapshots are not merged. Creator groups use `authorMid`, not a display name. `UP主` means a Bilibili creator. Profile links in imported-data outputs are generated from IDs, not verified by a profile lookup.

Observed sums include only valid values and come with `videos_with_*` coverage counts. If every value is missing, the sum is blank. Missing is not zero; partial sums are not complete creator performance, and summed views are not unique viewers. No follower counts or full upload histories are fetched.

The 1,000-view threshold is an example setting, not a research standard. Review rows use the unrounded favorites/views ratio for sorting and a two-decimal percentage for display. That ratio is not a conversion rate or sales estimate. Search-only `coins` and `shares` can be null. Negative, non-finite, boolean and string counts are treated as missing.

CSV files use UTF-8 with a BOM. Formula-like text gets an apostrophe prefix in exported tables; the input JSON is unchanged. Long creator IDs remain strings.

## Export Excel

The tested optional versions are Pandas 2.3.3 and openpyxl 3.1.5. Package installation downloads dependencies but does not start the Actor.

```shell
python -m pip install -r requirements-excel.txt
python analyze.py --excel --output-dir excel-analysis
```

The workbook contains `videos`, `review` and `creators` sheets, alongside the CSV files. Run the tests again after installation to include the Excel check.

## Inspect the API plan

```shell
python api_example.py
```

By default this prints a plan, not a request. It does not read a token, create files or contact Apify. The plan searches `机械键盘` (mechanical keyboards), with up to 20 results, using build `0.1.4`, 256 MB of memory, a 120-second run timeout and a $0.10 cap. Detail enrichment and proxies are off.

At the saved price of $0.002 per video or creator profile, exactly 20 returned videos cost $0.04, including platform usage. Check the Store price before collecting data; this is not a live quote or a customer bill.

The optional real-run path requires `--allow-paid-run`, `--confirm-unit-price-usd 0.002` and your own `APIFY_TOKEN` environment variable. That path has been tested with simulated responses only, not a fresh collection or paid run. **Enabling it is a separate cost and data-permission decision.** Never commit a token, pass it in a URL or store it with output data.

After explicit confirmation, the script sends one POST with `waitForFinish=60`. A `SUCCEEDED` response leads to one GET for up to the requested number of dataset records. An active or failed run is recorded without polling, restarting, scheduling or aborting it. An uncertain POST response may still mean a run started; check Console before starting again. The local timeout does not stop the cloud Actor.

`run.json` records the run ID and status without the token. A successful status does not establish result count or field completeness. Dataset retrieval may have account-specific storage or transfer implications.

## Data and publication boundaries

The Actor returns public metadata, not video files, subtitles, comment text or private material. Comments and danmaku are counts. You supply no Bilibili account cookies; the Actor manages guest cookies internally. Ordinary token-based API use requires an Apify account and can still hit rate limits.

Public visibility does not grant redistribution, commercial-use or AI-training rights. Assess permissions before collecting or sharing data. The included fixture is fabricated, not a substitute for access permission. This repository candidate does not assign an open-source license or rights to third-party metadata.

## References

The existing 20-result author-test walkthrough is separate from the synthetic fixture:

https://lexang.hashnode.dev/sorting-bilibili-videos-with-python-a-20-result-keyboard-research-sample

Official Actor-run parameters and charge caps:

https://docs.apify.com/api/v2/actors-runs-post.md

Official dataset formats and retrieval limits:

https://docs.apify.com/api/v2/dataset-items-get.md
