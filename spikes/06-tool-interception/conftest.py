"""Fail the session if the installed SDK is not the code these gates verified.

Review's negative control: with only `requirements.txt` pinning a version string,
`toolsets/external.py` could be modified and all 18 gates still passed. Round 2
pinned five files and left `native_tools/__init__.py` -- the module gate 6 reads
to decide which tools may be admitted -- unpinned, so the same control worked
there. The pin is checked BEFORE any gate runs, over every SDK file the spike's
behaviour depends on (`verify_pin.REQUIRED_PINS`), so either mutation aborts
collection instead of passing.

`test_gate0_negative_control_a_mismatched_pin_aborts_COLLECTION` asserts this
hook actually aborts, in a copy of the spike it owns.
"""
import pytest

from verify_pin import PinMismatch, require


def pytest_collection_modifyitems(session, config, items):
    try:
        require()
    except PinMismatch as e:
        pytest.exit(f"\n{e}\n", returncode=3)
