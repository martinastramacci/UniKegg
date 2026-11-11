"""Benchmark consumes results and cleans up without modifying domain data."""

from unittest.mock import Mock

import pytest

from tools import benchmark_queries


@pytest.mark.parametrize("failure", [False, True])
def test_benchmark_readonly_and_cleanup(monkeypatch, failure):
    assert len(benchmark_queries.statements()) == 30
    connection, cursor = Mock(), Mock()
    connection.cursor.return_value = cursor
    cursor.fetchone.side_effect = [("8.0-test",), ("a" * 64,)]
    cursor.fetchmany.side_effect = RuntimeError("query failed") if failure else [[(1,)], []] * 30
    monkeypatch.setattr(benchmark_queries, "connect", lambda: connection)
    if failure:
        with pytest.raises(RuntimeError, match="query failed"):
            benchmark_queries.run()
    else:
        result = benchmark_queries.run()
        assert len(result["queries"]) == 30
        assert all(q["rows"] == 1 for q in result["queries"])
        assert result["dataset_sha256"] == "a" * 64
    connection.start_transaction.assert_called_once_with(readonly=True, consistent_snapshot=True)
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    connection.close.assert_called_once()
    cursor.close.assert_called_once()
