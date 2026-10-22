// Checks that the site's downloads (Pyodide, web.py) match the command line (CPython) byte for
// byte, for every format and scenario plus the ready-made sets.
//
//   site/build.sh && (cd site && npm install --no-save pyodide@314.0.7 && node check.mjs)
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, readdirSync, rmSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, relative } from "node:path";
import { loadPyodide } from "pyodide";

const here = new URL(".", import.meta.url).pathname;
const pyodide = await loadPyodide();
pyodide.unpackArchive(new Uint8Array(readFileSync(join(here, "public/pkg/logger_generator.whl"))), "wheel");
pyodide.FS.writeFile("/home/pyodide/web.py", readFileSync(join(here, "public/web.py"), "utf8"));
pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide')");
const web = pyodide.pyimport("web");
pyodide.runPython(`
import hashlib, io, json, zipfile
def zip_hashes(data):
    with zipfile.ZipFile(io.BytesIO(bytes(data))) as z:
        return json.dumps({i.filename.split("/", 1)[1]: hashlib.sha256(z.read(i)).hexdigest()
                           for i in z.infolist() if not i.is_dir()})
`);
const zipHashes = pyodide.globals.get("zip_hashes");

function cliHashes(argv) {
  const out = mkdtempSync(join(tmpdir(), "lg-check-"));
  try {
    execFileSync("uv", ["run", "-q", "--project", join(here, ".."), "logger-generator", ...argv, "--out", out]);
    const hashes = {};
    const walk = (dir) => {
      for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) walk(path);
        else hashes[relative(out, path)] = createHash("sha256").update(readFileSync(path)).digest("hex");
      }
    };
    walk(out);
    return hashes;
  } finally {
    rmSync(out, { recursive: true, force: true });
  }
}

const catalogue = JSON.parse(web.catalogue());
const cases = [];
for (const format of catalogue.formats) {
  for (const scenario of format.scenarios) cases.push([format.command, "--scenario", scenario.name, "--seed", "4242"]);
}
cases.push(["fridgetag", "--model", "2L", "--seed", "7"]);
for (const set of catalogue.sets) cases.push(set.argv);

let failures = 0;
for (const argv of cases) {
  const result = web.run(JSON.stringify([...argv, "case"]));
  const [zip] = result.toJs();
  result.destroy();
  const site = JSON.parse(zipHashes(zip));
  const cli = cliHashes(argv);
  const same = JSON.stringify(Object.entries(site).sort()) === JSON.stringify(Object.entries(cli).sort());
  if (!same) failures++;
  console.log(`${same ? "ok  " : "DIFF"} ${argv.join(" ")} (${Object.keys(site).length} files)`);
}
console.log(failures ? `${failures} of ${cases.length} differ` : `all ${cases.length} match`);
process.exit(failures ? 1 : 0);
