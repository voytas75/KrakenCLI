"""Test configuration providing pandas stubs when real dependency is missing."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from types import SimpleNamespace


try:  # pragma: no cover - executed only when pandas exists
    import pandas  # type: ignore  # noqa: F401
except ModuleNotFoundError:  # pragma: no cover - executed when pandas missing

    class _FakeSeries(list):
        """Minimal list wrapper supporting ``astype`` conversions."""

        def astype(self, dtype):  # type: ignore[override]
            if dtype is float or dtype == float:
                return [float(value) for value in self]
            if dtype is int or dtype == int:
                return [int(value) for value in self]
            return list(self)

    class _FakeDataFrame:
        """Small subset of pandas.DataFrame used in trading engine tests."""

        def __init__(self, data, columns=None):
            if columns is None:
                raise ValueError("columns are required for FakeDataFrame")
            self._columns = list(columns)
            self._data = {col: [] for col in self._columns}
            for row in data:
                for index, column in enumerate(self._columns):
                    self._data[column].append(row[index])

        @property
        def empty(self) -> bool:
            return all(len(values) == 0 for values in self._data.values())

        def __getitem__(self, key):
            if key not in self._data:
                raise KeyError(key)
            return _FakeSeries(self._data[key])

        def __setitem__(self, key, values) -> None:
            self._data[key] = list(values)
            if key not in self._columns:
                self._columns.append(key)

        def __len__(self) -> int:  # pragma: no cover - simple utility
            for column in self._columns:
                return len(self._data[column])
            return 0

        def to_dict(self):  # pragma: no cover - helper parity method
            return dict(self._data)

    def _fake_to_datetime(values, unit="s", utc=True):  # pragma: no cover - deterministic helper
        factor = 1 if unit == "s" else 0.001 if unit == "ms" else 1
        return [
            datetime.fromtimestamp(float(value) * factor, tz=timezone.utc if utc else None)
            for value in values
        ]

    sys.modules["pandas"] = SimpleNamespace(DataFrame=_FakeDataFrame, to_datetime=_fake_to_datetime)
