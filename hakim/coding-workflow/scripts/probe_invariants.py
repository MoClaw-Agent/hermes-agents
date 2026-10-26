# Probing a pipeline's invariants

Use when you must establish whether a code path *actually* enforces its stated
guarantees, or when a suspicious line looks like it does nothing. The point is
to produce evidence, not to reason about the code: write a throwaway script that
drives the real objects and prints the observed outcome.

Put probes in the scratch dir, never in the repo's test tree — they are
investigation, not regression coverage. Promote the ones that pin a real defect
into proper tests afterwards (see the `coding-workflow` rule on tests that were
written around a defect).

## The six probe shapes

Each of these found a real defect that a green suite and a clean lint run had
missed. Adapt the shape; the value is in asking the question mechanically.

A coverage table is not a substitute for these. Asserting *that* something was
captured passes for a pipeline whose output is inverted, truncated or attributed
to the wrong source — probe 6 is the one that catches meaning, and it needs a
polarity pair rather than more samples of the same polarity.

### 1. Dead parameter — does the value reach the callee?

Record what the collaborator actually receives, rather than trusting the call
site to pass it.

```python
class Recorder:
    def __init__(self):
        self.seen = []
    def method_under_test(self, first_arg, *a, **kw):
        self.seen.append(first_arg)
        return []

rec = Recorder()
obj = Subject(config=cfg, dep=rec)
obj.public_entry("THE_VALUE_THAT_MATTERS", [{"other": "input"}])
print("callee saw:", rec.seen)   # empty or wrong => the parameter is dead
```

A parameter can be declared, accepted, and never used — the classic form is a
loop or ternary whose branches are identical (`x if cond is None else x`).

### 2. Latch vs per-unit key — does the second call still work?

Anything that records "already processed" is a candidate for a key that is too
coarse. Drive it repeatedly and compare counts.

```python
counts = []
for i in range(3):
    counts.append(len(obj.process(f"unit {i}", session="S")))
print("per-call results:", counts)   # [1, 0, 0] => keyed per-session, not per-unit
```

`[1, 0, 0]` is the signature of an idempotency key that latches on the first
call and silently drops everything after it.

### 3. Guard bypass — is the invariant enforced where it must be?

Construct the input the guard exists to reject, and confirm it is rejected **for
the right reason**. A pass for the wrong reason is not a pass: if you suspect a
trust check, make the *other* checks pass so the one under test is the only thing
that can reject it.

```python
# Make evidence valid so that ONLY the trust model can reject this candidate.
probe = {"content": "an assistant claim",
         "evidence": "an assistant claim",   # genuinely present in the source
         "source": "user",                    # tries to override attribution
         "confidence": 0.9}
```

### 4. Wrong-side comparison — is the guard checking the attacker's own data?

Give the producer a claim that quotes itself as its own proof. If it passes, the
guard compares the candidate against itself rather than against the source.

```python
probe = {"content": "the user's api key is hunter2",   # absent from the source
         "evidence": "the user's api key",               # but inside content
         "confidence": 0.99}
```

### 5. Missing write — did the required side effect happen?

For each state change a spec requires, perform the action and query for its
trace. Absence is the finding.

```python
table = "memory_history"
obj.create("x")
obj.update(1, content="y")
obj.pin(1)
con = sqlite3.connect(db)
print(con.execute(
    f"SELECT action, COUNT(*) FROM {table} GROUP BY action").fetchall())
# only ['archive', 'restore', 'delete'] => create/update/pin were never written
```

### 6. Inverted derivation — does the derived value keep the source's meaning?

For any step that *labels*, *normalises*, *summarises* or *rewrites* a value, the
output can be present, well-formed and the exact opposite of the input. Presence
is not correctness, so probe a **polarity pair**: feed a positive and a negative
form and assert the derived results differ in the right direction.

```python
for text in ["prefer tabs", "never push to master", "always run tests"]:
    out = derive(text)
    print(f"{text!r} -> {out[0]['content']!r}")
# 'never push to master' -> 'user prefers push to master'  => INVERTED
```

A single positive sample cannot show this: the negation is handled by the same
code path and produces equally plausible output. The mechanism to look for is a
pattern with alternation (`(?:prefer|always|never)`) collapsed into **one**
capture group, so the verb that distinguishes the cases is discarded and a fixed
prefix is applied to all of them. Count the distinct semantics the pattern
matches and confirm the output distinguishes them too.

## Reporting

State what you observed, with the command and its output. Distinguish:

- **rejected** — the guard fired and the bad input was refused;
- **accepted** — the bad input got through (the defect);
- **rejected for another reason** — a different check caught it first, so the
  guard under test is still unverified. Re-probe with the others satisfied.

That third case is the one that produces false "fixed" reports. Name which of
the three you observed, every time.
