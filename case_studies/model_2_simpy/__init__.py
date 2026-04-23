"""SimPy replication of AnyLogic Model 2 simplified transporter flow."""

from .params import Model2Params  # noqa: F401

try:  # pragma: no cover - import depends on optional simpy dependency
    from .model import Model2SimModel  # noqa: F401
except ImportError:  # pragma: no cover - allow params-only imports without simpy
    Model2SimModel = None  # type: ignore[assignment]
