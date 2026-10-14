from datetime import date

import pytest

from demo_access import DemoLimitError, DemoQuota


def test_minute_window_and_day_reset():
    now, day = [0.0], [date(2026, 10, 14)]
    quota = DemoQuota(per_day=3, clock=lambda: now[0], today=lambda: day[0])
    for _ in range(2):
        with quota.reserve():
            pass
    with pytest.raises(DemoLimitError, match="por minuto"):
        with quota.reserve():
            pass
    now[0] = 60
    with quota.reserve():
        pass
    with pytest.raises(DemoLimitError, match="diaria"):
        with quota.reserve():
            pass
    now[0] = 120
    day[0] = date(2026, 10, 15)
    with quota.reserve():
        pass


def test_busy_request_does_not_consume_quota_and_errors_release_lock():
    quota = DemoQuota(per_minute=10, per_day=2)
    with pytest.raises(RuntimeError, match="provider"):
        with quota.reserve():
            with pytest.raises(DemoLimitError, match="otra consulta"):
                with quota.reserve():
                    pass
            raise RuntimeError("provider")
    with quota.reserve():
        pass
    with pytest.raises(DemoLimitError, match="diaria"):
        with quota.reserve():
            pass
