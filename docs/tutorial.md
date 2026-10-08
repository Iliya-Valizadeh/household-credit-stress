# Tutorial

This page walks you through one full run of household-credit-stress, from a fresh clone to
the demo output. You need `uv`, `make`, and the Python version named in
`pyproject.toml`. `uv` can install that Python for you.

## Step 1: get the code

```bash
git clone https://github.com/Iliya-Valizadeh/household-credit-stress.git
cd household-credit-stress
```

## Step 2: install

```bash
make setup
```

## Step 3: run the demo

```bash
make demo
```

TODO: say what the reader should see when the demo finishes.

Until you replace the template example, the demo makes a small synthetic dataset. It
fits a [baseline](glossary.md#baseline) and a linear model. Then it prints the
[mean absolute error](glossary.md#mean-absolute-error) of each one on the test rows,
with a [confidence interval](glossary.md#confidence-interval).
