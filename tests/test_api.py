"""Regression tests for the HomgarApi HTTP client itself.

These guard against the exact class of failure that bricked Richard's HA
integration on 2026-04-20: HomGar's HTTPS endpoint silently dropped a
socket mid-response, the underlying ``requests`` call had no ``timeout``
and blocked the coordinator's executor thread indefinitely. After that
the DataUpdateCoordinator's in-flight update never completed and no
further polls fired — the valve switch stayed pinned at its last polled
state for three days.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from homgarapi.api import HomgarApi


def _api_with_mock_session(json_payload):
    sess = MagicMock()
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = json_payload
    resp.text = "ok"
    sess.request.return_value = resp
    api = HomgarApi(auth_cache={"token": "t"}, requests_session=sess)
    return api, sess


def test_request_passes_a_timeout_even_when_caller_does_not_supply_one():
    """Every _request call must be bounded. Otherwise a half-open TCP
    connection from the HomGar cloud can hang the whole coordinator."""
    api, sess = _api_with_mock_session({"code": 0, "data": {}})
    api._get_json("/ping")
    _, kwargs = sess.request.call_args
    assert "timeout" in kwargs, "_request must pass timeout= to requests"
    timeout = kwargs["timeout"]
    assert timeout is not None
    # Accept either a scalar or (connect, read) tuple. What we care about
    # is that *something* is set — the exact value is a tuning knob.
    if isinstance(timeout, tuple):
        connect_s, read_s = timeout
        assert 0 < connect_s <= 30
        assert 0 < read_s <= 120
    else:
        assert 0 < timeout <= 120


def test_caller_supplied_timeout_is_preserved():
    """A caller that explicitly wants a longer read (e.g. for an
    endpoint known to be slow) should not have its value clobbered."""
    api, sess = _api_with_mock_session({"code": 0, "data": {}})
    api._get_json("/slow", timeout=60)
    _, kwargs = sess.request.call_args
    assert kwargs["timeout"] == 60
