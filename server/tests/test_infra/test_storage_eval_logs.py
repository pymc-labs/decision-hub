"""Tests for eval log S3 storage functions in infra/storage.py."""

from unittest.mock import MagicMock

from decision_hub.infra.storage import (
    delete_eval_logs,
    list_eval_log_chunks,
    read_eval_log_chunk,
    upload_eval_log_chunk,
)


def _make_s3_client(pages: list[dict] | None = None) -> MagicMock:
    """Build a mock boto3 S3 client whose paginator yields the given pages.

    Each element of `pages` is a `list_objects_v2` response fragment
    (a dict with a "Contents" list). Callers that don't need pagination
    can omit the argument.
    """
    client = MagicMock()
    if pages is not None:
        client.get_paginator.return_value.paginate.return_value = iter(pages)
    return client


class TestUploadEvalLogChunk:
    def test_uploads_with_correct_key_and_content(self):
        client = _make_s3_client()
        result = upload_eval_log_chunk(client, "test-bucket", "eval-logs/run123/", 1, '{"seq":1}\n')
        assert result == "eval-logs/run123/0001.jsonl"
        client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="eval-logs/run123/0001.jsonl",
            Body=b'{"seq":1}\n',
            ContentType="application/x-ndjson",
        )

    def test_zero_pads_sequence_number(self):
        client = _make_s3_client()
        result = upload_eval_log_chunk(client, "bucket", "prefix/", 42, "data")
        assert result == "prefix/0042.jsonl"


class TestListEvalLogChunks:
    def test_returns_chunks_after_cursor(self):
        client = _make_s3_client(
            pages=[
                {
                    "Contents": [
                        {"Key": "eval-logs/run/0001.jsonl"},
                        {"Key": "eval-logs/run/0002.jsonl"},
                        {"Key": "eval-logs/run/0003.jsonl"},
                    ]
                }
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "eval-logs/run/", after_seq=1)
        assert len(result) == 2
        assert result[0] == (2, "eval-logs/run/0002.jsonl")
        assert result[1] == (3, "eval-logs/run/0003.jsonl")

    def test_returns_empty_for_no_contents(self):
        client = _make_s3_client(pages=[{}])
        result = list_eval_log_chunks(client, "bucket", "prefix/")
        assert result == []

    def test_skips_non_jsonl_files(self):
        client = _make_s3_client(
            pages=[
                {
                    "Contents": [
                        {"Key": "prefix/0001.jsonl"},
                        {"Key": "prefix/readme.txt"},
                    ]
                }
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "prefix/")
        assert len(result) == 1

    def test_returns_sorted_by_seq(self):
        client = _make_s3_client(
            pages=[
                {
                    "Contents": [
                        {"Key": "p/0003.jsonl"},
                        {"Key": "p/0001.jsonl"},
                        {"Key": "p/0002.jsonl"},
                    ]
                }
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "p/")
        seqs = [s for s, _ in result]
        assert seqs == [1, 2, 3]

    def test_paginates_beyond_first_page(self):
        """Regression: `list_objects_v2` caps at 1000 keys per response.
        Runs longer than one page previously silently lost every chunk
        past the first page. The paginator must stitch pages together.
        """
        client = _make_s3_client(
            pages=[
                {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1, 3)]},
                {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in (5, 6)]},
                {"Contents": [{"Key": "p/9999.jsonl"}]},
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "p/")
        seqs = [s for s, _ in result]
        assert seqs == [1, 2, 5, 6, 9999]


class TestReadEvalLogChunk:
    def test_reads_and_decodes_content(self):
        client = _make_s3_client()
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"seq":1}\n{"seq":2}\n')}
        result = read_eval_log_chunk(client, "bucket", "key")
        assert '{"seq":1}' in result
        assert '{"seq":2}' in result


class TestDeleteEvalLogs:
    def test_deletes_all_objects_under_prefix(self):
        client = _make_s3_client(
            pages=[
                {
                    "Contents": [
                        {"Key": "p/0001.jsonl"},
                        {"Key": "p/0002.jsonl"},
                    ]
                }
            ]
        )
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 2
        client.delete_objects.assert_called_once()

    def test_returns_zero_for_empty_prefix(self):
        client = _make_s3_client(pages=[{}])
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 0
        client.delete_objects.assert_not_called()

    def test_batches_delete_calls_in_groups_of_1000(self):
        """`delete_objects` accepts at most 1000 keys per call. A run with
        more than 1000 chunks previously left the tail orphaned; the fix
        must issue one delete per full batch plus a trailing partial call.
        """
        page_a = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1, 1001)]}
        page_b = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1001, 1251)]}
        client = _make_s3_client(pages=[page_a, page_b])

        count = delete_eval_logs(client, "bucket", "p/")

        assert count == 1250
        # First call: exactly 1000 keys (the batch cap).
        # Second call: the remaining 250 keys as a trailing partial batch.
        assert client.delete_objects.call_count == 2
        first_batch = client.delete_objects.call_args_list[0].kwargs["Delete"]["Objects"]
        second_batch = client.delete_objects.call_args_list[1].kwargs["Delete"]["Objects"]
        assert len(first_batch) == 1000
        assert len(second_batch) == 250
