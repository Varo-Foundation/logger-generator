// The chart under each download: the files read back (web.py) and drawn with uPlot.
// "series": high-resolution readings (EMS, Haier); "daily": per-day min/mean/max (Fridge-tag, MetaFridge).
import uPlot from "https://cdn.jsdelivr.net/npm/uplot@1.6.32/dist/uPlot.esm.js";

const INK = "#33383A";
const MUTED = "#5C6366";
const GRID = "#ECEDE7";
const SURFACE = "#FFFFFF";
const SERIES = ["#2E8A57", "#B07F10"];  // validated pair (green, gold); direct labels carry identity too
const BAND = "rgba(46, 138, 87, 0.14)";
const SAFE = "rgba(184, 218, 148, 0.2)";
const LIMIT = "#8DB86A";
const ALARMS = {  // labelled lanes: the name, not the colour, identifies each
  POWR: { color: "#5C6366", label: "Power cut (POWR)" },
  HEAT: { color: "#C0392B", label: "Heat alarm (HEAT)" },
  FRZE: { color: "#2F6DB5", label: "Freeze alarm (FRZE)" },
  DOOR: { color: "#8C6BB1", label: "Door open (DOOR)" },
};
const HIGH = "#C0392B";
const LOW = "#2F6DB5";
const FONT = '12px Inter, system-ui, sans-serif';

function el(tag, props = {}, children = []) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

const unitLabel = (unit) => (unit === "F" ? "°F" : "°C");
const fmt = (v, unit) => (v == null ? "–" : `${v > 0 ? "+" : ""}${v.toFixed(1)} ${unitLabel(unit)}`);
const dateOf = (ts) => new Date(ts * 1000).toISOString().slice(0, 10);
const timeOf = (ts) => new Date(ts * 1000).toISOString().slice(0, 16).replace("T", " ");
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
// Axis dates as "2 Aug" (and "2 Aug 12:00" once ticks are less than a day apart), the year on the first tick.
function timeTicks(u, ticks) {
  const hourly = ticks.length > 1 && ticks[1] - ticks[0] < 86400;
  return ticks.map((t, i) => {
    const d = new Date(t * 1000);
    const day = `${d.getUTCDate()} ${MONTHS[d.getUTCMonth()]}`;
    const time = hourly ? ` ${d.toISOString().slice(11, 16)}` : "";
    return i === 0 ? `${day}${time}\n${d.getUTCFullYear()}` : `${day}${time}`;
  });
}
const minutes = (m) => (m >= 60 ? `${Math.floor(m / 60)} h ${m % 60} min` : `${m} min`);

export function renderChart(root, chart) {
  root.replaceChildren();
  if (!chart) return;
  for (const note of chart.notes || []) root.append(el("p", { className: "chart-note", textContent: note }));
  if (chart.kind === "none" || !chart.x?.length) return;

  const daily = chart.kind === "daily";
  const unit = chart.unit;
  const { low, high } = chart.limits;
  const lanes = daily ? [] : Object.keys(ALARMS).filter((k) => chart.spans.some((s) => s.kind === k));
  const laneTop = lanes.length ? lanes.length * 16 + 8 : 0;  // CSS px reserved above the data

  // Title row and legend: line keys for lines, washes for areas.
  const title = daily ? "Daily temperatures" : chart.series.length > 1 ? "Temperatures" : "Temperature";
  const legend = el("div", { className: "chart-legend" });
  const key = (cls, color, text) => {
    const swatch = el("span", { className: cls });
    swatch.style.setProperty("--c", color);
    legend.append(el("span", { className: "chart-key" }, [swatch, text]));
  };
  if (daily) {
    key("key-line", SERIES[0], "Daily mean");
    key("key-wash", "rgba(46, 138, 87, 0.35)", "Daily min to max");
    if (chart.high.some((h) => h[1])) key("key-dot", HIGH, "High alarm day");
    if (chart.low.some((l) => l[1])) key("key-dot", LOW, "Low alarm day");
  } else if (chart.series.length > 1) {
    chart.series.forEach((s, i) => key("key-line", SERIES[i], s.label));
  }
  key("key-wash", "rgba(141, 184, 106, 0.55)", `Within the alarm limits (${fmt(low, unit)} to ${fmt(high, unit)})`);
  root.append(el("div", { className: "chart-head" }, [el("h4", { textContent: title }), legend]));

  const frame = el("div", { className: "chart-frame" });
  const tip = el("div", { className: "chart-tip", hidden: true });
  root.append(frame, el("p", { className: "hint", textContent: `Drag across the chart to zoom in; double-click to zoom out. Limits: ${chart.limits.source}.` }));

  const data = daily ? [chart.x, chart.min, chart.mean, chart.max] : [chart.x, ...chart.series.map((s) => s.values)];
  const series = daily
    ? [{}, { label: "Min", stroke: "rgba(46, 138, 87, 0.45)", width: 1 },
       { label: "Mean", stroke: SERIES[0], width: 2 },
       { label: "Max", stroke: "rgba(46, 138, 87, 0.45)", width: 1 }]
    : [{}, ...chart.series.map((s, i) => ({ label: s.label, stroke: SERIES[i], width: i ? 1.25 : 2 }))];

  const values = data.slice(1).flat().filter((v) => v != null);
  const lo = Math.min(...values, low);
  const hi = Math.max(...values, high);
  const pad = (hi - lo) * 0.08 || 1;

  const opts = {
    width: frame.clientWidth || 600,
    height: 320,
    tzDate: (ts) => uPlot.tzDate(new Date(ts * 1000), "Etc/UTC"),
    series: series.map((s) => ({ ...s, points: { show: false } })),
    bands: daily ? [{ series: [3, 1], fill: BAND }] : [],
    legend: { show: false },
    cursor: { drag: { x: true, y: false }, points: { show: false }, y: false },
    scales: { y: { range: () => [lo - pad, hi + pad + (laneTop ? (hi - lo + 2 * pad) * laneTop / 260 : 0)] } },
    axes: [
      { stroke: MUTED, font: FONT, grid: { stroke: GRID, width: 1 }, ticks: { show: false }, values: timeTicks, space: 70 },
      { stroke: MUTED, font: FONT, grid: { stroke: GRID, width: 1 }, ticks: { show: false }, size: 64,
        values: (u, ticks) => ticks.map((t) => `${t} ${unitLabel(unit)}`) },
    ],
    hooks: {
      drawClear: [(u) => {
        // The band between the device's alarm limits, with hairlines at each limit.
        const { ctx } = u;
        const { left, width, top, height } = u.bbox;
        const yHigh = u.valToPos(high, "y", true);
        const yLow = u.valToPos(low, "y", true);
        ctx.save();
        ctx.beginPath(); ctx.rect(left, top, width, height); ctx.clip();
        ctx.fillStyle = SAFE;
        ctx.fillRect(left, yHigh, width, yLow - yHigh);
        ctx.strokeStyle = LIMIT; ctx.lineWidth = devicePixelRatio;
        for (const y of [yHigh, yLow]) { ctx.beginPath(); ctx.moveTo(left, y); ctx.lineTo(left + width, y); ctx.stroke(); }
        ctx.restore();
      }],
      draw: [(u) => {
        const { ctx } = u;
        const r = devicePixelRatio;
        const { left, width, top } = u.bbox;
        ctx.save();
        ctx.beginPath(); ctx.rect(left, top, width, u.bbox.height); ctx.clip();
        ctx.font = `${11 * r}px Inter, system-ui, sans-serif`;
        ctx.textBaseline = "middle";
        ctx.textAlign = "left";
        // Alarm lanes along the top: one labelled row per kind present.
        lanes.forEach((kind, i) => {
          const y = top + (4 + i * 16) * r;
          ctx.fillStyle = ALARMS[kind].color;
          for (const s of chart.spans) {
            if (s.kind !== kind) continue;
            const x0 = Math.max(left, u.valToPos(s.start, "x", true));
            const x1 = Math.min(left + width, u.valToPos(s.end, "x", true));
            if (x1 >= left && x0 <= left + width) ctx.fillRect(x0, y, Math.max(x1 - x0, 2 * r), 10 * r);
          }
          ctx.fillStyle = INK;
          const label = kind;
          const w = ctx.measureText(label).width;
          ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
          ctx.fillRect(left + 2 * r, y - 1 * r, w + 8 * r, 12 * r);
          ctx.fillStyle = INK;
          ctx.fillText(label, left + 6 * r, y + 5 * r);
        });
        // Alarm days: a ringed dot on the day's max (high) or min (low).
        if (daily) {
          const dot = (i, value, color) => {
            const x = u.valToPos(chart.x[i], "x", true);
            const y = u.valToPos(value, "y", true);
            ctx.beginPath(); ctx.arc(x, y, 6 * r, 0, 2 * Math.PI); ctx.fillStyle = SURFACE; ctx.fill();
            ctx.beginPath(); ctx.arc(x, y, 4 * r, 0, 2 * Math.PI); ctx.fillStyle = color; ctx.fill();
          };
          chart.high.forEach((h, i) => h[1] && dot(i, chart.max[i], HIGH));
          chart.low.forEach((l, i) => l[1] && dot(i, chart.min[i], LOW));
        }
        // Direct labels at the right end of each line (a second cue besides colour).
        if (!daily && chart.series.length > 1) {
          const [x0, x1] = [u.scales.x.min, u.scales.x.max];
          chart.series.forEach((s, i) => {
            let j = u.valToIdx(x1);
            while (j > 0 && (s.values[j] == null || chart.x[j] > x1)) j--;
            if (chart.x[j] < x0) return;
            const name = s.key === "tamb" ? "Ambient" : "Chamber";
            const x = u.valToPos(chart.x[j], "x", true) - ctx.measureText(name).width - 6 * r;
            const y = u.valToPos(s.values[j], "y", true) - 10 * r;
            ctx.fillStyle = "rgba(255, 255, 255, 0.85)";
            ctx.fillRect(x - 3 * r, y - 7 * r, ctx.measureText(name).width + 6 * r, 14 * r);
            ctx.fillStyle = INK;
            ctx.fillText(name, x, y);
          });
        }
        ctx.restore();
      }],
      setCursor: [(u) => {
        const i = u.cursor.idx;
        if (i == null || u.cursor.left < 0) { tip.hidden = true; return; }
        const t = chart.x[i];
        const rows = [];
        const row = (value, label, color) => {
          const line = el("span", { className: "tip-key" });
          if (color) line.style.setProperty("--c", color);
          rows.push(el("div", { className: "tip-row" }, [line, el("strong", { textContent: value }), el("span", { textContent: label })]));
        };
        if (daily) {
          row(fmt(chart.max[i], unit), "max", "rgba(46, 138, 87, 0.45)");
          row(fmt(chart.mean[i], unit), "mean", SERIES[0]);
          row(fmt(chart.min[i], unit), "min", "rgba(46, 138, 87, 0.45)");
          if (chart.high[i][0]) row(minutes(chart.high[i][0]), chart.high[i][1] ? "above limit · high alarm" : "above limit", HIGH);
          if (chart.low[i][0]) row(minutes(chart.low[i][0]), chart.low[i][1] ? "below limit · low alarm" : "below limit", LOW);
        } else {
          chart.series.forEach((s, k) => row(fmt(s.values[i], unit), s.label, SERIES[k]));
          for (const kind of lanes) {
            if (chart.spans.some((s) => s.kind === kind && s.start < t && t <= s.end)) row("Active", ALARMS[kind].label, ALARMS[kind].color);
          }
        }
        tip.replaceChildren(el("div", { className: "tip-time", textContent: daily ? dateOf(t) : timeOf(t) }), ...rows);
        tip.hidden = false;
        const x = u.cursor.left + u.bbox.left / devicePixelRatio;
        const room = frame.clientWidth - x;
        tip.style.left = `${room > tip.offsetWidth + 24 ? x + 14 : x - tip.offsetWidth - 14}px`;
        tip.style.top = `${u.bbox.top / devicePixelRatio + 8 + laneTop}px`;
      }],
    },
  };

  const plot = new uPlot(opts, data, frame);
  frame.append(tip);
  frame.addEventListener("mouseleave", () => { tip.hidden = true; });
  new ResizeObserver(() => plot.setSize({ width: frame.clientWidth, height: 320 })).observe(frame);

  // The same numbers without hovering: one row per day, newest first.
  const table = el("table", { className: "chart-table" }, [
    el("thead", {}, [el("tr", {}, ["Date", "Min", "Mean", "Max"].map((h) => el("th", { textContent: h, scope: "col" })))]),
    el("tbody", {}, chart.table.map((r) => el("tr", {}, [el("td", { textContent: r[0] }), ...r.slice(1).map((v) => el("td", { textContent: fmt(v, unit) }))]))),
  ]);
  root.append(el("details", { className: "chart-details" }, [
    el("summary", { textContent: daily ? "Show the daily values as a table" : "Show daily min, mean and max as a table" }), table,
  ]));
}
