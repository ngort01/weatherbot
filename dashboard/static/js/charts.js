/**
 * Chart.js helpers. Specs come from <script class="chart-spec"> tags
 * embedded in HTMX partials.
 *
 * @typedef {{ labels: string[], values: number[], label?: string, horizontal?: boolean }} BarOrLineSpec
 * @typedef {{ labels: string[], series: {label: string, data: (number|null)[], color: string}[], actual?: number|null }} MultiLineSpec
 */

const ChartKit = (() => {
  /** @type {Record<string, import('chart.js').Chart>} */
  const registry = {};

  const gridColor = "rgba(36, 48, 73, 0.9)";
  const tickColor = "#64748b";
  const fontFamily = "'JetBrains Mono', ui-monospace, monospace";

  /**
   * @param {string} id
   * @returns {CanvasRenderingContext2D | null}
   */
  function ctx(id) {
    const el = document.getElementById(id);
    if (!el || !(el instanceof HTMLCanvasElement)) return null;
    return el.getContext("2d");
  }

  /** @param {string} id */
  function destroy(id) {
    if (registry[id]) {
      registry[id].destroy();
      delete registry[id];
    }
  }

  /**
   * @param {string} id
   * @param {import('chart.js').ChartConfiguration} config
   */
  function make(id, config) {
    destroy(id);
    const c = ctx(id);
    if (!c || typeof Chart === "undefined") return null;
    registry[id] = new Chart(c, config);
    return registry[id];
  }

  const baseScales = {
    x: {
      ticks: { color: tickColor, font: { family: fontFamily, size: 10 }, maxRotation: 0 },
      grid: { color: gridColor },
    },
    y: {
      ticks: { color: tickColor, font: { family: fontFamily, size: 10 } },
      grid: { color: gridColor },
    },
  };

  /**
   * @param {string} id
   * @param {BarOrLineSpec} opts
   */
  function lineCum(id, opts) {
    const vals = opts.values || [];
    const last = vals.filter((v) => v != null).at(-1) ?? 0;
    const color = last >= 0 ? "#34d399" : "#fb7185";
    return make(id, {
      type: "line",
      data: {
        labels: opts.labels,
        datasets: [{
          label: opts.label || "value",
          data: vals,
          borderColor: color,
          backgroundColor: color + "22",
          fill: true,
          tension: 0.2,
          pointRadius: vals.length > 40 ? 0 : 2,
          borderWidth: 2,
          spanGaps: true,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (c) => {
                const y = c.parsed.y;
                if (y == null) return "";
                return opts.label === "top price"
                  ? ` ${Number(y).toFixed(3)}`
                  : ` $${Number(y).toFixed(2)}`;
              },
            },
          },
        },
        scales: baseScales,
      },
    });
  }

  /**
   * @param {string} id
   * @param {BarOrLineSpec} opts
   */
  function barSigned(id, opts) {
    const colors = (opts.values || []).map((v) => (v >= 0 ? "#34d399" : "#fb7185"));
    const horizontal = !!opts.horizontal;
    const labels = opts.labels || [];
    const n = labels.length;

    // Horizontal city charts: grow parent so every row has room; widen y-axis for names.
    if (horizontal) {
      const canvas = document.getElementById(id);
      if (canvas && canvas.parentElement) {
        const rowPx = 26;
        const padPx = 48;
        canvas.parentElement.style.height = `${Math.max(280, n * rowPx + padPx)}px`;
      }
    }

    /** Longest label width estimate (px) for category axis on the left. */
    const maxLabelChars = labels.reduce((m, s) => Math.max(m, String(s || "").length), 0);
    const yLabelWidth = horizontal
      ? Math.min(160, Math.max(88, Math.ceil(maxLabelChars * 7.2) + 12))
      : undefined;

    return make(id, {
      type: "bar",
      data: {
        labels,
        datasets: [{
          label: opts.label || "value",
          data: opts.values,
          backgroundColor: colors,
          borderRadius: 4,
          categoryPercentage: horizontal ? 0.85 : 0.8,
          barPercentage: horizontal ? 0.9 : 0.9,
        }],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: horizontal ? "y" : "x",
        layout: horizontal
          ? { padding: { left: 4, right: 8, top: 4, bottom: 4 } }
          : { padding: 0 },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (c) => {
                const v = horizontal ? c.parsed.x : c.parsed.y;
                const prefix = opts.label === "MAE" ? " " : " $";
                return `${prefix}${Number(v).toFixed(opts.label === "MAE" ? 3 : 2)}`;
              },
            },
          },
        },
        scales: {
          x: {
            ...baseScales.x,
            ticks: { ...baseScales.x.ticks },
            grid: { ...baseScales.x.grid },
          },
          y: {
            ...baseScales.y,
            ticks: {
              ...baseScales.y.ticks,
              // Don't drop city names when the chart is dense
              autoSkip: !horizontal,
              autoSkipPadding: 2,
              font: { family: fontFamily, size: horizontal ? 11 : 10 },
            },
            grid: horizontal ? { display: false } : { ...baseScales.y.grid },
            afterFit: horizontal
              ? (scale) => {
                  scale.width = Math.max(scale.width, yLabelWidth || 100);
                }
              : undefined,
          },
        },
      },
    });
  }

  /**
   * @param {string} id
   * @param {MultiLineSpec} opts
   */
  function multiLine(id, opts) {
    /** @type {import('chart.js').ChartDataset[]} */
    const datasets = (opts.series || []).map((s) => ({
      label: s.label,
      data: s.data,
      borderColor: s.color,
      backgroundColor: "transparent",
      tension: 0.15,
      pointRadius: (s.data || []).length > 50 ? 0 : 1.5,
      borderWidth: s.label === "best" ? 2.5 : 1.5,
      spanGaps: true,
    }));

    if (opts.actual != null && Number.isFinite(opts.actual)) {
      datasets.push({
        label: "actual",
        data: (opts.labels || []).map(() => opts.actual),
        borderColor: "#fbbf24",
        borderDash: [6, 4],
        pointRadius: 0,
        borderWidth: 1.5,
      });
    }

    return make(id, {
      type: "line",
      data: { labels: opts.labels, datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        plugins: {
          legend: {
            labels: { color: tickColor, font: { family: fontFamily, size: 10 }, boxWidth: 12 },
          },
        },
        scales: baseScales,
      },
    });
  }

  /**
   * Find .chart-spec scripts under root (or document) and paint canvases.
   * @param {ParentNode} [root]
   */
  function initFromDom(root) {
    const scope = root || document;
    scope.querySelectorAll("script.chart-spec").forEach((node) => {
      if (!(node instanceof HTMLScriptElement)) return;
      const canvasId = node.dataset.canvas;
      const type = node.dataset.type;
      if (!canvasId || !type) return;
      let payload;
      try {
        payload = JSON.parse(node.textContent || "{}");
      } catch {
        return;
      }
      if (type === "line-cum") lineCum(canvasId, payload);
      else if (type === "bar-signed") barSigned(canvasId, payload);
      else if (type === "multi-line") multiLine(canvasId, payload);
    });
  }

  return { lineCum, barSigned, multiLine, initFromDom, destroy };
})();
