# How to run the checks before you push

Run the same checks that CI runs, on your own machine.

```bash
make lint
make test
make check-docs
```

`make check-docs` runs the tools in `tools/`. Each tool prints the file and line of
every problem it finds. Fix the text, then run the command again.

To run the checks on every commit, install the pre-commit hooks once:

```bash
uv run pre-commit install
```
