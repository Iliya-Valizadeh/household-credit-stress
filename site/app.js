/* Household credit stress: static page, no framework.
 *
 * Reads the JSON files `site_data.py` exports (see its module docstring) and runs the
 * ADR 0004 linear decomposition itself:
 *
 *   path = baseline_path + sensitivity_unemployment @ (u_path - last_unemployment)
 *                         + sensitivity_rate @ (m_path - last_rate)
 *
 * No model code is reimplemented here beyond that sum and the piecewise-linear path a
 * user's two slider values describe (ADR 0004, "How a path becomes arrears"); both
 * come straight from the ADR text. The honest-range check below only checks each
 * driver's LEVEL range, not the x_u/x_m TERM range the Python engine also checks
 * (docs/whats_weak.md records why).
 */

(function () {
  "use strict";

  const HORIZON_MONTHS = 24;
  const SEQUENTIAL_RAMP = [
    "#cde2fb", "#b7d3f6", "#9ec5f4", "#86b6ef", "#6da7ec", "#5598e7",
    "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b",
  ];
  // A fixed color domain (not scenario-dependent, and not refit as new data arrives)
  // so a tile's color always means the same arrears rate, chosen comfortably above
  // every region's historical arrears rate in the committed panel.
  const COLOR_DOMAIN = [0, 110];

  const state = {
    scenario: null,
    metrics: null,
    presets: null,
    ledger: null,
    status: null,
    deltas: {
      unemployment_rate: { 12: 0, 24: 0 },
      mortgage_rate_5y: { 12: 0, 24: 0 },
    },
    horizon: 12,
    ledgerRegion: "CA",
    mode: "sliders", // "sliders" | "preset"
    activePresetIndex: null,
  };

  async function fetchJson(name) {
    try {
      const response = await fetch("data/" + name);
      if (!response.ok) return null;
      return await response.json();
    } catch (err) {
      return null;
    }
  }

  function hexToRgb(hex) {
    const n = parseInt(hex.slice(1), 16);
    return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  }

  function colorScale(value, domain) {
    const [lo, hi] = domain;
    let t = (value - lo) / (hi - lo);
    t = Math.max(0, Math.min(1, t));
    const n = SEQUENTIAL_RAMP.length;
    const pos = t * (n - 1);
    const i0 = Math.floor(pos);
    const i1 = Math.min(n - 1, i0 + 1);
    const frac = pos - i0;
    const a = hexToRgb(SEQUENTIAL_RAMP[i0]);
    const b = hexToRgb(SEQUENTIAL_RAMP[i1]);
    const rgb = a.map((channel, idx) => Math.round(channel + (b[idx] - channel) * frac));
    return { hex: `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})`, luminance: relativeLuminance(rgb) };
  }

  function relativeLuminance([r, g, b]) {
    // sRGB relative luminance, for picking a legible label color on a fill.
    const srgb = [r, g, b].map((c) => c / 255);
    const lin = srgb.map((c) => (c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4)));
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2];
  }

  // ADR 0004, "How a path becomes arrears": straight lines joining (0, last_value),
  // (12, last_value + change12m) and (24, last_value + change24m), for months 1..n.
  function pathFromChanges(lastValue, change12, change24, n) {
    const out = new Array(n);
    for (let k = 1; k <= n; k += 1) {
      if (k <= 12) {
        out[k - 1] = lastValue + (change12 * k) / 12;
      } else {
        out[k - 1] = lastValue + change12 + (change24 - change12) * ((k - 12) / 12);
      }
    }
    return out;
  }

  function matVecAdd(baseline, matrix, delta) {
    const out = new Array(baseline.length);
    for (let i = 0; i < baseline.length; i += 1) {
      let sum = baseline[i];
      const row = matrix[i];
      for (let k = 0; k < delta.length; k += 1) {
        sum += row[k] * delta[k];
      }
      out[i] = sum;
    }
    return out;
  }

  function regionPath(region, deltas) {
    const payload = state.scenario.by_region[region];
    const uPath = pathFromChanges(
      payload.last_unemployment,
      deltas.unemployment_rate[12],
      deltas.unemployment_rate[24],
      HORIZON_MONTHS
    );
    const mPath = pathFromChanges(
      payload.last_rate,
      deltas.mortgage_rate_5y[12],
      deltas.mortgage_rate_5y[24],
      HORIZON_MONTHS
    );
    const uDelta = uPath.map((v) => v - payload.last_unemployment);
    const mDelta = mPath.map((v) => v - payload.last_rate);
    const withUnemployment = matVecAdd(payload.baseline_path, payload.sensitivity_unemployment, uDelta);
    const withRate = matVecAdd(new Array(HORIZON_MONTHS).fill(0), payload.sensitivity_rate, mDelta);
    return withUnemployment.map((v, i) => Math.max(0, v + withRate[i]));
  }

  function caPath(regionPaths) {
    const ca = state.scenario.ca;
    const weights = ca.mortgage_weights;
    const total = Object.values(weights).reduce((a, b) => a + b, 0);
    const change = new Array(HORIZON_MONTHS).fill(0);
    state.scenario.regions.forEach((region) => {
      const level = state.scenario.by_region[region].level_at_cutoff;
      const share = weights[region] / total;
      regionPaths[region].forEach((v, i) => {
        change[i] += share * (v - level);
      });
    });
    return change.map((c) => Math.max(0, ca.level_at_cutoff + c));
  }

  // A preset replays each region's own historical change exactly (ADR 0004, "Presets
  // from history"), not the single national delta the two sliders describe, so it is
  // run through the same sensitivities directly rather than through `pathFromChanges`.
  // `presets.json`'s arrays already hold the change from the last known value and are
  // one or two months short of 24 (the ADR: "the last two months of a driver path
  // never reach the arrears horizon"); padding with zero change is exact, not an
  // approximation, because sensitivity columns past that point never affect any of
  // the 24 target months (verified for every committed preset in `tests/test_scenario.py`).
  function padToHorizon(values) {
    const out = values.slice(0, HORIZON_MONTHS);
    while (out.length < HORIZON_MONTHS) out.push(0);
    return out;
  }

  function presetRegionPath(region, preset) {
    const payload = state.scenario.by_region[region];
    const uDelta = padToHorizon(preset.unemployment_change[region]);
    const mDelta = preset.rate_change ? padToHorizon(preset.rate_change) : new Array(HORIZON_MONTHS).fill(0);
    const withUnemployment = matVecAdd(payload.baseline_path, payload.sensitivity_unemployment, uDelta);
    const withRate = matVecAdd(new Array(HORIZON_MONTHS).fill(0), payload.sensitivity_rate, mDelta);
    return withUnemployment.map((v, i) => Math.max(0, v + withRate[i]));
  }

  function computeAllPaths() {
    const regionPaths = {};
    if (state.mode === "preset") {
      const preset = state.presets.presets[state.activePresetIndex];
      state.scenario.regions.forEach((region) => {
        regionPaths[region] = presetRegionPath(region, preset);
      });
    } else {
      state.scenario.regions.forEach((region) => {
        regionPaths[region] = regionPath(region, state.deltas);
      });
    }
    regionPaths.CA = caPath(regionPaths);
    return regionPaths;
  }

  // --- the honest range of inputs: level check only (docs/whats_weak.md) ----------

  function lastValueRange(driver) {
    const regions = state.scenario.regions;
    if (driver === "mortgage_rate_5y") {
      const v = state.scenario.by_region[regions[0]].last_rate;
      return { min: v, max: v };
    }
    const values = regions.map((r) => state.scenario.by_region[r].last_unemployment);
    return { min: Math.min(...values), max: Math.max(...values) };
  }

  // Both the 12- and 24-month slider for a driver check against the same honest
  // range: each just sets the driver's level at a different point in time.
  function sliderBounds(driver) {
    const ranges = state.scenario.ranges[driver];
    const { min, max } = lastValueRange(driver);
    return {
      allowedMin: ranges.level_widened_low - min,
      allowedMax: ranges.level_widened_high - max,
      warnMin: ranges.level_low - min,
      warnMax: ranges.level_high - max,
    };
  }

  // --- rendering ---------------------------------------------------------------

  function renderStaleBadge() {
    const badge = document.getElementById("stale-badge");
    if (!state.status) return;
    const staleSources = Object.entries(state.status)
      .filter(([, info]) => info.stale || !info.ok)
      .map(([name]) => name);
    if (staleSources.length === 0) {
      badge.hidden = true;
      return;
    }
    badge.hidden = false;
    badge.textContent = `Data may be out of date: ${staleSources.join(", ")}`;
  }

  function renderLabelBanner() {
    const banner = document.getElementById("label-banner");
    if (!state.metrics) {
      banner.innerHTML = "";
      return;
    }
    const scenarioInfo = state.scenario;
    let droppedNote = "";
    if (scenarioInfo.dropped_drivers.length > 0) {
      const names = scenarioInfo.dropped_drivers
        .map((d) => (d === "unemployment_rate" ? "unemployment" : "the mortgage rate"))
        .join(" and ");
      droppedNote = `<p>At the latest data, ${names} did not show the expected effect on arrears here, so its slider has no effect on the path.</p>`;
    }
    banner.innerHTML = `
      <p><strong>${state.metrics.label}.</strong>
      <span class="banner-reason">${state.metrics.label_reason}</span></p>
      ${droppedNote}
    `;
  }

  function renderDriverControls() {
    document.querySelectorAll(".driver-group").forEach((group) => {
      const driver = group.dataset.driver;
      const unit = driver === "unemployment_rate" ? "points" : "%";
      const regions = state.scenario.regions;
      const lastDisplay =
        driver === "mortgage_rate_5y"
          ? state.scenario.by_region[regions[0]].last_rate
          : null;
      const lastValueEl = group.querySelector(".last-value");
      if (driver === "mortgage_rate_5y") {
        lastValueEl.textContent = lastDisplay.toFixed(2);
      } else {
        const values = regions.map((r) => state.scenario.by_region[r].last_unemployment);
        const lo = Math.min(...values).toFixed(1);
        const hi = Math.max(...values).toFixed(1);
        lastValueEl.textContent = `${lo} to ${hi}`;
      }

      const bounds = sliderBounds(driver);
      group.querySelectorAll(".slider").forEach((slider) => {
        const reach = Number(slider.dataset.reach);
        slider.min = bounds.allowedMin.toFixed(2);
        slider.max = bounds.allowedMax.toFixed(2);
        slider.value = state.deltas[driver][reach];
        updateSliderOutput(slider, unit);
      });
    });
  }

  function updateSliderOutput(slider, unit) {
    const output = slider.parentElement.querySelector(".slider-output");
    const value = Number(slider.value);
    const sign = value > 0 ? "+" : "";
    output.textContent = `${sign}${value.toFixed(2)} ${unit}`;
  }

  function checkRangeWarning(driver, group) {
    const note = group.querySelector(".driver-note");
    if (state.mode === "preset") {
      // A preset replays history exactly; the two-slider range check does not apply
      // to it (ADR 0004 already notes the 1990s preset may leave the fitted range).
      note.hidden = true;
      note.classList.remove("warn");
      return;
    }
    const messages = [];
    const bounds = sliderBounds(driver);
    ["12", "24"].forEach((reach) => {
      const value = state.deltas[driver][reach];
      if (value < bounds.warnMin || value > bounds.warnMax) {
        messages.push(
          `The ${reach}-month change goes past anything this model has seen. The ` +
            "scenario still runs, but it is extending straight lines past its history."
        );
      }
    });
    if (messages.length > 0) {
      note.hidden = false;
      note.classList.add("warn");
      note.textContent = messages[0];
    } else {
      note.hidden = true;
      note.classList.remove("warn");
    }
  }

  function renderTiles(regionPaths) {
    const grid = document.getElementById("tile-grid");
    grid.innerHTML = "";
    const monthLabel = state.scenario.target_months[state.horizon - 1];
    document.getElementById("map-caption").textContent =
      `Scenario arrears rate at ${monthLabel}, ${state.horizon} month(s) past the last published month ` +
      `(${state.scenario.cutoff}). Shading is the same color scale at every setting (0 to 110bp).`;

    const order = [...state.scenario.regions, "CA"];
    order.forEach((region) => {
      const value = regionPaths[region][state.horizon - 1];
      const baseline =
        region === "CA" ? state.scenario.ca.level_at_cutoff : state.scenario.by_region[region].level_at_cutoff;
      const delta = value - baseline;
      const { hex, luminance } = colorScale(value, COLOR_DOMAIN);
      const tile = document.createElement("div");
      tile.className = "tile" + (region === "CA" ? " tile-ca" : "");
      tile.style.background = hex;
      tile.style.color = luminance > 0.5 ? "#0b0b0b" : "#ffffff";
      const name = region === "CA" ? "Canada" : state.scenario.region_names[region] || region;
      const sign = delta >= 0 ? "+" : "";
      tile.innerHTML = `
        <span class="tile-region">${name}</span>
        <span class="tile-value">${value.toFixed(1)} bp</span>
        <span class="tile-delta">${sign}${delta.toFixed(1)} bp vs ${baseline.toFixed(1)}</span>
      `;
      grid.appendChild(tile);
    });

    document.getElementById("tile-legend").textContent =
      "Arrears rate: mortgage accounts three or more months overdue, per 10,000 mortgages. " +
      "Darker means higher.";
  }

  function recompute() {
    const regionPaths = computeAllPaths();
    document.getElementById("horizon-output").textContent = `+${state.horizon} month(s)`;
    renderTiles(regionPaths);
    document.querySelectorAll(".driver-group").forEach((group) => {
      checkRangeWarning(group.dataset.driver, group);
    });
  }

  function applyPreset(index) {
    state.mode = "preset";
    state.activePresetIndex = index;
    renderScenarioStatus();
    recompute();
  }

  function resetDeltas() {
    state.mode = "sliders";
    state.activePresetIndex = null;
    state.deltas.unemployment_rate[12] = 0;
    state.deltas.unemployment_rate[24] = 0;
    state.deltas.mortgage_rate_5y[12] = 0;
    state.deltas.mortgage_rate_5y[24] = 0;
    renderDriverControls();
    renderScenarioStatus();
    recompute();
  }

  function renderScenarioStatus() {
    const el = document.getElementById("scenario-status");
    if (!el) return;
    if (state.mode === "preset") {
      const preset = state.presets.presets[state.activePresetIndex];
      let note = "";
      if (state.activePresetIndex === 0) {
        note =
          " Its unemployment rise may go past anything the model was fitted on " +
          "(ADR 0004); regions past that range are shown anyway.";
      }
      el.textContent = `Showing: the exact historical path starting ${preset.start_month}.${note}`;
    } else {
      el.textContent = "Showing: a custom scenario from the sliders above.";
    }
  }

  // --- forecast record (ledger) chart -------------------------------------------

  function renderLedgerControls() {
    const select = document.getElementById("ledger-region");
    select.innerHTML = "";
    state.ledger.regions.forEach((region) => {
      const option = document.createElement("option");
      option.value = region;
      option.textContent = region === "CA" ? "Canada" : region;
      select.appendChild(option);
    });
    select.value = state.ledgerRegion;
    select.addEventListener("change", () => {
      state.ledgerRegion = select.value;
      renderLedgerChart();
    });
  }

  function renderLedgerChart() {
    const rows = state.ledger.rows.filter((r) => r.region === state.ledgerRegion);
    const svg = document.getElementById("ledger-chart");
    const tbody = document.querySelector("#ledger-table tbody");
    const empty = document.getElementById("ledger-empty");
    tbody.innerHTML = "";
    svg.innerHTML = "";

    rows
      .slice()
      .sort((a, b) => (a.target_month < b.target_month ? -1 : 1))
      .forEach((row) => {
        const tr = document.createElement("tr");
        tr.innerHTML = `
          <td>${row.target_month}</td>
          <td>${row.horizon} month(s)</td>
          <td>${row.forecast_bp.toFixed(1)}</td>
          <td>${row.lo80_bp.toFixed(1)} to ${row.hi80_bp.toFixed(1)}</td>
          <td>${row.actual_bp === null ? "not yet published" : row.actual_bp.toFixed(1)}</td>
        `;
        tbody.appendChild(tr);
      });

    if (rows.length === 0) {
      empty.hidden = false;
      return;
    }
    empty.hidden = true;
    drawLedgerSvg(svg, rows);
  }

  function drawLedgerSvg(svg, rows) {
    const width = 640;
    const height = 300;
    const margin = { top: 16, right: 16, bottom: 36, left: 44 };
    const plotWidth = width - margin.left - margin.right;
    const plotHeight = height - margin.top - margin.bottom;

    const months = [...new Set(rows.map((r) => r.target_month))].sort();
    const xFor = (month) =>
      margin.left + (months.length <= 1 ? plotWidth / 2 : (months.indexOf(month) / (months.length - 1)) * plotWidth);

    const values = rows.flatMap((r) => [r.forecast_bp, r.lo80_bp, r.hi80_bp, r.actual_bp]).filter((v) => v !== null);
    const yMin = Math.min(...values) - 2;
    const yMax = Math.max(...values) + 2;
    const yFor = (v) => margin.top + plotHeight - ((v - yMin) / (yMax - yMin)) * plotHeight;

    const ns = "http://www.w3.org/2000/svg";
    const make = (tag, attrs) => {
      const el = document.createElementNS(ns, tag);
      Object.entries(attrs).forEach(([k, v]) => {
        // fill/stroke go through the style property so a CSS var() resolves
        // (var() is not reliably read from a plain presentation attribute).
        if (k === "fill" || k === "stroke") {
          el.style[k] = v;
        } else {
          el.setAttribute(k, v);
        }
      });
      return el;
    };

    // gridlines (y)
    const ticks = 4;
    for (let i = 0; i <= ticks; i += 1) {
      const v = yMin + ((yMax - yMin) * i) / ticks;
      const y = yFor(v);
      svg.appendChild(
        make("line", { x1: margin.left, x2: width - margin.right, y1: y, y2: y, class: "chart-gridline" })
      );
      const label = make("text", { x: 4, y: y + 4, class: "chart-axis-label" });
      label.textContent = v.toFixed(0);
      svg.appendChild(label);
    }

    // baseline
    svg.appendChild(
      make("line", {
        x1: margin.left,
        x2: width - margin.right,
        y1: margin.top + plotHeight,
        y2: margin.top + plotHeight,
        class: "chart-baseline",
      })
    );

    const byHorizon = {};
    rows.forEach((row) => {
      byHorizon[row.horizon] = byHorizon[row.horizon] || [];
      byHorizon[row.horizon].push(row);
    });

    const seriesColor = { 1: "var(--series-1)", 3: "var(--series-2)" };
    Object.entries(byHorizon).forEach(([horizon, horizonRows]) => {
      const sorted = horizonRows.slice().sort((a, b) => (a.target_month < b.target_month ? -1 : 1));
      const color = seriesColor[horizon] || "var(--series-1)";

      if (sorted.length > 1) {
        const bandPoints = sorted
          .map((r) => `${xFor(r.target_month)},${yFor(r.hi80_bp)}`)
          .concat(sorted.slice().reverse().map((r) => `${xFor(r.target_month)},${yFor(r.lo80_bp)}`))
          .join(" ");
        svg.appendChild(make("polygon", { points: bandPoints, fill: color, opacity: "0.1", stroke: "none" }));

        const linePoints = sorted.map((r) => `${xFor(r.target_month)},${yFor(r.forecast_bp)}`).join(" ");
        svg.appendChild(
          make("polyline", { points: linePoints, fill: "none", stroke: color, "stroke-width": "2" })
        );
      }

      sorted.forEach((r) => {
        const x = xFor(r.target_month);
        svg.appendChild(
          make("line", { x1: x, x2: x, y1: yFor(r.lo80_bp), y2: yFor(r.hi80_bp), stroke: color, "stroke-width": "2" })
        );
        svg.appendChild(
          make("circle", { cx: x, cy: yFor(r.forecast_bp), r: "4", fill: color, stroke: "var(--surface-1)", "stroke-width": "2" })
        );
        if (r.actual_bp !== null) {
          svg.appendChild(
            make("circle", {
              cx: x,
              cy: yFor(r.actual_bp),
              r: "4",
              fill: "var(--surface-1)",
              stroke: color,
              "stroke-width": "2",
            })
          );
        }
      });

      const last = sorted[sorted.length - 1];
      const endLabel = make("text", {
        x: xFor(last.target_month) + 6,
        y: yFor(last.forecast_bp) - 6,
        class: "chart-axis-label",
      });
      endLabel.textContent = `${horizon}mo`;
      svg.appendChild(endLabel);
    });

    months.forEach((month) => {
      const label = make("text", {
        x: xFor(month),
        y: height - 10,
        class: "chart-axis-label",
        "text-anchor": "middle",
      });
      label.textContent = month;
      svg.appendChild(label);
    });
  }

  // --- wiring --------------------------------------------------------------------

  function wireControls() {
    document.querySelectorAll(".slider").forEach((slider) => {
      slider.addEventListener("input", () => {
        state.mode = "sliders";
        state.activePresetIndex = null;
        const driver = slider.dataset.driver;
        const reach = slider.dataset.reach;
        state.deltas[driver][reach] = Number(slider.value);
        const unit = driver === "unemployment_rate" ? "points" : "%";
        updateSliderOutput(slider, unit);
        renderScenarioStatus();
        recompute();
      });
    });

    document.getElementById("horizon-slider").addEventListener("input", (event) => {
      state.horizon = Number(event.target.value);
      recompute();
    });

    document.querySelectorAll(".preset-button").forEach((button) => {
      button.addEventListener("click", () => {
        if (button.dataset.preset === "reset") {
          resetDeltas();
        } else {
          applyPreset(Number(button.dataset.preset));
        }
      });
    });
  }

  async function init() {
    const [scenario, metrics, presets, ledger, status] = await Promise.all([
      fetchJson("scenario.json"),
      fetchJson("scenario_metrics.json"),
      fetchJson("scenario_presets.json"),
      fetchJson("ledger.json"),
      fetchJson("status.json"),
    ]);
    state.scenario = scenario;
    state.metrics = metrics;
    state.presets = presets;
    state.ledger = ledger;
    state.status = status;

    if (!scenario) {
      document.getElementById("label-banner").textContent =
        "The scenario data did not load. Run python -m household_credit_stress.site_data and reload.";
      return;
    }

    renderStaleBadge();
    renderLabelBanner();
    renderDriverControls();
    renderScenarioStatus();
    wireControls();
    recompute();

    if (ledger) {
      renderLedgerControls();
      renderLedgerChart();
    }
  }

  init();
})();
