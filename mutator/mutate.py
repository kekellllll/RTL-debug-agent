#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, json, re, subprocess, time, argparse, sys, shutil, csv, tempfile, requests
from pathlib import Path

# ================================================================
#  MUTATION ENGINE — multi-mode (single API call per file)
#  - Accepts: directory of .sv files (svdir), CSV, or JSON
#  - Emits: out/mutants.json (full mutated Verilog), out/mutations_manifest.jsonl
#  - Multi mode: model returns multiple mutants (one per applicable bug type)
#    with BUG-START/BUG-END markers so we can record line numbers.
# ================================================================

# ---------- output paths ----------
OUT_DIR = Path("out")
OUT_DIR.mkdir(parents=True, exist_ok=True)
OUT_JSON = OUT_DIR / "mutants.json"
MANIFEST = OUT_DIR / "mutations_manifest.jsonl"

# ---------- model ----------
OPENAI_API_KEY = (os.environ.get("OPENAI_API_KEY") or "").strip().strip('"\u201c\u201d')
if not OPENAI_API_KEY:
    raise SystemExit("Set OPENAI_API_KEY, e.g. `export OPENAI_API_KEY=sk-...`")

MODEL = "gpt-4o"

SYSTEM_PROMPT = """You are a Verilog/SystemVerilog mutation engine.
Return syntactically valid code that compiles with a standard tool (e.g., Verilator).
Each mutant must apply exactly ONE bug type (no combinations).
Never invent new ports or modules; preserve original modules unless you wrap ONLY the changed lines.
Always wrap the changed region with:
// BUG-START[<bug_type>]
<changed line(s)>
// BUG-END[<bug_type>]"""

# ================================================================
# Tools & API helpers
# ================================================================
def run(cmd):
    return subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

def tools_preflight():
    missing = [t for t in ("verilator",) if shutil.which(t) is None]
    if missing:
        sys.exit("Missing required tool(s): " + ", ".join(missing))

def api_sanity_check(model: str):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    body = {"model": model, "max_tokens": 1,
            "messages": [{"role": "system", "content": "ping"}, {"role": "user", "content": "ok"}]}
    try:
        r = requests.post(url, headers=headers, json=body, timeout=10)
        r.raise_for_status()
    except Exception as e:
        sys.exit(f"OpenAI API check failed: {e}")

def call_openai_raw(prompt, retries=2, backoff=1.0):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"}
    body = {"model": MODEL, "temperature": 0.2,
            "messages": [{"role": "system", "content": SYSTEM_PROMPT},
                         {"role": "user", "content": prompt}]}
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, headers=headers, json=body, timeout=120)
            if resp.status_code in (429, 500, 502, 503, 504) and attempt < retries:
                time.sleep(backoff * (2 ** attempt))
                continue
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"]
        except requests.HTTPError as e:
            if attempt < retries and e.response is not None and e.response.status_code in (429, 500, 502, 503, 504):
                time.sleep(backoff * (2 ** attempt))
                continue
            raise

# ================================================================
# Normalization & compilation
# ================================================================
COMMENT_BLOCK_RE = re.compile(r"/\*.*?\*/", re.S)
COMMENT_LINE_RE  = re.compile(r"//.*?$", re.M)

def strip_comments_and_ws(s: str) -> str:
    s = COMMENT_BLOCK_RE.sub("", s)
    s = COMMENT_LINE_RE.sub("", s)
    s = re.sub(r"\s+", "", s)
    return s

def materially_changed(a: str, b: str) -> bool:
    return strip_comments_and_ws(a) != strip_comments_and_ws(b)

def write_temp_sv(text: str) -> Path:
    tf = tempfile.NamedTemporaryFile("w", suffix=".sv", delete=False)
    tf.write(text)
    if not text.endswith("\n"):
        tf.write("\n")
    tf.close()
    return Path(tf.name)

def gates_check_from_text(code_text: str, run_icarus=False):
    tmp = write_temp_sv(code_text)
    try:
        v = run(["verilator", "--lint-only", "--sv", "-Wall", "-Wno-fatal", str(tmp)])
        v_ok = (v.returncode == 0)
        i_ok = None
        if run_icarus:
            # optional: iverilog sanity; many SV features may not be supported
            i = run(["iverilog", "-g2012", "-tnull", str(tmp)])
            i_ok = (i.returncode == 0)
        return v_ok, i_ok, v.stdout
    finally:
        tmp.unlink(missing_ok=True)

# ================================================================
# Multi-mode helpers (single API call returns multiple mutants)
# ================================================================
def build_multi_prompt(src_text: str, mutators):
    """
    Ask the model to decide applicability and return one JSON with mutants.
    Each applicable mutant must contain full Verilog with BUG markers.
    """
    bug_list = [{"name": n, "content": c} for n, c in mutators]
    return (
        "You are a Verilog/SystemVerilog mutation engine.\n"
        "For each bug type below, decide if it applies to the source. "
        "Return a single JSON fenced with ```json containing:\n"
        "{ \"mutants\": [\n"
        "    {\"bug_type\":\"<name>\",\"applies\":true|false,\"rationale\":\"...\",\n"
        "     \"code\":\"<full mutated verilog with BUG markers as comments>\"}, ...\n"
        "  ] }\n"
        "Rules:\n"
        "- At most ONE mutant per bug type.\n"
        "- If not applicable, set applies=false and omit 'code'.\n"
        "- For applicable ones, modify the source with EXACTLY ONE bug type.\n"
        "- Keep original modules and ports; do not invent new ones.\n"
        "- IMPORTANT: Wrap changed lines with:\n"
        "    // BUG-START[<bug_type>]\n"
        "    <changed line(s)>\n"
        "    // BUG-END[<bug_type>]\n"
        "- Output ONLY the JSON block. No extra text.\n\n"
        f"Bug types:\n{json.dumps(bug_list, indent=2)}\n\n"
        f"Source code:\n```verilog\n{src_text}\n```"
    )

def parse_json_block(txt: str):
    m = re.search(r"```json\s*([\s\S]*?)```", txt, re.IGNORECASE)
    payload = m.group(1) if m else None
    if not payload:
        # fallback: last JSON object in the reply
        m2 = re.search(r"\{[\s\S]*\}\s*$", txt)
        payload = m2.group(0) if m2 else None
    if not payload:
        return None
    try:
        return json.loads(payload)
    except Exception:
        return None

def extract_bug_ranges(mutated_code: str):
    """
    Returns (bug_type, start_line, end_line) based on BUG markers, else (None,None,None).
    1-based line numbers in the mutated code.
    """
    lines = mutated_code.splitlines()
    start = end = bug = None
    for i, ln in enumerate(lines, start=1):
        ms = re.search(r"//\s*BUG-START\[([^]]+)\]", ln)
        me = re.search(r"//\s*BUG-END\[([^]]+)\]", ln)
        if ms:
            bug = ms.group(1)
            start = i
        if me:
            end = i
            if bug is None:
                bug = me.group(1)
            break
    return bug, start, end

# ================================================================
# Input loaders
# ================================================================
TB_HINTS = ("tb_", "_tb.sv", "testbench", "sim_")
def looks_like_tb(name: str) -> bool:
    n = name.lower()
    return any(h in n for h in TB_HINTS)

def load_first_n_svdir(dir_path: Path, n: int, patterns=None, include_testbench=False):
    """
    Load first N .sv files matching patterns (default: *.sv).
    Skips files that look like testbenches unless include_testbench=True.
    """
    if patterns is None:
        patterns = ["*.sv"]
    dir_path = Path(dir_path)
    seen = set()
    files = []
    for pat in patterns:
        for p in dir_path.rglob(pat):
            if p.suffix.lower() != ".sv":
                continue
            if not include_testbench and looks_like_tb(p.name):
                continue
            if p in seen:
                continue
            seen.add(p)
            files.append(p)
    files = sorted(files)
    out = []
    count = 0
    for p in files:
        if count >= n: break
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if not txt.strip():
            continue
        out.append((str(count), {"verilog": txt, "path": str(p)}))
        count += 1
    return out

def load_first_n_csv(csv_path: Path, n: int, column: str):
    items = []
    with csv_path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if column not in reader.fieldnames:
            raise SystemExit(f"CSV column '{column}' not found. Available: {reader.fieldnames}")
        for i, row in enumerate(reader):
            if i >= n: break
            raw = (row.get(column) or "").strip()
            if not raw: 
                continue
            items.append((str(i), {"verilog": raw, "path": f"{csv_path}#{i}"}))
    return items

def load_first_n_json(json_path: Path, n: int, field: str):
    data = json.loads(json_path.read_text(encoding="utf-8"))
    items = []
    if isinstance(data, dict):
        # BRIDGES-style
        try:
            keys = sorted(data.keys(), key=lambda k: int(k))
        except Exception:
            keys = sorted(data.keys())
        for k in keys[:n]:
            rec = data[k]
            src = (rec.get(field) or rec.get("anonymized_verilog") or "").strip()
            if not src: 
                continue
            items.append((str(k), {"verilog": src, "path": f"{json_path}:{k}"}))
    elif isinstance(data, list):
        for i, rec in enumerate(data[:n]):
            src = (rec.get(field) or rec.get("anonymized_verilog") or "").strip()
            if not src:
                continue
            items.append((str(i), {"verilog": src, "path": f"{json_path}#{i}"}))
    else:
        raise SystemExit("Unsupported JSON top-level (expected dict or list).")
    return items

def load_mutators_file(path: Path):
    data = json.loads(path.read_text(encoding="utf-8"))
    pairs = []
    for obj in data:
        name = (obj.get("name") or "").strip()
        content = (obj.get("content") or "").strip()
        if name and content:
            pairs.append((name, content))
    if not pairs:
        raise SystemExit("No mutators loaded.")
    return pairs

# ================================================================
# Main
# ================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Generate mutated Verilog/SV with single-call multi-mutant mode and compile checks."
    )
    parser.add_argument("input_path", type=str, help="Path to input (dir, CSV, or JSON).")
    parser.add_argument("-f", "--input-format", choices=["svdir", "csv", "json"], default="svdir")
    parser.add_argument("-n", "--num", type=int, help="Process first N entries/files.")
    parser.add_argument("--all", action="store_true",
                        help="Process *all* available files/records instead of requiring -n. Overrides -n if given.")
    parser.add_argument("--field", type=str, default="verilog",
                        help="When -f json, which JSON field holds source (default: verilog).")
    parser.add_argument("--csv-column", type=str, default="text",
                        help="When -f csv, which column contains the code (default: text).")
    parser.add_argument("--sv-pattern", type=str, default="*.sv",
                        help="When -f svdir, comma-separated globs to select files (default: *.sv).")
    parser.add_argument("--include-testbench", action="store_true",
                        help="Include files that look like TB: tb_*, *_tb.sv, names with 'testbench'/'sim_'.")
    parser.add_argument("--mutators", type=str, default="input/mutators.json",
                        help="Mutators list (.json) with name/content.")
    parser.add_argument("--check", choices=["verilator", "both"], default="verilator",
                        help="Compile check mode: verilator (default) or both.")
    parser.add_argument("--sleep", type=float, default=0.4, help="Sleep seconds between API calls.")
    parser.add_argument("--emit-noncompiling", action="store_true",
                        help="Include mutants that fail compile checks in the output.")
    parser.add_argument("--mode", choices=["single","multi"], default="multi",
                        help="single=legacy per-mutator looping; multi=single API returns multiple mutants (default).")
    args = parser.parse_args()

    tools_preflight()
    api_sanity_check(MODEL)

    in_path = Path(args.input_path)
    if not in_path.exists():
        typ = "directory" if args.input_format == "svdir" else "file"
        sys.exit(f"Input {typ} not found: {in_path}")

    mutators = load_mutators_file(Path(args.mutators))

    # Load based on format
    if args.input_format == "svdir":
        patterns = [p.strip() for p in (args.sv_pattern or "*.sv").split(",") if p.strip()]
        # Determine how many files to process
        if args.all:
            # Count all .sv files matching patterns
            sv_files = []
            for pat in patterns:
                sv_files.extend(in_path.rglob(pat))
            n_val = len([f for f in sv_files if f.suffix.lower() == ".sv"])
            print(f"[INFO] --all flag set → processing all {n_val} .sv files in {in_path}")
        elif args.num is None:
            sys.exit("Either -n or --all must be provided.")
        else:
            n_val = args.num
        subset = load_first_n_svdir(in_path, n_val, patterns=patterns, include_testbench=args.include_testbench)

    elif args.input_format == "csv":
        subset = load_first_n_csv(in_path, args.num, args.csv_column)
    else:  # json
        subset = load_first_n_json(in_path, args.num, args.field)

    if not subset:
        sys.exit("No records loaded from the input source (check format/field/column and -n).")

    print(f"[INFO] Using OpenAI model: {MODEL}")
    print(f"Loaded {len(subset)} record(s) from {in_path} (first {args.num}).")
    print(f"Loaded {len(mutators)} mutator(s) from {args.mutators}.\n")

    output_json = {}
    out_counter = 0

    with MANIFEST.open("w", encoding="utf-8") as w:
        for i, (idx_str, rec) in enumerate(subset, start=1):
            src = rec["verilog"]
            src_path = rec.get("path", "")
            source_meta = {
                "source_type": args.input_format,
                "dir_path": str(in_path) if args.input_format == "svdir" else None,
                "file_path": src_path if args.input_format == "svdir" else str(in_path),
                "json_index": idx_str if args.input_format == "json" else None,
                "csv_row": idx_str if args.input_format == "csv" else None,
                "csv_column": args.csv_column if args.input_format == "csv" else None,
            }

            print(f"Processing {i}/{len(subset)} — {src_path or idx_str}")

            # Pre-lint source; skip irreparably broken inputs
            v_ok_src, _, _ = gates_check_from_text(src, run_icarus=False)
            if not v_ok_src:
                print("  Source doesn't compile (verilator). Skipping.")
                continue

            base_stem = f"idx_{idx_str}"

            if args.mode == "multi":
                prompt = build_multi_prompt(src, mutators)
                try:
                    raw = call_openai_raw(prompt)
                except Exception as e:
                    print(f"[{base_stem}] API ERROR ({e})")
                    continue

                data = parse_json_block(raw)
                if not data or "mutants" not in data or not isinstance(data["mutants"], list):
                    print(f"[{base_stem}] INVALID JSON (no 'mutants')")
                    continue

                for mrec in data["mutants"]:
                    bug_type = mrec.get("bug_type")
                    applies = mrec.get("applies")
                    code_blob = (mrec.get("code") or "").strip()

                    if not bug_type or not isinstance(applies, bool):
                        continue
                    if not applies or not code_blob:
                        continue
                    if not materially_changed(src, code_blob):
                        print(f"  [{bug_type}] NO MATERIAL CHANGE (skipped)")
                        continue

                    run_icarus = (args.check == "both")
                    v_ok, i_ok, _ = gates_check_from_text(code_blob, run_icarus=run_icarus)
                    ok = v_ok if args.check == "verilator" else (v_ok and (i_ok is True))
                    status = "COMPILES" if ok else "FAILS"

                    bug_name, l1, l2 = extract_bug_ranges(code_blob)
                    print(f"  [{bug_type}] → {status} lines=({l1},{l2})")

                    if ok or args.emit_noncompiling:
                        output_json[str(out_counter)] = {"verilog": code_blob}
                        out_counter += 1

                    rec_line = {
                        **source_meta,
                        "mutator_primary": bug_type,
                        "mutator_ordered_list": [bug_type],
                        "verilator_ok": bool(v_ok),
                        "iverilog_ok": (None if i_ok is None else bool(i_ok)),
                        "compile_ok": bool(ok),
                        "bug_marker_type": bug_name,
                        "bug_lines": [l1, l2],
                    }
                    w.write(json.dumps(rec_line) + "\n")

                time.sleep(args.sleep)
                continue  # next record

            # -------------------------
            # Legacy SINGLE mode (kept for compatibility; not recommended)
            # -------------------------
            # If you want the old per-mutator looping behavior, you can place it here.
            # Default flow: do nothing in single mode unless you add your previous loop.
            print("  [single mode] No legacy loop defined here. Use --mode multi.")
            time.sleep(args.sleep)

    with OUT_JSON.open("w", encoding="utf-8") as jf:
        json.dump(output_json, jf, indent=2)

    print(f"\nDone. Mutants written: {len(output_json)}")
    print(f"Mutants JSON → {OUT_JSON}")
    print(f"Manifest     → {MANIFEST}")

if __name__ == "__main__":
    main()
