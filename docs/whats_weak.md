# What's weak

The full list of limits. The README shows the top few. Rank them by how much each one
could change the main result, with the largest first. Say what was done about each
one, even if the answer is "nothing yet".

| Rank | Weakness | How much it could change the result | What was done |
|---|---|---|---|
| 1 | TODO | TODO | TODO |
| TODO | The web page's scenario range check (`site/app.js`) only looks at each driver's level, not the `x_u`/`x_m` term the Python engine also checks (`scenario.driver_ranges`, ADR 0004) | Could let the page's "beyond history" warning or hard stop fire at a different point than the Python engine would, in either direction | The page clamps its sliders and warns using the level range only, exported in `site/data/scenario.json`; it never computes or checks the term range |
