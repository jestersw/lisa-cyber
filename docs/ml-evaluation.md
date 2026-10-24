# Evaluating the behavior model (#51)

The agent's next-app choice is driven by a Markov transition model
(`lisa_ml.model.MarkovModel`, served as the `counts` artifact). Issue #51 is
about deciding, once enough real logs exist, whether a richer model beats that
baseline — and swapping it in without changing the runtime. `lisa_ml.evaluate`
is the harness for that decision.

**Outcome so far:** the model shipped as the production inference upgrade is
`BackoffMarkovModel` — first-order Markov that backs off to the global next-app
marginal for states unseen in training. It is *strictly ≥* plain Markov on top-1
accuracy, needs no retraining and uses the **identical `counts` artifact**, so
the swap is zero-risk. Higher-order (`bigram`) and the stateless baselines are
kept in the harness for comparison; higher-order only helps when the real
process has genuine higher-order structure (the first-order synthetic generator
doesn't, so it doesn't win there — real logs may differ).

## The contract

Every candidate implements `NextAppPredictor`: a `predict_next(state) -> str | None`
method (and a `fit(transitions)` to train). `MarkovModel` already satisfies it,
and so does anything we add later. Because the agent and backend consume
`predict_next` / the `counts` artifact, a better model that implements this
contract drops in with no runtime changes.

## Method

- **Split:** `split_events` takes the first `frac` (default 0.8) of each
  agent's events as train and the rest as test, in time order — we never train
  on the future of a sequence we score.
- **Metric:** top-1 accuracy — of the test transitions `(state -> actual next
  app)`, the fraction the model predicts exactly.
- **Baselines:** `most_frequent` (always the global mode; the floor a real
  model must clear) and `persist` (predict the current app again). A stateful
  model that can't beat `most_frequent` isn't earning its complexity.
- **Candidates:** `markov(app)` / `markov(app_hour)` (first-order, two state
  keys), `backoff(app)` / `backoff(app_hour)` (the same with global-marginal
  back-off for unseen states), and `markov(bigram)` / `backoff(bigram)`
  (second-order: state is the previous two apps). Back-off differs from plain
  Markov *only* on states unseen in training, where it guesses the global mode
  instead of nothing — so its accuracy can only match or exceed the baseline.

## Running it

```sh
# on synthetic data (no logs needed)
python -m lisa_ml.evaluate --synthetic

# on exported logs from the backend (/events/export)
python -m lisa_ml.evaluate --events events.json
```

Example — default synthetic (`agents=5, days=10, per_day=40`, dense):

```
model              accuracy  n
-----------------  --------  -
markov(app)           0.281  395
backoff(app)          0.281  395
most_frequent         0.266  395
markov(bigram)        0.256  390
backoff(bigram)       0.256  390
markov(app_hour)      0.203  395
backoff(app_hour)     0.203  395
persist               0.177  395
```

Here every test state was also seen in training, so back-off never triggers and
ties plain Markov; `app_hour` splits states too finely for this volume; and
`bigram` adds sparsity without signal because the generator is first-order.

The back-off win shows up under **sparsity** — fewer events per state, the
realistic-logs regime (`agents=12, days=2, per_day=12`):

```
model              accuracy  n
-----------------  --------  -
most_frequent         0.354  48
markov(app)           0.312  48
backoff(app)          0.312  48
markov(bigram)        0.278  36
backoff(bigram)       0.278  36
backoff(app_hour)     0.271  48
markov(app_hour)      0.250  48
persist               0.229  48
```

`backoff(app_hour)` (0.271) beats `markov(app_hour)` (0.250): the states the
finer key leaves unseen in training now return the global mode instead of a
miss. Real logs will shift these numbers — that's the point; run the harness on
exported logs to pick the winner for your data.

## The runtime swap (already wired)

Back-off is live in production inference. The backend's `next-activity` endpoint,
on a state it has no counts for, now backs off to the model's global marginal
and reports `source: "backoff"` (distinct from `"model"` for a state-specific
prediction and `"fallback"` for no model at all); the agent trusts both `model`
and `backoff` as data-driven. Nothing about the stored artifact changed — the
global marginal is derived from the existing `counts` — so no retraining or
migration was needed. `lisa_ml.model.BackoffMarkovModel` is the offline
equivalent and loads/saves the exact same artifact as `MarkovModel`.

## Adding a heavier candidate (boosting / RNN)

Implement `fit` + `predict_next`, then add a `Candidate` to
`default_candidates()` (a candidate may also carry a custom `transitions`
builder to train on a different state space, as `bigram` does):

```python
Candidate("gbm", state_app, GradientBoostedNextApp)
```

Keep dependency-heavy models in an optional extra so the base `lisa-ml` package
stays dependency-free. When a candidate wins on real logs, export it in the same
`counts`-shaped artifact (or extend the artifact and the loader together) so the
agent/backend keep working unchanged.
