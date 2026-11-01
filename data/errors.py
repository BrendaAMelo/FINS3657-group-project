# Errors raised by the data layer. Messages are safe to show to users.


class DataError(Exception):
    """Base class for data-layer problems."""


class DataUnavailableError(DataError):
    """Data could not be downloaded or read."""


class DataQualityError(DataError):
    """Data exists but is not good enough to use."""
