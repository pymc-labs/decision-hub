"""Tests for eval log S3 storage functions in infra/storage.py."""

from unittest.mock import MagicMock

import pytest

from decision_hub.infra.storage import (
    delete_eval_logs,
    list_eval_log_chunks,
    read_eval_log_chunk,
    upload_eval_log_chunk,
)


def _make_s3_client(pages: list[list[dict]] | None = None) -> MagicMock:
    """Return a MagicMock S3 client whose `list_objects_v2` paginator yields
    the given `pages`. Each page is the `Contents` list for that page. This
    matches how boto3's real `client.get_paginator("list_objects_v2")` yields
    responses, so tests exercise the same code paths as production.
    """
    client = MagicMock()
    if pages is None:
        pages = [[]]
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": page} for page in pages]
    client.get_paginator.return_value = paginator
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
                [
                    {"Key": "eval-logs/run/0001.jsonl"},
                    {"Key": "eval-logs/run/0002.jsonl"},
                    {"Key": "eval-logs/run/0003.jsonl"},
                ]
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "eval-logs/run/", after_seq=1)
        assert len(result) == 2
        assert result[0] == (2, "eval-logs/run/0002.jsonl")
        assert result[1] == (3, "eval-logs/run/0003.jsonl")

    def test_returns_empty_for_no_contents(self):
        client = _make_s3_client(pages=[[]])
        result = list_eval_log_chunks(client, "bucket", "prefix/")
        assert result == []

    def test_skips_non_jsonl_files(self):
        client = _make_s3_client(
            pages=[
                [
                    {"Key": "prefix/0001.jsonl"},
                    {"Key": "prefix/readme.txt"},
                ]
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "prefix/")
        assert len(result) == 1

    def test_returns_sorted_by_seq(self):
        client = _make_s3_client(
            pages=[
                [
                    {"Key": "p/0003.jsonl"},
                    {"Key": "p/0001.jsonl"},
                    {"Key": "p/0002.jsonl"},
                ]
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "p/")
        seqs = [s for s, _ in result]
        assert seqs == [1, 2, 3]

    def test_paginates_across_multiple_pages(self):
        """Regression: previously used a single list_objects_v2 call, which
        truncated at 1000 keys and lost the tail of long-running eval logs
        (including the final "run complete" chunk)."""
        client = _make_s3_client(
            pages=[
                [{"Key": f"p/{i:04d}.jsonl"} for i in range(1, 1001)],
                [{"Key": f"p/{i:04d}.jsonl"} for i in range(1001, 1501)],
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "p/")
        assert len(result) == 1500
        assert result[0][0] == 1
        assert result[-1][0] == 1500


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
                [
                    {"Key": "p/0001.jsonl"},
                    {"Key": "p/0002.jsonl"},
                ]
            ]
        )
        client.delete_objects.return_value = {
            "Deleted": [{"Key": "p/0001.jsonl"}, {"Key": "p/0002.jsonl"}],
        }
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 2
        client.delete_objects.assert_called_once()

    def test_returns_zero_for_empty_prefix(self):
        client = _make_s3_client(pages=[[]])
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 0
        client.delete_objects.assert_not_called()

    def test_batches_deletes_in_groups_of_1000(self):
        """S3 DeleteObjects caps each request at 1000 keys, so anything
        larger must be split across multiple requests."""
        pages = [
            [{"Key": f"p/{i:04d}.jsonl"} for i in range(1, 1001)],
            [{"Key": f"p/{i:04d}.jsonl"} for i in range(1001, 2501)],
        ]
        client = _make_s3_client(pages=pages)
        # Each real DeleteObjects call returns per-batch Deleted; simulate
        # by returning 1000 the first two times then 500 the third.
        client.delete_objects.side_effect = [
            {"Deleted": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1, 1001)]},
            {"Deleted": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1001, 2001)]},
            {"Deleted": [{"Key": f"p/{i:04d}.jsonl"} for i in range(2001, 2501)]},
        ]
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 2500
        assert client.delete_objects.call_count == 3

    def test_raises_on_partial_failure(self):
        """Previously the Errors[] array in DeleteObjects responses was
        ignored, so half-failed deletes were reported as full success."""
        client = _make_s3_client(
            pages=[
                [
                    {"Key": "p/0001.jsonl"},
                    {"Key": "p/0002.jsonl"},
                ]
            ]
        )
        client.delete_objects.return_value = {
            "Deleted": [{"Key": "p/0001.jsonl"}],
            "Errors": [{"Key": "p/0002.jsonl", "Code": "AccessDenied", "Message": "no"}],
        }
        with pytest.raises(RuntimeError, match="delete_objects reported 1 errors"):
            delete_eval_logs(client, "bucket", "p/")
