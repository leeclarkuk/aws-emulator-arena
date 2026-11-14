const report = JSON.parse(document.getElementById("arena-report").textContent);
const history = JSON.parse(document.getElementById("arena-history").textContent);

const app = document.getElementById("app");
const summary = report.summary;
const emulator = report.emulator;

const scoreClass = summary.fidelity_pct == null ? "mid" : summary.fidelity_pct >= 80 ? "good" : summary.fidelity_pct >= 50 ? "mid" : "low";

app.append(el("div", { class: "wrap" }, [
  header(),
  hero(),
  genome(),
  el("div", { class: "split" }, [scenarios(), services()]),
  wall(),
  divergences(),
  el("div", { class: "lower" }, [trend(), latency()]),
  footer(),
]));

function header() {
  return el("header", { class: "top" }, [
    el("div", { class: "brand" }, [
      el("div", { class: "mark" }),
      el("div", {}, [
        el("h1", {}, ["AWS Emulator Arena"]),
        el("p", {}, ["Local fidelity board"]),
      ]),
    ]),
    el("div", { class: "pills" }, [
      pill("emulator", emulator.version || "unknown"),
      pill("account", emulator.account || "-"),
      pill("startup", ms(emulator.startup_ms)),
      pill("rss", emulator.rss_mb == null ? "-" : `${emulator.rss_mb} MB`),
      pill("ran", when(report.generated_at)),
    ]),
  ]);
}

function hero() {
  const pct = summary.fidelity_pct == null ? "-" : String(summary.fidelity_pct);
  const scored = summary.pass + summary.not_implemented + summary.divergent;
  return el("section", { class: "hero" }, [
    el("div", { class: "hero-card" }, [
      el("p", { class: "kicker" }, ["Fidelity"]),
      el("div", { class: "scoreline" }, [
        el("p", { class: `score ${scoreClass}` }, [pct]),
        el("small", {}, ["%"]),
      ]),
      el("p", { class: "lede" }, [
        `${summary.pass} of ${scored} steps behaved like AWS`,
        el("span", {}, [
          ` across ${summary.scenarios} workflows. ${summary.not_implemented} came back 501 Not Implemented. ${summary.divergent} answered, and answered wrong.`,
        ]),
      ]),
    ]),
    el("div", { class: "stats" }, [
      stat(summary.pass, "passed", "pass"),
      stat(summary.not_implemented, "501 not implemented", "gap"),
      stat(summary.divergent, "divergent", "div"),
      stat(summary.latency_ms.p50 == null ? "-" : ms(summary.latency_ms.p50), `p50 over ${summary.latency_ms.n} calls`, ""),
    ]),
  ]);
}

function genome() {
  const steps = report.scenarios.flatMap((scenario) =>
    scenario.steps.map((step) => ({ scenario, step }))
  );
  return el("div", { class: "genome-block" }, [
    el("p", { class: "legend" }, [
      el("span", {}, [swatch("pass"), "pass"]),
      el("span", {}, [swatch("gap"), "501"]),
      el("span", {}, [swatch("div"), "divergent"]),
      el("span", {}, [swatch("blocked"), "blocked"]),
    ]),
    el("div", { class: "genome", role: "img", "aria-label": "Every step in this run, in order" },
      steps.map(({ scenario, step }) => {
        const mark = el("b", { class: step.outcome });
        mark.title = `${scenario.title}: ${step.operation} (${label(step.outcome)})`;
        return mark;
      })
    ),
  ]);
}

function scenarios() {
  return el("section", {}, [
    head("Workflows", "Open a row for its steps."),
    ...report.scenarios.map(scenarioCard),
  ]);
}

function scenarioCard(scenario) {
  const total = scenario.pass + scenario.not_implemented + scenario.divergent + scenario.blocked;
  const body = el("div", {}, [
    el("h3", {}, [scenario.title]),
    el("p", { class: "summary" }, [scenario.summary]),
    bar(scenario),
    el("div", { class: "chips" }, scenario.service_names.map((name) => el("span", { class: "chip" }, [name]))),
  ]);
  const summaryEl = el("summary", {}, [
    body,
    el("div", { class: "pct" }, [scenario.fidelity_pct == null ? "-" : `${scenario.fidelity_pct}%`]),
  ]);
  const list = el("ol", { class: "steps" }, scenario.steps.map((step) => {
    const item = el("li", {}, [
      el("span", { class: `outcome ${step.outcome}` }, [label(step.outcome)]),
      el("span", {}, [
        step.title,
        el("div", { class: "op" }, [`${step.service_name} ${step.operation}`]),
      ]),
      el("span", { class: "ms" }, [ms(step.latency_ms)]),
    ]);
    if (step.detail) item.append(el("div", { class: "detail" }, [step.detail]));
    return item;
  }));
  const details = el("details", { class: "scenario" }, [summaryEl, list]);
  details.dataset.steps = String(total);
  return details;
}

function services() {
  return el("section", {}, [
    head("Services", "Share of steps that passed."),
    el("div", { class: "services-panel" }, report.services.map((row) => el("div", { class: "service" }, [
      el("div", { class: "name" }, [row.name]),
      bar(row),
      el("div", { class: "pct" }, [row.fidelity_pct == null ? "-" : `${row.fidelity_pct}%`]),
    ]))),
  ]);
}

function wall() {
  const cards = report.wall_of_501;
  return el("section", {}, [
    head("Wall of 501s", cards.length ? "Operations the emulator still refuses." : "Nothing returned 501."),
    cards.length
      ? el("div", { class: "wall" }, cards.map((gap) => el("article", { class: "ticket" }, [
          el("p", { class: "code" }, ["501"]),
          el("p", { class: "opname" }, [`${gap.service_name} ${gap.operation}`]),
          el("p", { class: "where" }, [gap.scenario_title]),
          el("p", { class: "msg" }, [gap.detail || gap.title]),
        ])))
      : el("p", { class: "empty" }, ["This run did not hit a Not Implemented response."]),
  ]);
}

function divergences() {
  const rows = report.divergences;
  return el("section", {}, [
    head("Divergences", "The call returned, and it was not what the workflow needed."),
    rows.length
      ? el("div", { class: "divs" }, rows.map((row) => el("article", { class: "note" }, [
          el("span", { class: "badge" }, ["divergent"]),
          el("h3", {}, [row.title]),
          el("p", { class: "where" }, [`${row.scenario_title}: ${row.service_name} ${row.operation}`]),
          el("p", { class: "msg" }, [row.detail || "Behaviour did not match the scenario."]),
        ])))
      : el("p", { class: "empty" }, ["No divergent calls in this run."]),
  ]);
}

function trend() {
  const runs = history.runs || [];
  return el("section", {}, [
    head("Over time", "One point per arena run. The hourly job appends the next emulator release."),
    el("div", { class: "panel" }, [
      runs.length ? chart(runs) : el("p", { class: "empty" }, ["No history yet."]),
    ]),
  ]);
}

function chart(runs) {
  const width = 640;
  const height = 180;
  const pad = { l: 28, r: 12, t: 16, b: 28 };
  const innerW = width - pad.l - pad.r;
  const innerH = height - pad.t - pad.b;
  const xs = runs.map((_, i) => (runs.length === 1 ? pad.l + innerW / 2 : pad.l + (innerW * i) / (runs.length - 1)));
  const ys = runs.map((run) => pad.t + innerH * (1 - (run.fidelity_pct || 0) / 100));
  const d = xs.map((x, i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const svg = svgEl("svg", { class: "trend", viewBox: `0 0 ${width} ${height}`, role: "img", "aria-label": "Fidelity over emulator runs" });
  for (let i = 0; i <= 4; i++) {
    const y = pad.t + (innerH * i) / 4;
    svg.append(svgEl("line", { class: "grid", x1: pad.l, y1: y, x2: width - pad.r, y2: y }));
  }
  svg.append(svgEl("line", { class: "axis", x1: pad.l, y1: pad.t + innerH, x2: width - pad.r, y2: pad.t + innerH }));
  if (runs.length > 1) svg.append(svgEl("path", { class: "line", d }));
  xs.forEach((x, i) => {
    const dot = svgEl("circle", { class: "dot", cx: x, cy: ys[i], r: 3 });
    const title = svgEl("title");
    title.textContent = `${runs[i].emulator_version || "run"}: ${runs[i].fidelity_pct}%`;
    dot.append(title);
    svg.append(dot);
  });
  const first = runs[0];
  const last = runs[runs.length - 1];
  svg.append(text(pad.l, height - 8, first.emulator_version || ""));
  if (runs.length > 1) {
    const end = text(width - pad.r, height - 8, last.emulator_version || "");
    end.setAttribute("text-anchor", "end");
    svg.append(end);
  }
  return svg;
}

function latency() {
  const rows = report.services.filter((row) => row.latency_ms && row.latency_ms.n);
  const table = el("table", { class: "latency" }, [
    el("thead", {}, [el("tr", {}, ["Service", "p50", "p95", "max", "calls"].map((label) => el("th", {}, [label])))]),
    el("tbody", {}, rows.map((row) => el("tr", {}, [
      el("td", {}, [row.name]),
      el("td", {}, [ms(row.latency_ms.p50)]),
      el("td", {}, [ms(row.latency_ms.p95)]),
      el("td", {}, [ms(row.latency_ms.max)]),
      el("td", {}, [String(row.latency_ms.n)]),
    ]))),
  ]);
  return el("section", {}, [
    head("Latency", "Wire time per SDK call, measured inside the arena."),
    el("div", { class: "panel" }, [table]),
  ]);
}

function footer() {
  return el("footer", { class: "colophon" }, [
    el("div", {}, ["No AWS account. No real credentials. The emulator on 127.0.0.1 is the only thing under test."]),
    el("nav", {}, [
      el("a", { href: "https://docs.aws.amazon.com/emulator/" }, ["Emulator docs"]),
      el("a", { href: "https://github.com/aws/aws-emulator" }, ["Emulator source"]),
      el("a", { href: "https://github.com/leeclarkuk/aws-emulator-arena" }, ["Arena source"]),
    ]),
  ]);
}

function head(title, note) {
  return el("div", { class: "section-head" }, [el("h2", {}, [title]), el("p", {}, [note])]);
}

function stat(value, labelText, tone) {
  return el("div", { class: "stat" }, [
    el("div", { class: `n ${tone}` }, [String(value)]),
    el("div", { class: "l" }, [labelText]),
  ]);
}

function pill(name, value) {
  return el("span", { class: "pill" }, [name, " ", el("strong", {}, [String(value)])]);
}

function bar(row) {
  const parts = ["pass", "not_implemented", "divergent", "blocked"];
  const total = parts.reduce((sum, key) => sum + (row[key] || 0), 0) || 1;
  return el("div", { class: "bar", "aria-hidden": "true" }, parts.map((key) => {
    const node = el("i", { class: key });
    node.style.width = `${((row[key] || 0) / total) * 100}%`;
    return node;
  }));
}

function swatch(name) {
  return el("i", { class: name });
}

function label(outcome) {
  if (outcome === "not_implemented") return "501";
  if (outcome === "divergent") return "divergent";
  if (outcome === "blocked") return "blocked";
  return "pass";
}

function ms(value) {
  if (value == null || value === "") return "-";
  const n = Number(value);
  if (Number.isNaN(n)) return "-";
  return n >= 100 ? `${Math.round(n)} ms` : `${n.toFixed(n >= 10 ? 1 : 2)} ms`;
}

function when(iso) {
  if (!iso) return "-";
  return iso.replace("T", " ").replace("Z", " UTC");
}

function el(tag, attrs, kids) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value != null) node.setAttribute(key, value);
  }
  for (const kid of kids || []) node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  return node;
}

function svgEl(tag, attrs) {
  const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [key, value] of Object.entries(attrs || {})) node.setAttribute(key, value);
  return node;
}

function text(x, y, value) {
  const node = svgEl("text", { x, y });
  node.textContent = value;
  return node;
}
