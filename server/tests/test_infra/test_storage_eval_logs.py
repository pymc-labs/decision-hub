"""Tests for eval log S3 storage functions in infra/storage.py."""

from unittest.mock import MagicMock

from decision_hub.infra.storage import (
    delete_eval_logs,
    list_eval_log_chunks,
    read_eval_log_chunk,
    upload_eval_log_chunk,
)


def _make_s3_client(pages: list[dict] | None = None) -> MagicMock:
    """Build a mock S3 client whose `get_paginator("list_objects_v2")` yields
    the given pages. Storage helpers use the paginator API to avoid the
    silent 1000-object truncation of `list_objects_v2`.
    """
    client = MagicMock()
    paginator = MagicMock()
    paginator.paginate.return_value = pages or []
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

    def test_paginates_across_pages(self):
        """Long-running evals with >1000 chunks span multiple S3 list pages —
        the helper must return chunks from every page, not just the first."""
        client = _make_s3_client(
            [
                {"Contents": [{"Key": "p/0001.jsonl"}, {"Key": "p/0002.jsonl"}]},
                {"Contents": [{"Key": "p/0003.jsonl"}, {"Key": "p/0004.jsonl"}]},
            ]
        )
        result = list_eval_log_chunks(client, "bucket", "p/")
        assert [s for s, _ in result] == [1, 2, 3, 4]


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

    def test_batches_deletes_at_1000_keys(self):
        """S3 delete_objects caps at 1000 keys per request. When the paginator
        returns more, delete_eval_logs must issue multiple batched calls."""
        # 1500 keys across two pages: 1000 → first delete, 500 → second delete.
        page1 = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1000)]}
        page2 = {"Contents": [{"Key": f"p/{i:04d}.jsonl"} for i in range(1000, 1500)]}
        client = _make_s3_client([page1, page2])
        count = delete_eval_logs(client, "bucket", "p/")
        assert count == 1500
        assert client.delete_objects.call_count == 2
        assert len(client.delete_objects.call_args_list[0].kwargs["Delete"]["Objects"]) == 1000
        assert len(client.delete_objects.call_args_list[1].kwargs["Delete"]["Objects"]) == 500
