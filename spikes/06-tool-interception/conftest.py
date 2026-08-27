"""Fail the session if the installed SDK is not the code these gates verified.

Review's negative control: with only `requirements.txt` pinning a version string,
`toolsets/external.py` could be modified and all 18 gates still passed. The pin is
now enforced BEFORE any gate runs, so that mutation is impossible to miss.
"""
import pytest

from verify_pin import PinMismatch, require


def pytest_collection_modifyitems(session, config, items):
    try:
        require()
    except PinMismatch as e:
        pytest.exit(f"\n{e}\n", returncode=3)
