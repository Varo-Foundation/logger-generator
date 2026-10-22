// The page: builds the form from the generator's own catalogue and turns choices into
// the same command line a user would run.
const worker = new Worker("worker.js", { type: "module" });
const pending = new Map();
let nextId = 0;

function call(message) {
  const id = nextId++;
  worker.postMessage({ id, ...message });
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

worker.onmessage = ({ data }) => {
  const { resolve, reject } = pending.get(data.id);
  pending.delete(data.id);
  data.ok ? resolve(data.result) : reject(new Error(data.error));
};

const $ = (id) => document.getElementById(id);
function el(tag, props = {}, children = []) {
  const node = Object.assign(document.createElement(tag), props);
  node.append(...children);
  return node;
}

let catalogue;
let lastDownload;

const randomSeed = () => 1 + Math.floor(Math.random() * 99999);

function save({ zip, name }) {
  const url = URL.createObjectURL(new Blob([zip], { type: "application/zip" }));
  const link = el("a", { href: url, download: name });
  document.body.append(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 60_000);
}

function command(argv, folder) {
  const quoted = argv.map((a) => (/^[\w.,:-]+$/.test(a) ? a : `'${a}'`)).join(" ");
  return `uvx --from git+https://github.com/Varo-Foundation/logger-generator@v${catalogue.version} logger-generator ${quoted} --out ${folder}`;
}

function setBusy(busy, text) {
  $("status").hidden = !busy;
  $("status").classList.remove("error");
  $("status-text").textContent = text || "";
  for (const button of document.querySelectorAll("button")) button.disabled = busy;
}

async function produce(argv, folder) {
  setBusy(true, "Generating…");
  try {
    const result = await call({ type: "run", argv: [...argv, folder] });
    lastDownload = result;
    save(result);
    $("result-name").textContent = result.name;
    $("result-summary").textContent = result.summary;
    $("result-command").textContent = command(argv, folder);
    $("result").hidden = false;
    return result;
  } catch (error) {
    $("result").hidden = true;
    alertBox(`Couldn't generate that: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

function alertBox(text) {
  setBusy(false);
  $("status").hidden = false;
  $("status").classList.add("error");
  $("status-text").textContent = text;
}

function selectedFormat() {
  const command = new FormData($("form")).get("format");
  return catalogue.formats.find((f) => f.command === command);
}

function renderScenarios() {
  const format = selectedFormat();
  $("scenarios").replaceChildren(...format.scenarios.map((s, i) =>
    el("label", { className: "scenario" }, [
      el("input", { type: "radio", name: "scenario", value: s.name, checked: i === 0 }),
      el("span", {}, [el("strong", { textContent: s.name }), el("span", { textContent: s.description })]),
    ])));
  $("model-field").hidden = format.command !== "fridgetag";
}

function renderForm() {
  $("formats").replaceChildren(...catalogue.formats.map((f, i) =>
    el("label", { className: "choice" }, [
      el("input", { type: "radio", name: "format", value: f.command, checked: i === 0 }),
      el("span", {}, [el("strong", { textContent: f.name }), el("span", { textContent: f.detail })]),
    ])));
  $("model").replaceChildren(...catalogue.fridgetagModels.map((m) =>
    el("option", { value: m, textContent: m, selected: m === "2E" })));
  $("formats").addEventListener("change", renderScenarios);
  renderScenarios();
  $("seed").value = randomSeed();
  $("reroll").addEventListener("click", () => { $("seed").value = randomSeed(); });

  $("form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const format = selectedFormat();
    const scenario = new FormData($("form")).get("scenario");
    const seed = String(Math.min(99999, Math.max(1, parseInt($("seed").value, 10) || randomSeed())));
    const argv = [format.command, "--scenario", scenario];
    if (format.command === "fridgetag") argv.push("--model", $("model").value);
    argv.push("--seed", seed);
    const folder = `${format.command}-${scenario}-seed-${seed}`;
    if (await produce(argv, folder)) $("seed").value = randomSeed();  // fresh data next time
  });

  $("sets").replaceChildren(...catalogue.sets.map((s) => el("article", { className: "set" }, [
    el("h3", { textContent: s.title }),
    el("p", { textContent: s.description }),
    el("code", { textContent: `logger-generator ${s.argv.join(" ")} --out ${s.folder}` }),
    el("a", { className: "button ghost", href: s.file, download: "", textContent: "Download" }),
  ])));

  $("copy").addEventListener("click", async () => {
    await navigator.clipboard.writeText($("result-command").textContent);
    $("copy").textContent = "Copied";
    setTimeout(() => { $("copy").textContent = "Copy"; }, 1500);
  });
  $("again").addEventListener("click", (event) => { event.preventDefault(); if (lastDownload) save(lastDownload); });
}

call({ type: "init" })
  .then((result) => {
    catalogue = result;
    $("version").textContent = "v" + catalogue.version;
    renderForm();
    $("form").hidden = false;
    setBusy(false);
  })
  .catch((error) => alertBox(`The generator didn't load (${error.message}). Reload the page to try again.`));
