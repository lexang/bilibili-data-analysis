# Synthetic test data

`synthetic-videos.json` contains nine hand-written test records. Names, BV-like identifiers, creator IDs and counts are fabricated solely to exercise the code. They are not Bilibili measurements, customer data, anonymized records or a market sample. Every record has `is_synthetic: true`.

The fixture contains six unique video records, one duplicate, one non-video record and one invalid identifier. Analysis produces four creator-ID groups and three review rows. Those counts demonstrate the algorithm only.

Video and profile links are blank when processing synthetic data. The script must not construct real Bilibili links from these placeholders. Synthetic and imported data cannot be mixed in one analysis.

The original 20-record author test, its CSV/Excel outputs and any account credentials are deliberately excluded from this repository candidate. Provide your own permitted JSON export with `--input`; do not mark real data as synthetic.
