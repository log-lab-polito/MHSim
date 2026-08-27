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
        """Create a stream seeded exactly as `java.util.Random` would be.

        Args:
            seed: Seed value. Scrambled on assignment, matching Java.
        """
        self.set_seed(seed)

    def set_seed(self, seed: int) -> None:
        """Reseed the stream, restarting it from a known point.

        Args:
            seed: Seed value, scrambled with the LCG multiplier exactly as
                Java's `setSeed` does.
        """
        self._seed = (int(seed) ^ self._MULTIPLIER) & self._MASK

    def next(self, bits: int) -> int:
        """Advance the generator and return its top `bits` bits.

        This is the primitive every other method is built on; matching it
        exactly is what makes the whole stream reproduce Java's.

        Args:
            bits: How many bits to return, in `1..32`.

        Returns:
            An unsigned integer of the requested width.

        Raises:
            ValueError: If `bits` is outside `1..32`.
        """
        if not 0 < bits <= 32:
            raise ValueError(f"bits must be in 1..32, got {bits}")
        self._seed = (self._seed * self._MULTIPLIER + self._ADDEND) & self._MASK
        return self._seed >> (48 - bits)

    def next_double(self) -> float:
        """Draw a float uniformly from `[0, 1)`.

        Returns:
            The next double in the stream, assembled from a 26-bit and a
            27-bit draw as Java's `nextDouble` does.
        """
        return ((self.next(26) << 27) + self.next(27)) / float(1 << 53)

    def random(self) -> float:
        """Draw a float uniformly from `[0, 1)`.

        Alias for `next_double`, provided so instances satisfy the parts of
        the `random.Random` interface that MHSim's samplers rely on.

        Returns:
            The next double in the stream.
        """
        return self.next_double()

    def next_int(self, bound: int | None = None) -> int:
        """Draw an integer, optionally bounded.

        Args:
            bound: Exclusive upper bound. When omitted, returns a signed
                32-bit integer over the full range, as Java's no-argument
                `nextInt` does.

        Returns:
            A signed 32-bit integer when `bound` is `None`, otherwise a
            value in `[0, bound)`.

        Raises:
            ValueError: If `bound` is given but not positive.
        """
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
        """Draw an integer uniformly from the inclusive range `[a, b]`.

        Args:
            a: Lower bound, inclusive.
            b: Upper bound, inclusive.

        Returns:
            A value in `[a, b]`.

        Raises:
            ValueError: If `b` is less than `a`.
        """
        if b < a:
            raise ValueError(f"empty randint range: {a}..{b}")
        return int(a) + self.next_int(int(b) - int(a) + 1)

    def expovariate(self, rate: float) -> float:
        """Draw from an exponential distribution by inverse transform.

        Args:
            rate: Rate parameter in inverse seconds; the mean is `1 / rate`.

        Returns:
            One exponential draw.

        Raises:
            ValueError: If `rate` is not strictly positive.
        """
        rate = float(rate)
        if rate <= 0:
            raise ValueError(f"rate must be positive, got {rate}")
        return -math.log(1.0 - self.random()) / rate

    def triangular(self, low: float, high: float, mode: float) -> float:
        """Draw from a triangular distribution by inverse transform.

        Args:
            low: Lower bound of the support.
            high: Upper bound of the support.
            mode: Peak of the density; must lie within `[low, high]`.

        Returns:
            One triangular draw, or `low` when the support is degenerate.

        Raises:
            ValueError: If `high` is below `low`, or `mode` falls outside
                the support.
        """
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
