# Unit Testing Guide

## LoRa Network Coverage Mapping Platform

> **Audience.** Developers writing tests for `api-service/`, `ml-service/`, and `worker-service/` (Python), plus `web-app/` and `mobile-app/` (JavaScript). Reviewers checking that PRs uphold the test bar.
>
> **Anchor.** Every rule in this guide traces to a specific chapter of *A Philosophy of Software Design* (Ousterhout, 2018) and to a concrete rule already in `system-architecture.md` or `data-architecture.md`. Tests are not a separate discipline — they are the same design discipline, applied from the outside.
>
> **Non-negotiable.** A PR cannot merge unless the tests it touches obey Sections 2, 3, and 5 of this guide. The `import-linter` rules that apply to production code apply to tests too.

---

## Table of Contents

1. Why tests exist on this platform
2. The five testing principles
3. Which layer to test, and how
4. Test structure conventions
5. Naming
6. Worked examples — one per capability
7. Anti-patterns specific to this codebase
8. Frontend tests (Vitest)
9. Coverage and quality gates
10. Quick reference

---

## 1. Why tests exist on this platform

This platform is donation-funded and open-source. There is no QA team. The flywheel — free lookup → ML map credibility → API ingestion — breaks the moment any of the three core features regresses silently. Tests are the only mechanism that catches regressions before they erode user trust.

Three concrete consequences:

- A bug in `CoverageQuery.predict` that silently returns the wrong stage shows up as map drift over weeks. The recalibration cycle (Stage 1 → Stage 2/3/4 cascade rule) cannot heal data the model has already polluted. Tests must catch this **before** deploy, not after.
- A regression in the lookup latency budget (3 s end-to-end) breaks the funnel. Latency is part of the contract, so it is part of the test suite.
- The four-capability interface is the platform's most important boundary. Tests are how we enforce that boundary day-to-day, after the architects have left the room.

Tests are not insurance. They are the executable form of the architecture.

---

## 2. The five testing principles

These are derived directly from Ousterhout's principles and adapted to this codebase. If a test violates one, rewrite the test — do not bend the principle.

### Principle 1 — Test the interface, not the implementation (Ch. 4, 5)

A test on `CoverageQuery.predict` proves something about the *contract*. If the test fails when the contract is unchanged, the test is wrong. If the test passes when the contract is broken, the test is also wrong.

What this rules out:
- Tests that assert on SQL strings, table names, index names, or query plans.
- Tests that import from `infrastructure/` to "verify" a database write happened. Use the repository's own read methods instead.
- Tests that check whether `predict()` internally chose Stage 2 or Stage 3. The interface specifies `Confidence.source ∈ {PRIMARY, FALLBACK, DEGRADED}` — that is the only stage information a test is allowed to observe.

The smell is uniform: if a test would need to be rewritten when an implementation detail changes (cache backend swap, index choice, stage transition), the test is reaching past the interface.

### Principle 2 — Pull complexity into fixtures, not into every test (Ch. 8)

Test setup that must repeat across many tests — building a `Gateway` with valid antenna parameters, constructing a `SurveyRecord` batch with realistic timestamps, spinning up an in-memory address cache — belongs in fixtures, not in test bodies. Each test body should read like a sentence: *"given X, when Y, then Z."*

Concretely:
- Use `pytest.fixture` for every value object that has more than two fields. `make_gateway()`, `make_survey_record()`, `make_coordinates_in_da_nang()` — these belong in `tests/conftest.py` or a `tests/factories.py` module.
- Defaults in factories are valid and boring. Tests override only the field that matters to that specific test. A test that proves "RSSI below −150 dBm is rejected" should set `rssi_dbm=-160` and accept every other default — it should not also pick a timestamp, a device class, and a gateway id.
- Pull the cascade itself into fixtures where applicable: `address_resolver_with_warm_cache`, `coverage_query_stage1_only`. Tests then read at a single level of abstraction.

### Principle 3 — Errors are values; test the values, not the exceptions (Ch. 10)

The data layer returns `Result[T, E]`. Business errors are *not* exceptions. Tests must reflect this:

- Assert on `Err(PredictionUnavailable(reason=...))`, not on `pytest.raises`.
- An empty `list[Gateway]` from `find()` is a valid result. Test it positively (`assert result == []`), not as an exception case.
- `pytest.raises` is reserved for **unexpected** failures: out-of-memory, DB connection lost, invariant violations. If you find yourself writing `pytest.raises(ValueError)` for a business outcome, the production code likely violates Ch. 10 — fix the production code, not the test.

This is the one place where test code most commonly drags the architecture in the wrong direction. Hold the line.

### Principle 4 — Tests are documentation; they must be obvious (Ch. 18)

Anyone reading a test should understand, from the test alone:

- What input is being supplied.
- What outcome is being asserted.
- Why this case matters.

What this means in practice:
- The "why" lives in the test name. `test_predict_returns_fallback_confidence_when_stage4_unavailable` tells the reader the rule. `test_predict_2` tells them nothing.
- No magic numbers in assertions. `assert pred.rssi_dbm == EXPECTED_RSSI_AT_5KM` reads; `assert pred.rssi_dbm == -123.4` does not.
- One behavior per test. If the test name needs the word "and," split it.

### Principle 5 — Write the test name and docstring before the body (Ch. 15)

Same rule as "comments first," applied to tests. Before writing assertions:

1. Write the test function signature and name.
2. Write a one-line docstring stating the rule under test.
3. **Then** write Arrange / Act / Assert.

If you cannot articulate the rule in one line, the test is not yet ready to be written. Either the production interface is unclear (fix that first), or the case being tested is not actually a rule (delete it).

---

## 3. Which layer to test, and how

The architecture is layered. Tests are layered the same way. A test belongs at the layer where the rule it asserts is actually defined — not higher, not lower.

| Layer | What lives here | What its tests assert | What its tests must NOT do |
|---|---|---|---|
| `api/` (FastAPI routers) | HTTP shape, auth, rate limit | Status codes, request validation, response schema, auth tier enforcement | Re-test business logic that lives in `application/`. Re-test data validation that lives in Pydantic models. |
| `application/services/` | Orchestration across capabilities | Cross-capability flows (e.g. lookup = resolve address + predict coverage); tier → depth mapping; SLA budgets | Test SQL. Test stage selection. Mock the entire repository. |
| `application/domain/` | Value objects, `Confidence`, `Coordinates`, `Result` | Invariants of the value objects (e.g. `Confidence.credible_interval_95` math) | Hit a database. Hit any I/O. |
| `repository/` (4 capabilities) | The contract defined in `data-architecture.md` §6 | The contract: input shape → output shape, including `Result` branches and `Confidence` semantics | Test framework code (FastAPI, SQLAlchemy). Test the underlying provider (don't test that VietMap returns coordinates). |
| `infrastructure/` | Concrete clients (SQLAlchemy, R2, geocoders) | Adapter behavior: the concrete implementation honors the abstract repository interface | Drive the test from the application layer. |

**The matching rule.** A bug fix should add a test at the same layer the bug lived. A bug in `CoverageService.lookup_at_address` (orchestration) gets an `application/` test. A bug in tile cache invalidation gets a `repository/` test. A bug in HTTP 401 handling gets an `api/` test. Tests that drift across layers ("end-to-end test that catches everything") are the most expensive to maintain and the slowest to run — use them sparingly, only for the three core flywheel paths (lookup, map render, survey upload).

### Test doubles — the rule is "fakes over mocks"

The repository interfaces in `data-architecture.md` §6 are deliberately small and fully specified. That makes them easy to **fake**: implement a real, in-memory version of the interface that obeys the same contract.

```python
# tests/fakes/coverage_query_fake.py
class FakeCoverageQuery:
    """In-memory CoverageQuery for application-layer tests.
    Honors the same contract as the real repository: returns Result,
    populates Confidence, raises only on programmer error."""

    def __init__(self) -> None:
        self._predictions: dict[Coordinates, Prediction] = {}

    def predict(
        self,
        target: Coordinates,
        spreading_factor: SpreadingFactor = SpreadingFactor.SF7,
    ) -> Result[Prediction, PredictionUnavailable]:
        pred = self._predictions.get(target)
        if pred is None:
            return Err(PredictionUnavailable(
                reason=UnavailabilityReason.OUT_OF_REGION,
                region_supported=False,
                retry_after_seconds=None,
            ))
        return Ok(pred)

    # Test-only helper, not part of the interface
    def _seed(self, target: Coordinates, prediction: Prediction) -> None:
        self._predictions[target] = prediction
```

Fakes are written **once per capability**, live under `tests/fakes/`, and are reused across every test that needs them. They do not change when production code changes, because they obey the same interface.

`unittest.mock.Mock` is reserved for cases where:
- The collaborator is third-party and outside our interface (a Sentry SDK call, a Prometheus counter).
- A test specifically needs to assert *that a side effect was triggered* (e.g. that the audit log was written exactly once).

For everything we own — repositories, services, ML stages — fakes are the default. The reason is not stylistic: a `Mock` configured to return `Ok(...)` does not verify that production code constructs valid `Coordinates` or that the `Result` was unwrapped correctly. A fake does, because it type-checks.

---

## 4. Test structure conventions

### 4.1 File and folder layout

Each service mirrors its production layout under `tests/`:

```
api-service/
├── app/
│   ├── api/
│   ├── application/
│   ├── repository/
│   └── infrastructure/
└── tests/
    ├── conftest.py                   # shared fixtures
    ├── factories.py                  # value-object builders
    ├── fakes/                        # in-memory repositories
    ├── api/                          # mirrors app/api/
    ├── application/                  # mirrors app/application/
    ├── repository/                   # mirrors app/repository/
    └── infrastructure/               # mirrors app/infrastructure/
```

A test for `app/application/services/coverage_service.py` lives at `tests/application/services/test_coverage_service.py`. No exceptions.

### 4.2 Arrange–Act–Assert, with blank lines between sections

```python
def test_predict_returns_fallback_confidence_when_stage4_unavailable(
    coverage_query: FakeCoverageQuery,
    da_nang_point: Coordinates,
) -> None:
    """When the requested stage is unavailable, the result is still Ok
    but Confidence.source is FALLBACK. No exception is raised."""
    # Arrange
    coverage_query.simulate_stage4_outage()
    coverage_query.seed(da_nang_point, stage1_prediction(da_nang_point))

    # Act
    result = coverage_query.predict(da_nang_point, SpreadingFactor.SF7)

    # Assert
    prediction = unwrap_ok(result)
    assert prediction.confidence.source is ConfidenceSource.FALLBACK
```

The blank lines are not cosmetic. They make the three phases visible at a glance and discourage interleaving setup with assertions.

### 4.3 One assertion idea per test

A test may have multiple `assert` statements, but they must all describe the *same* rule. A test that asserts "RSSI is in range AND timestamp is recent AND gateway id is set" is three tests pretending to be one. When it fails, you don't know which rule broke.

The exception: asserting on a structured result (`prediction.confidence.source`, `prediction.confidence.epistemic_variance`) is one rule about the shape of `Confidence`.

### 4.4 No conditional logic in tests

`if`, `for`, and `try` in test bodies are red flags. They mean the test is computing the expected value rather than stating it. If you find yourself looping over cases, use `pytest.mark.parametrize`:

```python
@pytest.mark.parametrize(
    "rssi_dbm, expected_status",
    [
        (-70.0, CoverageStatus.GOOD),
        (-110.0, CoverageStatus.MARGINAL),
        (-140.0, CoverageStatus.NONE),
    ],
)
def test_coverage_status_thresholds(
    rssi_dbm: float, expected_status: CoverageStatus,
) -> None:
    """RSSI thresholds for GOOD/MARGINAL/NONE are fixed by the
    user-facing layer-1 contract (system-design.md §4.2)."""
    assert classify_coverage(rssi_dbm) is expected_status
```

Each row is one test case. The test runner reports them individually.

---

## 5. Naming

### 5.1 Test functions

Pattern: `test_<unit>_<behavior>_when_<condition>`.

Good:
- `test_predict_returns_fallback_when_stage4_unavailable`
- `test_submit_rejects_record_with_rssi_above_minus_30`
- `test_find_returns_empty_list_when_no_gateway_matches_criteria`
- `test_resolve_does_not_call_paid_provider_when_depth_is_cache_only`

Bad:
- `test_predict` — what about predict?
- `test_predict_works` — works according to whom?
- `test_stage_4_fallback` — not a sentence; doesn't say what's asserted.

The name is the contract under test. If you cannot write the name, the test is not ready.

### 5.2 Fixtures

Pattern: `<noun>_<modifier>` describing the *state*, not the type.

Good: `gateway_in_da_nang`, `survey_batch_with_two_outliers`, `address_resolver_with_warm_cache`.
Bad: `gateway1`, `mock_repo`, `setup_data`.

### 5.3 Test classes (when used)

Group with a `Test<Subject>` class only when several tests share genuine setup that cannot be expressed as a fixture. Most tests should be free functions — classes add ceremony without benefit.

---

## 6. Worked examples — one per capability

Each example is intentionally minimal. The goal is to demonstrate the rule, not to enumerate every case.

### 6.1 `CoverageQuery.predict` — happy path and fallback

```python
# tests/repository/coverage_query/test_predict.py

def test_predict_returns_prediction_with_primary_confidence_for_supported_region(
    coverage_query: CoverageQueryFake,
    da_nang_point: Coordinates,
) -> None:
    """A point in a region operating at its expected stage returns a
    Prediction with Confidence.source = PRIMARY."""
    coverage_query.seed(da_nang_point, stage2_prediction(da_nang_point))

    result = coverage_query.predict(da_nang_point, SpreadingFactor.SF7)

    prediction = unwrap_ok(result)
    assert prediction.confidence.source is ConfidenceSource.PRIMARY


def test_predict_returns_unavailable_for_point_outside_supported_region(
    coverage_query: CoverageQueryFake,
) -> None:
    """A point outside any supported region returns
    Err(PredictionUnavailable), not an exception. The reason field
    distinguishes 'no data yet' from a system fault."""
    point_in_unsupported_region = Coordinates(lat=70.0, lng=120.0)

    result = coverage_query.predict(point_in_unsupported_region)

    err = unwrap_err(result)
    assert err.reason is UnavailabilityReason.OUT_OF_REGION
    assert err.region_supported is False
```

What is *not* tested here: which SQL ran, which index was used, whether the tile came from cache or live inference, which exact stage produced the result. All four are implementation details hidden by the interface (Ch. 5).

### 6.2 `SurveyIngest.submit` — partial rejection is a value, not an error

```python
# tests/repository/survey_ingest/test_submit.py

def test_submit_accepts_valid_records_and_lists_rejected_records_in_receipt(
    survey_ingest: SurveyIngestFake,
    valid_uploader: UploaderIdentity,
    da_nang_point: Coordinates,
) -> None:
    """A batch with one out-of-range RSSI record is partially accepted:
    the receipt reports the rejection. The whole batch does not fail.
    (data-architecture.md §6.3 — Mask Exceptions, Ch. 10.)"""
    valid_record = make_survey_record(location=da_nang_point, rssi_dbm=-95.0)
    invalid_record = make_survey_record(location=da_nang_point, rssi_dbm=-200.0)

    result = survey_ingest.submit(
        records=[valid_record, invalid_record],
        uploader=valid_uploader,
    )

    receipt = unwrap_ok(result)
    assert receipt.accepted_count == 1
    assert len(receipt.rejected) == 1
    assert receipt.rejected[0].field == "rssi_dbm"
```

This test enforces a non-obvious rule: a batch with bad records is still `Ok`, not `Err`. Forgetting this rule and changing the implementation to raise would silently break uploaders who expect partial success — which is most of them.

### 6.3 `GatewayDirectory.find` — empty result is valid

```python
# tests/repository/gateway_directory/test_find.py

def test_find_returns_empty_list_when_no_gateway_matches_criteria(
    gateway_directory: GatewayDirectoryFake,
) -> None:
    """No matches is a valid outcome of a query, not an error.
    The caller iterates the list; an empty list is the natural empty
    iteration. (Ch. 10, 'design special cases out of existence'.)"""
    empty_region = Polygon(
        points=[
            Coordinates(lat=10.0, lng=100.0),
            Coordinates(lat=10.0, lng=100.1),
            Coordinates(lat=10.1, lng=100.1),
            Coordinates(lat=10.1, lng=100.0),
        ]
    )

    gateways = gateway_directory.find(GatewayCriteria(within=empty_region))

    assert gateways == []
```

What we do *not* do: check `pytest.raises(NotFoundError)`. There is no such error. A `find` that returns an empty list is the design.

### 6.4 `AddressResolution.resolve` — depth controls cost, not tier

```python
# tests/repository/address_resolution/test_resolve.py

def test_resolve_does_not_call_paid_provider_when_depth_is_cache_only(
    spy_geocoding_clients: GeocodingClientSpies,
    address_resolution: AddressResolutionWithSpies,
) -> None:
    """The paid (Google) provider is not invoked when depth is
    CACHE_ONLY, regardless of cache state. (data-architecture.md §6.5
    — the data layer enforces the cost rule by construction.)"""
    address = "123 Lê Lợi, Đà Nẵng"

    address_resolution.resolve(address, depth=GeocodingDepth.CACHE_ONLY)

    assert spy_geocoding_clients.google.call_count == 0
```

This is one of the rare cases where asserting on a side-effect — "the paid client was not called" — is the right test. The whole point of `GeocodingDepth` is to make this rule structural; the test verifies the rule holds. A spy is appropriate here; a fake would not capture the call count.

Note also what is *not* asserted: nothing about user tier. The repository test does not know about tiers. The tier-to-depth mapping is tested at the application layer.

### 6.5 Application-layer test — orchestration with fakes

```python
# tests/application/services/test_coverage_service.py

def test_lookup_at_address_uses_cache_only_depth_for_community_tier(
    coverage_service_with_fakes: CoverageService,
    fake_address_resolution: AddressResolutionFake,
) -> None:
    """A community-tier user's address lookup must use CACHE_AND_LOCAL
    depth at most. The application service is responsible for the
    tier → depth mapping. The repository never sees the tier."""
    request = LookupRequest(
        address="Đà Nẵng",
        tier=Tier.COMMUNITY,
    )

    coverage_service_with_fakes.lookup_at_address(request)

    last_call = fake_address_resolution.calls[-1]
    assert last_call.depth in (
        GeocodingDepth.CACHE_ONLY,
        GeocodingDepth.CACHE_AND_LOCAL,
    )
```

The test crosses one layer (service → repository) but stops there. It does not verify which provider was finally called — that is the repository's job and is tested in 6.4.

---

## 7. Anti-patterns specific to this codebase

These are tests we have seen, or expect to see, that violate the rules above. Each is paired with the correct fix.

### 7.1 Asserting on the ML stage

```python
# WRONG
result = coverage_query.predict(point)
assert result.value._stage == 4
```

The interface deliberately hides the stage. Reaching past it via a private attribute couples every test to the stage roadmap. When the model graduates a region from Stage 3 to Stage 4, every such test breaks for no real reason.

```python
# RIGHT
prediction = unwrap_ok(coverage_query.predict(point))
assert prediction.confidence.source is ConfidenceSource.PRIMARY
assert prediction.confidence.total_variance < 5.0
```

The visible contract says: the prediction has a confidence, and the source is one of three values. That's what tests can rely on.

### 7.2 Mocking SQLAlchemy

```python
# WRONG
mock_session = Mock()
mock_session.execute.return_value.scalar.return_value = ...
service = CoverageService(session=mock_session)
```

This mocks the wrong layer and tests the wrong thing. SQLAlchemy is infrastructure; the application service should not even know it exists. A test that mocks a session is a test that has crossed `application/` → `infrastructure/`, which the linter forbids in production code and which we forbid in tests too.

```python
# RIGHT
service = CoverageService(coverage_query=FakeCoverageQuery())
```

### 7.3 Drive-by refactoring in test files

A bug fix in `coverage_service.py` should not also reformat the imports of `test_coverage_service.py` or rename five unrelated fixtures. The same surgical-changes rule applies to test files. Tests are code; they earn their place line by line.

### 7.4 Assertions on log messages

```python
# WRONG
caplog.set_level(logging.INFO)
service.do_thing()
assert "thing done" in caplog.text
```

Log messages are not part of the contract. They change for product reasons (translation, structured logging, severity tuning) without the contract changing. If the rule under test is "an audit row was written," assert on the audit table. If the rule is "an alert was emitted," assert on the metric counter.

### 7.5 Re-asserting Pydantic validation in router tests

`api/v1/coverage.py` accepts a Pydantic model `CoveragePointRequest`. The model already enforces `Field(ge=-90, le=90)` on `lat`. A test that POSTs a bad latitude and asserts a 422 has tested Pydantic, not our code. It is duplication of the framework's own test suite. Skip it.

What is worth testing at the router layer: that the right tier is enforced; that the response schema matches OpenAPI; that the right `Result` branch translates to the right HTTP status code (`PredictionUnavailable` → 200 with payload, *not* 404 — that's a domain decision worth pinning).

### 7.6 Helper functions that hide the test's argument

```python
# WRONG
def test_predict_in_da_nang() -> None:
    assert_predict_works(da_nang_point)
```

`assert_predict_works` hides every assertion behind a name that says nothing. If five tests call it, five tests assert the same thing. The reader has to jump to the helper to learn what the test does. Inline the assertions.

A helper is appropriate only when (a) it has a clear and narrow job, like `unwrap_ok(result)`, and (b) the alternative — repeating the same five lines in every test — would obscure the test's actual content. Even then, the helper does *not* contain assertions about the domain. `unwrap_ok` asserts the result is `Ok`; it does not assert anything about the value inside.

### 7.7 Performance assertions in unit tests

```python
# WRONG
start = time.perf_counter()
service.predict(point)
elapsed = time.perf_counter() - start
assert elapsed < 0.2  # P95 budget
```

The 200 ms budget is real (`data-architecture.md` §6.2), but a unit test runs on a contended CI box and measures a single sample. It is a flaky proxy for the real SLA. Latency budgets are tested by load tests in CI (`k6`, scheduled nightly), not by unit tests.

What unit tests *can* assert about performance: that hot-path methods do not invoke a paid provider; that a single `predict` call does not cause N database round-trips (use a query counter on the test session in `infrastructure/` tests only).

---

## 8. Frontend tests (Vitest)

The same five principles apply. Two specifics:

### 8.1 Test components by user-visible behavior, not by implementation

Use `@testing-library/react`. Find elements by accessible role and label, not by `data-testid` or by `className`. A test that breaks because someone refactored `useState` to `useReducer` is testing the wrong thing.

```js
// Right
const status = await screen.findByRole('status');
expect(status).toHaveTextContent(/good signal/i);

// Wrong — couples test to internal markup
expect(container.querySelector('.lookup-result__badge--good')).toBeTruthy();
```

### 8.2 The API client is the seam, not the endpoint

Mock `apiClient.lookupCoverage(...)` at the module boundary. Do not mock `fetch` and reconstruct the network. Tests that rebuild the network shape are tests against the network framework, not against our code.

```js
import { vi } from 'vitest';
import { lookupCoverage } from '@/services/coverageApi';

vi.mock('@/services/coverageApi', () => ({
  lookupCoverage: vi.fn(),
}));

it('shows GOOD status when coverage is good', async () => {
  vi.mocked(lookupCoverage).mockResolvedValue({
    rssi_dbm: -75,
    snr_db: 9.5,
    status: 'GOOD',
    serving_gateway_id: 'gw_da_nang_01',
    confidence: { value: 0.9, source: 'PRIMARY' },
  });

  render(<LookupForm />);
  await userEvent.type(screen.getByLabelText(/address/i), 'Đà Nẵng');
  await userEvent.click(screen.getByRole('button', { name: /check/i }));

  expect(await screen.findByRole('status'))
    .toHaveTextContent(/good signal/i);
});
```

The Zod schema in `apiClient` is what guarantees the shape; the component test trusts that and focuses on user-visible behavior.

---

## 9. Coverage and quality gates

These match `system-architecture.md` §9.4. They are floors, not goals.

| Service | Tool | Floor | Where the floor binds |
|---|---|---|---|
| `api-service`, `ml-service`, `worker-service` | `pytest --cov` | 80% line, 80% branch on `application/` and `repository/` | CI fails below |
| `web-app`, `mobile-app` | `vitest --coverage` | 70% on `features/` and `lib/` | CI fails below |
| Critical user paths | Playwright | The three flywheel paths green | CI fails on red |

Coverage above the floor is welcome but not the metric we optimize. **A 100%-covered codebase whose tests violate Section 2 is worse than a 75%-covered codebase whose tests are obvious.** Reviewers should be willing to block a PR for unobvious tests even when coverage rises.

`infrastructure/` is intentionally not subject to a high floor. Adapter code is tested by integration with a real Postgres in `tests/infrastructure/` using `testcontainers`. These tests are slower and run in the nightly job, not on every push.

---

## 10. Quick reference

### 10.1 Decision tree — where does my test go?

1. The rule is "this HTTP shape, this status code" → `tests/api/`.
2. The rule is "this orchestration across capabilities, this tier mapping" → `tests/application/services/`.
3. The rule is "this value object invariant" → `tests/application/domain/`.
4. The rule is "this repository contract" → `tests/repository/<capability>/` with a fake.
5. The rule is "this adapter honors the repository interface" → `tests/infrastructure/` with `testcontainers`.
6. The rule is "all three of the above hold for the lookup flow end-to-end" → one Playwright test, no more.

### 10.2 Five things to check before pushing

1. Every test name reads as a sentence describing a rule.
2. No test imports from `infrastructure/` unless it lives in `tests/infrastructure/`.
3. No test asserts on stage number, SQL, log text, or CSS class.
4. No test uses `pytest.raises` for a `Result` branch.
5. Every fixture used by more than one test lives in `conftest.py` or `factories.py`.

### 10.3 The five principles in one line each

1. Test the interface, not the implementation. (Ch. 4, 5)
2. Pull complexity into fixtures. (Ch. 8)
3. Errors are values; test the values. (Ch. 10)
4. Tests are documentation; they must be obvious. (Ch. 18)
5. Write the test name first. (Ch. 15)

---

*End of document.*