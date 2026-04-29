"""SimPy replication of the parameterized warehouse Model 5."""

from .params import Model5Params  # noqa: F401

try:  # pragma: no cover - import depends on optional simpy dependency
    from .model import Model5SimModel  # noqa: F401
except ImportError:  # pragma: no cover - allow params-only imports without simpy
    Model5SimModel = None  # type: ignore[assignment]
