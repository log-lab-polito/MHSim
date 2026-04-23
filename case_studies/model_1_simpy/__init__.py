"""SimPy replication of the parameterized warehouse Model 1."""

from .params import Model1Params  # noqa: F401

try:  # pragma: no cover - import depends on optional simpy dependency
    from .model import Model1SimModel  # noqa: F401
except ImportError:  # pragma: no cover - allow params-only imports without simpy
    Model1SimModel = None  # type: ignore[assignment]
