# Glossary

Each technical term has a heading and one plain sentence. Link a term to its heading
the first time it appears in each file. `make check-docs` checks this.

## Backtest

A test that replays the past: at each past month, fit the model on the data known then
and score its forecast against what happened next.

## Baseline

A simple method, such as always guessing the most common answer, that a model must
beat to be worth using.

## Basis point

One hundredth of a percentage point. An arrears rate of 0.20% is 20 basis points. <!-- not-a-claim -->

## Bootstrap

A way to see how much a number could change: draw many new samples from the test rows,
with repeats allowed, and compute the number again on each one.

## Confidence interval

A range around a measured number that shows how much the number could move if the
test were run again on new data.

## Interval coverage

The share of actual values that land inside their forecast intervals.
An 80% interval should catch about 80% of them. <!-- not-a-claim -->

## Mean absolute error

The average size of a miss, in the same units as the thing being predicted. Lower is
better.

## Persistence forecast

A forecast that says the next value will equal the latest known value.

## Prediction interval

A range that a future value should fall inside with a stated chance, such as 80%. <!-- not-a-claim -->

## Vintage

One published version of a data series. Later vintages can revise past numbers.
