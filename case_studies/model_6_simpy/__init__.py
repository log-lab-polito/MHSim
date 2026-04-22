"""SimPy replication of AnyLogic Model 6 simplified transporter flow."""

from .params import Model6Params  # noqa: F401

try:  # pragma: no cover - import depends on optional simpy dependency
    from .model import Model6SimModel  # noqa: F401
except ImportError:  # pragma: no cover - allow params-only imports without simpy
    Model6SimModel = None  # type: ignore[assignment]
