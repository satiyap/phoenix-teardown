"""GATE 01c — is the compatibility layer PUBLIC COMPOSITION or a FORK?

Invariant: we must be able to own dedupe WITHOUT replacing Hub internals.
If we must monkeypatch or subclass over a private, it is a maintained fork.
"""
import inspect
import pytest
from ag2.network import Hub
from ag2.network.hub.core import Hub as CoreHub

# sync tests: no asyncio mark needed


def test_dedupe_is_only_called_from_rpc_dispatch_not_the_post_path():
    """The ownership question, precisely.

    If the hub consulted find_envelope_by_causation while ACCEPTING an envelope,
    owning dedupe would mean replacing a hub method -> maintained fork. It does
    not: the single self-call is in the RPC dispatch table, routing a REMOTE
    request. post_envelope never consults it.
    """
    src = inspect.getsource(CoreHub)
    assert src.count("self.find_envelope_by_causation") == 1

    # the call site sits under the RPC op dispatcher, not in post_envelope
    lines = src.splitlines()
    idx = next(i for i, l in enumerate(lines) if "self.find_envelope_by_causation" in l)
    window = "\n".join(lines[max(0, idx - 6):idx])
    assert 'op == "find_envelope_by_causation"' in window, window
    print("\n  the 1 self-call is RPC routing, not the accept path")

    # and prove post_envelope itself does not consult it
    post_src = inspect.getsource(CoreHub.post_envelope)
    assert "find_envelope_by_causation" not in post_src
    print("  post_envelope does NOT consult it -> dedupe is ours to own")


def test_post_envelope_and_read_wal_are_public():  # noqa: sync ok
    """The two operations our layer needs must both be public API."""
    for name in ("post_envelope", "read_wal", "find_envelope_by_causation"):
        assert not name.startswith("_")
        assert hasattr(Hub, name), name
    print("  post_envelope / read_wal / find_envelope_by_causation all public")


def test_our_layer_needs_no_private_access():
    """Composition check: a wrapper using only public members is sufficient."""
    class DedupingHub:
        """Owns dedupe; delegates everything else. No private access."""
        def __init__(self, hub, ledger):
            self._hub, self._ledger = hub, ledger

        async def post_with_claim(self, envelope):
            key = (envelope.channel_id, envelope.sender_id, envelope.causation_id)
            if not self._ledger.claim(*key):
                return None                      # already executed elsewhere
            return await self._hub.post_envelope(envelope)   # public

        def __getattr__(self, item):             # delegate the rest
            return getattr(self._hub, item)

    privates = [n for n in inspect.getsource(DedupingHub).split()
                if n.startswith("hub._") or "._causation_index" in n]
    assert privates == [], f"wrapper touches privates: {privates}"
    print("  wrapper uses public members only -> ADAPTER, not fork")
