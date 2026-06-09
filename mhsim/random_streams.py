"""Pseudo-random streams used to mirror external simulation runtimes."""

from __future__ import annotations

import math


class JavaRandom:
    """Minimal Python implementation of ``java.util.Random``.

    AnyLogic's default probability distributions are based on Java's
    ``java.util.Random``. This class lets parity models consume the same raw
    pseudo-random stream from the same seed.
    """

    _MULTIPLIER = 0x5DEECE66D
    _ADDEND = 0xB
    _MASK = (1 << 48) - 1

    def __init__(self, seed: int = 0) -> None:
        self.set_seed(seed)

    def set_seed(self, seed: int) -> None:
        self._seed = (int(seed) ^ self._MULTIPLIER) & self._MASK

    def next(self, bits: int) -> int:
        if not 0 < bits <= 32:
            raise ValueError(f"bits must be in 1..32, got {bits}")
        self._seed = (self._seed * self._MULTIPLIER + self._ADDEND) & self._MASK
        return self._seed >> (48 - bits)

    def next_double(self) -> float:
        return ((self.next(26) << 27) + self.next(27)) / float(1 << 53)

    def random(self) -> float:
        return self.next_double()

    def next_int(self, bound: int | None = None) -> int:
        if bound is None:
            value = self.next(32)
            return value - (1 << 32) if value >= (1 << 31) else value

        bound = int(bound)
        if bound <= 0:
            raise ValueError(f"bound must be positive, got {bound}")

        if bound & (bound - 1) == 0:
            return (bound * self.next(31)) >> 31

        while True:
            bits = self.next(31)
            value = bits % bound
            if self._signed_32(bits - value + (bound - 1)) >= 0:
                return value

    @staticmethod
    def _signed_32(value: int) -> int:
        value &= 0xFFFFFFFF
        return value - (1 << 32) if value >= (1 << 31) else value

    def randint(self, a: int, b: int) -> int:
        if b < a:
            raise ValueError(f"empty randint range: {a}..{b}")
        return int(a) + self.next_int(int(b) - int(a) + 1)

    def expovariate(self, rate: float) -> float:
        rate = float(rate)
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        return -math.log(1.0 - self.random()) / rate

    def triangular(self, low: float, high: float, mode: float) -> float:
        low = float(low)
        high = float(high)
        mode = float(mode)
        if high < low:
            raise ValueError(f"high must be >= low, got low={low}, high={high}")
        if high == low:
            return low
        if mode < low or mode > high:
            raise ValueError(
                f"mode must be inside [low, high], got low={low}, "
                f"high={high}, mode={mode}"
            )

        u = self.random()
        c = (mode - low) / (high - low)
        if u <= c:
            return low + math.sqrt(u * (high - low) * (mode - low))
        return high - math.sqrt((1.0 - u) * (high - low) * (high - mode))
