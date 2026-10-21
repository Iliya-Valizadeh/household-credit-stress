# Tutorial

This page walks you through one full run of household-credit-stress, from a fresh clone to
the demo output. You need `uv`, `make`, and the Python version named in
`pyproject.toml`. `uv` can install that Python for you.

## Step 1: get the code

The repo is not on GitHub yet, so the address below does not work until it is. Until
then, start from a local copy.

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

This takes a few minutes. `make demo` runs the real [backtest](glossary.md#backtest) on the data already
committed under `data/processed/`, with no downloads and no keys. It prints the ADR
0003 `arx` model's gap against the AR(1) [baseline](glossary.md#baseline), in
[basis points](glossary.md#basis-point), for one month ahead and three months ahead,
each with a [confidence interval](glossary.md#confidence-interval) and a plain-word
verdict such as "no clear difference". The numbers it prints match
[CLAIMS.md](../CLAIMS.md).
