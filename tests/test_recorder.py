import json
from decimal import Decimal

from hyperdspy.config import RecordingConfig
from hyperdspy.models import BookSnapshot, PriceLevel
from hyperdspy.recorder import CsvWriter, DataRecorder, JsonLinesWriter


def make_book():
    return BookSnapshot(
        coin="BTC",
        bids=(
            PriceLevel(price=Decimal("67500.0"), size=Decimal("1.5"), num_orders=3),
            PriceLevel(price=Decimal("67490.0"), size=Decimal("2.0"), num_orders=5),
        ),
        asks=(
            PriceLevel(price=Decimal("67510.0"), size=Decimal("1.2"), num_orders=4),
            PriceLevel(price=Decimal("67520.0"), size=Decimal("3.0"), num_orders=6),
        ),
        timestamp_ms=1700000000000,
    )


class TestJsonLinesWriter:
    def test_write_and_read(self, tmp_path):
        path = tmp_path / "test.jsonl"
        writer = JsonLinesWriter(path)
        writer.write({"a": 1, "b": "hello"})
        writer.write({"a": 2, "b": "world"})
        writer.flush()
        writer.close()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[0]) == {"a": 1, "b": "hello"}
        assert json.loads(lines[1]) == {"a": 2, "b": "world"}

    def test_creates_parent_dirs(self, tmp_path):
        path = tmp_path / "sub" / "dir" / "test.jsonl"
        writer = JsonLinesWriter(path)
        writer.write({"x": 1})
        writer.close()
        assert path.exists()


class TestCsvWriter:
    def test_write_with_header(self, tmp_path):
        path = tmp_path / "test.csv"
        writer = CsvWriter(path)
        writer.write({"coin": "BTC", "price": "67500", "size": "1.5"})
        writer.write({"coin": "ETH", "price": "3000", "size": "10.0"})
        writer.flush()
        writer.close()

        lines = path.read_text().strip().split("\n")
        assert len(lines) == 3  # header + 2 rows
        assert lines[0] == "coin,price,size"
        assert lines[1] == "BTC,67500,1.5"


class TestDataRecorder:
    def test_record_l2_creates_file(self, tmp_path):
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), format="jsonl")
        recorder = DataRecorder(config)
        book = make_book()

        recorder.record_l2("BTC", book)
        recorder.flush()
        recorder.close()

        files = list((tmp_path / "BTC").glob("l2_*.jsonl"))
        assert len(files) == 1

        records = [json.loads(line) for line in files[0].read_text().strip().split("\n")]
        assert len(records) == 1
        assert records[0]["coin"] == "BTC"
        assert records[0]["best_bid"] == "67500.0"
        assert records[0]["best_ask"] == "67510.0"
        assert records[0]["mid"] is not None

    def test_record_l4_creates_file(self, tmp_path):
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), format="jsonl")
        recorder = DataRecorder(config)

        raw_msg = {"coin": "BTC", "bids": [{"oid": 1, "limitPx": "67500", "sz": "1.0"}]}
        recorder.record_l4("BTC", raw_msg)
        recorder.flush()
        recorder.close()

        files = list((tmp_path / "BTC").glob("l4_*.jsonl"))
        assert len(files) == 1

        records = [json.loads(line) for line in files[0].read_text().strip().split("\n")]
        assert records[0]["coin"] == "BTC"
        assert records[0]["data"] == raw_msg

    def test_record_trade(self, tmp_path):
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), format="jsonl")
        recorder = DataRecorder(config)

        trade = {"side": "B", "px": "67505.0", "sz": "0.5", "time": 1700000001000, "hash": "0xabc"}
        recorder.record_trade("BTC", trade)
        recorder.flush()
        recorder.close()

        files = list((tmp_path / "BTC").glob("trades_*.jsonl"))
        assert len(files) == 1

        records = [json.loads(line) for line in files[0].read_text().strip().split("\n")]
        assert records[0]["side"] == "B"
        assert records[0]["px"] == "67505.0"

    def test_disabled_recording(self, tmp_path):
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), record_l2=False)
        recorder = DataRecorder(config)
        recorder.record_l2("BTC", make_book())
        recorder.close()

        # No files should be created for L2
        l2_files = list((tmp_path / "BTC").glob("l2_*"))
        assert len(l2_files) == 0

    def test_csv_format(self, tmp_path):
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), format="csv")
        recorder = DataRecorder(config)

        trade = {"side": "B", "px": "67505.0", "sz": "0.5", "time": 1700000001000}
        recorder.record_trade("BTC", trade)
        recorder.flush()
        recorder.close()

        files = list((tmp_path / "BTC").glob("trades_*.csv"))
        assert len(files) == 1
        lines = files[0].read_text().strip().split("\n")
        assert len(lines) == 2  # header + 1 row

    def test_multiple_coins(self, tmp_path):
        config = RecordingConfig(enabled=True, output_dir=str(tmp_path), format="jsonl")
        recorder = DataRecorder(config)

        recorder.record_l2("BTC", make_book())
        eth_book = BookSnapshot(
            coin="ETH",
            bids=(PriceLevel(Decimal("3000"), Decimal("10"), 5),),
            asks=(PriceLevel(Decimal("3001"), Decimal("8"), 3),),
            timestamp_ms=1700000000000,
        )
        recorder.record_l2("ETH", eth_book)
        recorder.flush()
        recorder.close()

        assert (tmp_path / "BTC").exists()
        assert (tmp_path / "ETH").exists()
