"""Simple unit conversion module.

Provides functions to convert temperatures (Celsius -> Fahrenheit)
and distances (Kilometers -> Miles).
"""


def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert a temperature from Celsius to Fahrenheit.

    Args:
        celsius: Temperature in degrees Celsius.

    Returns:
        Temperature in degrees Fahrenheit.
    """
    return (celsius * 9.0 / 5.0) + 32.0


def fahrenheit_to_celsius(fahrenheit: float) -> float:
    """Convert a temperature from Fahrenheit to Celsius.

    Args:
        fahrenheit: Temperature in degrees Fahrenheit.

    Returns:
        Temperature in degrees Celsius.
    """
    return (fahrenheit - 32.0) * 5.0 / 9.0


def km_to_miles(km: float) -> float:
    """Convert a distance from kilometers to miles.

    Args:
        km: Distance in kilometers.

    Returns:
        Distance in miles.
    """
    return km * 0.621371


def miles_to_km(miles: float) -> float:
    """Convert a distance from miles to kilometers.

    Args:
        miles: Distance in miles.

    Returns:
        Distance in kilometers.
    """
    return miles / 0.621371
