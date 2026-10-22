// Runs logger-generator in Pyodide, off the page's main thread.
// Messages in: {id, type: "init"} or {id, type: "run", argv: [...args, folderName]}.
// Messages out: {id, ok, result | error}.
import { loadPyodide } from "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/pyodide.mjs";

let ready;

async function init() {
  const pyodide = await loadPyodide({ indexURL: "https://cdn.jsdelivr.net/npm/pyodide@314.0.7/" });
  const [wheel, glue] = await Promise.all([
    fetch("pkg/logger_generator.whl", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error("package " + r.status); return r.arrayBuffer(); }),
    fetch("web.py", { cache: "no-cache" }).then((r) => { if (!r.ok) throw new Error("web.py " + r.status); return r.text(); }),
  ]);
  pyodide.unpackArchive(wheel, "wheel");
  pyodide.FS.writeFile("/home/pyodide/web.py", glue);
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import web");
  return pyodide;
}

self.onmessage = async ({ data }) => {
  const { id, type } = data;
  try {
    ready ??= init();
    const pyodide = await ready;
    const web = pyodide.pyimport("web");
    if (type === "init") {
      self.postMessage({ id, ok: true, result: JSON.parse(web.catalogue()) });
    } else if (type === "run") {
      const result = web.run(JSON.stringify(data.argv));
      const [bytes, summary, name] = result.toJs();
      result.destroy();
      const zip = bytes.slice();  // copy out of the Python heap before transferring
      self.postMessage({ id, ok: true, result: { zip, summary, name } }, [zip.buffer]);
    }
  } catch (error) {
    // argparse exits on bad input; surface its message rather than "SystemExit".
    self.postMessage({ id, ok: false, error: String(error.message || error).split("\n").filter(Boolean).slice(-1)[0] });
  }
};
