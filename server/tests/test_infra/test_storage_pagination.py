"""Verify list_eval_log_chunks / delete_eval_logs page through S3 results.

Previously both helpers issued a single ``list_objects_v2`` call and silently
ignored the second page, which meant any eval producing more than ~1000
log chunks lost everything past the first page.
"""

from unittest.mock import MagicMock

from decision_hub.infra.storage import delete_eval_logs, list_eval_log_chunks


def _mk_pages(*chunks_per_page: list[str]) -> MagicMock:
    """Build a fake boto3 client whose paginator yields the given pages."""
    paginator = MagicMock()
    paginator.paginate.return_value = [{"Contents": [{"Key": key} for key in keys]} for keys in chunks_per_page]
    client = MagicMock()
    client.get_paginator.return_value = paginator
    return client


def test_list_eval_log_chunks_walks_every_page() -> None:
    client = _mk_pages(
        ["eval-logs/run-x/0001.jsonl", "eval-logs/run-x/0002.jsonl"],
        ["eval-logs/run-x/0003.jsonl"],
    )

    chunks = list_eval_log_chunks(client, "bucket", "eval-logs/run-x/")

    assert [seq for seq, _ in chunks] == [1, 2, 3]
    client.get_paginator.assert_called_once_with("list_objects_v2")


def test_list_eval_log_chunks_filters_by_after_seq_across_pages() -> None:
    client = _mk_pages(
        ["eval-logs/run-x/0001.jsonl", "eval-logs/run-x/0002.jsonl"],
        ["eval-logs/run-x/0003.jsonl", "eval-logs/run-x/0004.jsonl"],
    )

    chunks = list_eval_log_chunks(client, "bucket", "eval-logs/run-x/", after_seq=2)
    assert [seq for seq, _ in chunks] == [3, 4]


def test_list_eval_log_chunks_skips_non_jsonl_and_unparsable_seq() -> None:
    client = _mk_pages(
        [
            "eval-logs/run-x/0001.jsonl",
            "eval-logs/run-x/README.md",
            "eval-logs/run-x/notanumber.jsonl",
        ],
    )

    chunks = list_eval_log_chunks(client, "bucket", "eval-logs/run-x/")
    assert [seq for seq, _ in chunks] == [1]


def test_delete_eval_logs_batches_in_chunks_of_1000() -> None:
    # 1500 keys spread over three list pages should produce two delete
    # calls — the first with 1000 keys, the second with 500.
    page_size = 600
    pages = [[f"eval-logs/run-x/{i:04d}.jsonl" for i in range(start, start + page_size)] for start in (0, 600, 1200)]
    pages[-1] = pages[-1][:300]  # last page = 300 keys → total 1500

    client = _mk_pages(*pages)

    deleted = delete_eval_logs(client, "bucket", "eval-logs/run-x/")

    assert deleted == 1500
    assert client.delete_objects.call_count == 2
    first_batch = client.delete_objects.call_args_list[0].kwargs["Delete"]["Objects"]
    second_batch = client.delete_objects.call_args_list[1].kwargs["Delete"]["Objects"]
    assert len(first_batch) == 1000
    assert len(second_batch) == 500


def test_delete_eval_logs_no_objects_is_noop() -> None:
    client = _mk_pages([])  # one page, zero objects
    deleted = delete_eval_logs(client, "bucket", "eval-logs/run-x/")
    assert deleted == 0
    client.delete_objects.assert_not_called()
