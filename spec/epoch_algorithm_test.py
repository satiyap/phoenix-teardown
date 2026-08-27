"""Verify the normative rewind algorithm from spec/04-events.md against the
defect it replaces. Oracle is independent: hand-written expected live sets."""
from dataclasses import dataclass

@dataclass
class E:
    seq: int; epoch: int; event_type: str; payload: dict

def live(events):
    cuts = [(e.payload["to_epoch"], e.payload["from_seq"])
            for e in events if e.event_type == "run.rewound"]
    return [e for e in events
            if e.event_type != "run.rewound"
            and not any(e.epoch <= to_e and e.seq >= from_s for to_e, from_s in cuts)]

def naive(events):
    """The defective rule this replaces."""
    out = list(events)
    for e in events:
        if e.event_type == "run.rewound":
            fs = e.payload["from_seq"]
            out = [x for x in out if x.seq < fs]
    return out

def mk(*specs):
    return [E(s, ep, t, p or {}) for s, ep, t, p in specs]

# rewind at seq 6 supersedes epoch-0 events with seq >= 4; epoch 1 continues
log = mk((1,0,"run.created",None), (2,0,"run.started",None), (3,0,"run.progressed",None),
         (4,0,"run.progressed",None), (5,0,"run.progressed",None),
         (6,1,"run.rewound",{"to_epoch":0,"from_seq":4}),
         (7,1,"run.progressed",None), (8,1,"run.succeeded",None))

print("A. continuation after rewind")
print("   spec  live seqs:", [e.seq for e in live(log)],  "  <- expect [1,2,3,7,8]")
print("   naive live seqs:", [e.seq for e in naive(log)], "  <- DEFECT: post-rewind gone")
assert [e.seq for e in live(log)] == [1,2,3,7,8]
assert [e.seq for e in naive(log)] == [1,2,3]

# a rewind of a rewind
log2 = log + mk((9,2,"run.rewound",{"to_epoch":1,"from_seq":7}),
                (10,2,"run.progressed",None))
print("\nB. composed rewinds")
print("   spec  live seqs:", [e.seq for e in live(log2)], "  <- expect [1,2,3,10]")
assert [e.seq for e in live(log2)] == [1,2,3,10]

print("\nC. no rewind -> everything live")
plain = mk((1,0,"run.created",None),(2,0,"run.succeeded",None))
assert [e.seq for e in live(plain)] == [1,2]
print("   ok")
print("\nALL PASS — the epoch algorithm permits continuation; the naive rule does not.")
