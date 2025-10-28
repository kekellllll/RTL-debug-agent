#!/usr/bin/env python3
import os, json, re, subprocess, hashlib, time, argparse, sys, shutil, csv, tempfile
from pathlib import Path
import requests

# -------------------
# Paths & constants
# -------------------
OUT_DIR = Path("out")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = OUT_DIR / "mutants.json"               # BRIDGES-style output
MANIFEST = OUT_DIR / "mutations_manifest.jsonl"   # detailed per-mutant metadata

# -------------------
# API key (sanitized) and model
# -------------------
OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip()
OPENAI_API_KEY = OPENAI_API_KEY.strip(' \t\r\n"\'\u201c\u201d')
try:
    OPENAI_API_KEY.encode("ascii")
except UnicodeEncodeError:
    raise SystemExit("OPENAI_API_KEY contains non-ASCII characters (e.g., smart quotes). Re-export it with plain quotes.")
if not OPENAI_API_KEY:
    raise SystemExit("Set OPENAI_API_KEY in env (e.g., export OPENAI_API_KEY=sk-...)")

MODEL = "gpt-4o"  # or "gpt-4o"

SYSTEM_PROMPT = """You are a meticulous Verilog/SystemVerilog mutation engine used to create buggy versions of clean RTL for testing repair systems.
Rules:
- If the source contains a single module, return that single module.
- If the source contains multiple modules, return ALL original modules in one code fence; mutate exactly ONE module and keep the others unchanged (verbatim).
- Preserve existing module names and ports; do not invent new ports, clocks, or modules.
- Apply exactly ONE mutation in total (not one per module).
- Keep the code syntactically valid; do not introduce external dependencies.
- Return ONLY a single fenced code block: ```verilog ... ```
- Do not include any explanations or comments; just the code.
"""

# -------------------
# Utility helpers
# -------------------
def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def tools_preflight():
    missing = [t for t in ("verilator", "iverilog") if shutil.which(t) is None]
    if missing:
        sys.exit(f"Missing required tool(s): {', '.join(missing)}. "
                 f"Install via Homebrew (brew install verilator icarus-verilog) or conda (conda install -c conda-forge verilator iverilog).")

def api_sanity_check(model: str):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    body = {"model": model, "temperature": 0, "max_tokens": 1,
            "messages": [{"role": "system", "content": "You are a minimal responder."},
                         {"role": "user", "content": "ok"}]}
    try:
        resp = requests.post(url, headers=headers, json=body, timeout=15)
    except requests.exceptions.Timeout:
        raise SystemExit("OpenAI API sanity check timed out. Check your network.")
    except requests.exceptions.ConnectionError as e:
        raise SystemExit(f"Network error reaching OpenAI API: {e}")
    except requests.exceptions.RequestException as e:
        raise SystemExit(f"Unexpected request error: {e}")
    if resp.status_code == 401:
        raise SystemExit("Unauthorized (401): invalid or missing OPENAI_API_KEY.")
    if resp.status_code == 404:
        raise SystemExit(f"Model not found (404): '{model}'. Change MODEL or check your access.")
    if resp.status_code == 429:
        raise SystemExit("Rate limited or quota exceeded (429): check usage limits or slow down.")
    if 500 <= resp.status_code < 600:
        raise SystemExit(f"OpenAI server error ({resp.status_code}). Try again later.")
    # Don't over-validate content; reaching here is good enough.

def call_openai(prompt, retries=2, backoff=1.0):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    body = {"model": MODEL, "temperature": 0.2,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": prompt}]}
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=120)
            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt < retries:
                    time.sleep(backoff * (2 ** attempt))
                    continue
            resp.raise_for_status()
            txt = resp.json()["choices"][0]["message"]["content"]
            m = re.search(r"```(?:verilog)?\s*([\s\S]*?)```", txt, re.IGNORECASE)
            return (m.group(1) if m else txt).strip()
        except requests.HTTPError as e:
            if attempt < retries and e.response is not None and e.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (2 ** attempt))
                continue
            raise

MODULE_RE = re.compile(r'^\s*module\s+\w+', re.MULTILINE)

def is_multimodule(src_text: str) -> bool:
    return len(MODULE_RE.findall(src_text)) > 1

def materially_changed(a, b):
    na = re.sub(r"\s+", "", a)
    nb = re.sub(r"\s+", "", b)
    return na != nb

def write_temp_sv(text: str) -> Path:
    tf = tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False)
    try:
        tf.write(text)
        if not text.endswith("\n"):
            tf.write("\n")
        tmp = Path(tf.name)
    finally:
        tf.close()
    return tmp

def gates_check_from_text(code_text: str, run_icarus=True):
    tmp = write_temp_sv(code_text)
    try:
        v = run(["verilator", "--lint-only", "--sv", "-Wall", "-Wno-fatal", str(tmp)])
        v_ok = (v.returncode == 0)
        i_ok = None
        if run_icarus:
            i = run(["iverilog", "-g2012", "-tnull", str(tmp)])
            i_ok = (i.returncode == 0)
        return v_ok, i_ok, v.stdout
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass

def preflight_compile_source(src_text: str) -> bool:
    v_ok, _, _ = gates_check_from_text(src_text, run_icarus=False)
    return v_ok

def build_prompt_with_fallbacks(src_text, ordered_mutators):
    items = "\n".join(f"- {name}: {content}" for name, content in ordered_mutators)
    mm_hint = ("This source has multiple modules. Include all modules in the output and mutate exactly one of them."
               if is_multimodule(src_text) else
               "This source has a single module.")
    return (
        f"{mm_hint}\n"
        "Apply exactly ONE mutation from the following ordered list. "
        "If the first is impossible because the construct does not exist in the given code, "
        "attempt the next, and so on. Never invent new ports or clocks. "
        "If truly none apply, return the original code unchanged; this should be rare.\n\n"
        f"Ordered mutations:\n{items}\n\n"
        f"Source code:\n```verilog\n{src_text}\n```"
    )

def load_first_n(json_path: Path, n: int):
    with json_path.open("r") as f:
        data = json.load(f)
    items = []
    if isinstance(data, dict):
        try:
            keys = sorted(data.keys(), key=lambda k: int(k))
        except Exception:
            keys = sorted(data.keys())
        for k in keys[:n]:
            items.append((str(k), data[k]))
    elif isinstance(data, list):
        for i, rec in enumerate(data[:n]):
            items.append((str(i), rec))
    else:
        raise SystemExit("Unsupported JSON top-level type (expected dict or list).")
    return items

def load_mutators_file(path: Path):
    if not path.exists():
        raise SystemExit(f"Mutators file not found: {path}")
    ext = path.suffix.lower()
    pairs = []
    if ext == ".json":
        data = json.loads(path.read_text())
        if not isinstance(data, list):
            raise SystemExit("JSON mutators file must be a list of {name, content}.")
        for obj in data:
            name = (obj.get("name") or "").strip()
            content = (obj.get("content") or "").strip()
            if name and content:
                pairs.append((name, content))
    elif ext == ".csv":
        with path.open(newline="") as f:
            reader = csv.DictReader(f)
            if "name" not in reader.fieldnames or "content" not in reader.fieldnames:
                raise SystemExit("CSV mutators file must have headers: name,content")
            for row in reader:
                name = (row.get("name") or "").strip()
                content = (row.get("content") or "").strip()
                if name and content:
                    pairs.append((name, content))
    else:
        # .txt: alternating lines name/content (blank lines allowed between pairs)
        raw = path.read_text().splitlines()
        buf = [ln for ln in raw if ln.strip() != ""]
        if len(buf) % 2 != 0:
            raise SystemExit("TXT mutators must be pairs of lines: name then content.")
        for i in range(0, len(buf), 2):
            name = buf[i].strip()
            content = buf[i+1].strip()
            if name and content:
                pairs.append((name, content))
    if not pairs:
        raise SystemExit("No mutators loaded from file.")
    return pairs

# -------------------
# Main
# -------------------
def main():
    parser = argparse.ArgumentParser(description="Mutate Verilog/SystemVerilog modules from a JSON dataset using OpenAI, with external mutators, automatic fallbacks, and BRIDGES-style JSON output.")
    parser.add_argument("json_path", type=str, help="Path to the input JSON file.")
    parser.add_argument("-n", "--num", type=int, required=True, help="Process only the first N entries from the JSON.")
    parser.add_argument("--field", type=str, default="verilog", help="Which JSON field holds the source code (default: verilog). Fallback is anonymized_verilog.")
    parser.add_argument("--sleep", type=float, default=0.4, help="Sleep seconds between API calls (default: 0.4).")
    parser.add_argument("--mutators", type=str, default="input/mutators.json", help="Path to mutators file (.json, .csv, or .txt). Order defines fallback order.")
    parser.add_argument("--check", choices=["verilator", "both"], default="verilator", help="Compile check mode: 'verilator' (default) or 'both' (verilator + iverilog).")
    parser.add_argument("--emit-noncompiling", action="store_true", help="Include mutants that fail compile checks in the output JSON (default: exclude).")
    args = parser.parse_args()

    tools_preflight()
    api_sanity_check(MODEL)

    json_path = Path(args.json_path)
    if not json_path.exists():
        sys.exit(f"JSON file not found: {json_path}")

    mutators = load_mutators_file(Path(args.mutators))  # list[(name, content)]
    subset = load_first_n(json_path, args.num)
    if not subset:
        sys.exit("No records loaded from the JSON (check format and -n).")

    print(f"[INFO] Using OpenAI model: {MODEL}")
    print(f"Loaded {len(subset)} record(s) from {json_path} (first {args.num}).")
    print(f"Loaded {len(mutators)} mutator(s) from {args.mutators} (order = fallback order).")

    # BRIDGES-style output accumulator
    output_json = {}
    out_counter = 0

    summary_total = summary_pass = summary_fail = 0

    with MANIFEST.open("w") as w:
        total = len(subset)
        for i, (idx_str, rec) in enumerate(subset, start=1):
            print(f"Processing record {i}/{total} (JSON index {idx_str})")
            src = (rec.get(args.field) or "").strip()
            if not src:
                src = (rec.get("anonymized_verilog") or "").strip()
            if not src:
                print(f"Skipping index {idx_str}: no '{args.field}' or 'anonymized_verilog' found.")
                continue

            # Preflight compile the source; skip broken sources
            if not preflight_compile_source(src):
                print(f"[jsonidx_{idx_str}] source does not compile; skipping before mutation.")
                continue

            base_stem = f"jsonidx_{idx_str}"

            # For each primary mutator, build ordered fallback list = file order rotated at primary
            for p_idx, (primary_name, _) in enumerate(mutators):
                ordered = mutators[p_idx:] + mutators[:p_idx]
                prompt = build_prompt_with_fallbacks(src, ordered)

                try:
                    mutated = call_openai(prompt)
                except Exception as e:
                    print(f"[{base_stem}] mutation '{primary_name}' → API ERROR ({e})")
                    continue

                if not mutated or "module" not in mutated or "endmodule" not in mutated:
                    print(f"[{base_stem}] mutation '{primary_name}' → MALFORMED OUTPUT (skipped)")
                    continue

                if not materially_changed(src, mutated):
                    print(f"[{base_stem}] mutation '{primary_name}' → NO-OP (skipped)")
                    continue

                # Compile checks from code text (no need to write persistent .sv files)
                run_icarus = (args.check == "both")
                v_ok, i_ok, _ = gates_check_from_text(mutated, run_icarus=run_icarus)
                ok = v_ok if args.check == "verilator" else (v_ok and (i_ok is True))

                # Console status
                if ok:
                    status = "COMPILES"
                elif v_ok and i_ok is False:
                    status = "COMPILES WITH VERILATOR, FAILS IN ICARUS"
                elif not v_ok:
                    status = "DOES NOT COMPILE (verilator)"
                else:
                    status = "DOES NOT COMPILE"
                print(f"[{base_stem}] mutation '{primary_name}' → {status}")

                # Include in BRIDGES-style JSON only if ok, unless user opted in
                if ok or args.emit_noncompiling:
                    output_json[str(out_counter)] = {"verilog": mutated}
                    out_counter += 1

                # Manifest line
                rec_line = {
                    "source_type": "json",
                    "json_path": str(json_path),
                    "json_index": idx_str,
                    "mutator_primary": primary_name,
                    "mutator_ordered_list": [n for n, _ in ordered],
                    "verilator_ok": bool(v_ok),
                    "iverilog_ok": (None if i_ok is None else bool(i_ok)),
                    "compile_ok": bool(ok)
                }
                w.write(json.dumps(rec_line) + "\n")

                summary_total += 1
                if ok:
                    summary_pass += 1
                else:
                    summary_fail += 1

                time.sleep(args.sleep)

    # Write BRIDGES-style mutants JSON
    with OUT_JSON.open("w") as jf:
        json.dump(output_json, jf, indent=2)

    print(f"\nSummary: {summary_total} mutations generated "
          f"({summary_pass} compile successfully, {summary_fail} failed to compile)")
    print(f"\nMutants JSON → {OUT_JSON}\nManifest → {MANIFEST}")

if __name__ == "__main__":
    main()
