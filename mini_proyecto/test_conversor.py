"""Unit tests for the conversor module."""

import unittest

from conversor import (
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    km_to_miles,
    miles_to_km,
)


class TestTemperatureConversion(unittest.TestCase):
    def test_celsius_to_fahrenheit_freezing(self):
        self.assertAlmostEqual(celsius_to_fahrenheit(0), 32.0)

    def test_celsius_to_fahrenheit_boiling(self):
        self.assertAlmostEqual(celsius_to_fahrenheit(100), 212.0)

    def test_celsius_to_fahrenheit_negative(self):
        self.assertAlmostEqual(celsius_to_fahrenheit(-40), -40.0)

    def test_celsius_to_fahrenheit_body(self):
        self.assertAlmostEqual(celsius_to_fahrenheit(37), 98.6)

    def test_fahrenheit_to_celsius_roundtrip(self):
        self.assertAlmostEqual(fahrenheit_to_celsius(celsius_to_fahrenheit(25)), 25.0)


class TestDistanceConversion(unittest.TestCase):
    def test_km_to_miles_zero(self):
        self.assertAlmostEqual(km_to_miles(0), 0.0)

    def test_km_to_miles_one(self):
        self.assertAlmostEqual(km_to_miles(1), 0.621371)

    def test_km_to_miles_marathon(self):
        self.assertAlmostEqual(km_to_miles(42.195), 26.2188, places=3)

    def test_miles_to_km_roundtrip(self):
        self.assertAlmostEqual(miles_to_km(km_to_miles(10)), 10.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
