"""Tests for eval log S3 storage functions in infra/storage.py."""

from unittest.mock import MagicMock

from decision_hub.infra.storage import (
    delete_eval_logs,
    list_eval_log_chunks,
    read_eval_log_chunk,
    upload_eval_log_chunk,
)


def _make_s3_client(pages: list[dict] | None = None) -> MagicMock:
    """Build a mock S3 client whose paginator yields ``pages`` in order.

    ``pages`` is a list of raw ``list_objects_v2`` response dicts (each with
    a ``Contents`` key). Empty list ⇒ one empty page.
    """
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = iter(pages if pages is not None else [{}])
    client.get_paginator.return_value = paginator
    return client


class TestUploadEvalLogChunk:
    def test_uploads_with_correct_key_and_content(self):
        client = MagicMock()
        result = upload_eval_log_chunk(client, "test-bucket", "eval-logs/run123/", 1, '{"seq":1}\n')
        assert result == "eval-logs/run123/0001.jsonl"
        client.put_object.assert_called_once_with(
            Bucket="test-bucket",
            Key="eval-logs/run123/0001.jsonl",
            Body=b'{"seq":1}\n',
            ContentType="application/x-ndjson",
        )

    def test_zero_pads_sequence_number(self):
        client = MagicMock()
        result = upload_eval_log_chunk(client, "bucket", "prefix/", 42, "data")
        assert result == "prefix/0042.jsonl"


class TestListEvalLogChunks:
    def test_returns_chunks_after_cursor(self):
        client = _make_s3_client(
            [
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
        client.get_paginator.assert_called_once_with("list_objects_v2")

    def test_returns_empty_for_no_contents(self):
        client = _make_s3_client([{}])
        result = list_eval_log_chunks(client, "bucket", "prefix/")
        assert result == []

    def test_skips_non_jsonl_files(self):
        client = _make_s3_client(
            [
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
            [
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

    def test_paginates_beyond_the_1000_key_limit(self):
        """Regression: ``list_objects_v2`` caps at 1000 keys per call. Without
        pagination, chunks past index 1000 vanish and the CLI silently loses
        tail events. The paginator must chain pages transparently."""
        page_a = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1, 1001)]}
        page_b = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1001, 1201)]}
        client = _make_s3_client([page_a, page_b])
        result = list_eval_log_chunks(client, "bucket", "p/")
        assert len(result) == 1200
        # Order preserved after the sort.
        assert result[0][0] == 1
        assert result[-1][0] == 1200


class TestReadEvalLogChunk:
    def test_reads_and_decodes_content(self):
        client = MagicMock()
        client.get_object.return_value = {"Body": MagicMock(read=lambda: b'{"seq":1}\n{"seq":2}\n')}
        result = read_eval_log_chunk(client, "bucket", "key")
        assert '{"seq":1}' in result
        assert '{"seq":2}' in result


class TestDeleteEvalLogs:
    def test_deletes_all_objects_under_prefix(self):
        client = _make_s3_client(
            [
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
        client = _make_s3_client([{}])
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 0
        client.delete_objects.assert_not_called()

    def test_batches_delete_calls_at_the_1000_key_limit(self):
        """Regression: ``delete_objects`` accepts at most 1000 keys per call.
        A prefix with 2500 chunks must produce 3 batched deletes, not one
        oversize (rejected) call and not 1500 leaked orphans."""
        page_a = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1, 1001)]}
        page_b = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1001, 2001)]}
        page_c = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(2001, 2501)]}
        client = _make_s3_client([page_a, page_b, page_c])
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 2500
        assert client.delete_objects.call_count == 3
        # Verify each batch stayed at or under the 1000-key cap.
        for call in client.delete_objects.call_args_list:
            assert len(call.kwargs["Delete"]["Objects"]) <= 1000
