# Evaluating the behavior model (#51)

The agent's next-app choice is driven by a Markov transition model
(`lisa_ml.model.MarkovModel`, served as the `counts` artifact). Issue #51 is
about deciding, once enough real logs exist, whether a richer model (gradient
boosting, an RNN) beats that baseline — and swapping it in without changing the
runtime. `lisa_ml.evaluate` is the harness for that decision.

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

## Running it

```sh
# on synthetic data (no logs needed)
python -m lisa_ml.evaluate --synthetic

# on exported logs from the backend (/events/export)
python -m lisa_ml.evaluate --events events.json
```

Example (synthetic):

```
model             accuracy  n
----------------  --------  -
markov(app)          0.281  395
most_frequent        0.266  395
markov(app_hour)     0.203  395
persist              0.177  395
```

`markov(app)` clears the most-frequent floor; `app_hour` splits states too
finely for this volume. Real logs will shift these numbers — that's the point.

## Adding a candidate (boosting / RNN)

Implement `fit` + `predict_next`, then add a `Candidate` to
`default_candidates()`:

```python
Candidate("gbm", state_app, GradientBoostedNextApp)
```

Keep dependency-heavy models in an optional extra so the base `lisa-ml` package
stays dependency-free. When a candidate wins on real logs, export it in the same
`counts`-shaped artifact (or extend the artifact and the loader together) so the
agent/backend keep working unchanged.
