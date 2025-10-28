# Verilog Mutator (BRIDGES-compatible)

A Python tool for generating **buggy Verilog/SystemVerilog mutants** using OpenAI GPT models.  
Each clean RTL design from `rtl.json` is mutated to create a labeled dataset for
training and evaluating debugging or repair models — such as in the **BRIDGES** framework.

---

## 🔧 Features
- Loads clean RTL modules from a JSON dataset (`rtl.json`)
- Uses OpenAI’s Chat Completions API to create single-bug or multi-bug mutants
- Handles **multi-module designs** correctly (mutates one module, preserves dependencies)
- Pre-checks for syntax errors before sending any API requests
- Performs **Verilator** and **Icarus Verilog** compile checks
- Outputs a **BRIDGES-style JSON**:
  {
    "0": {"verilog": "module buggy_calc(...);"},
    "1": {"verilog": "module buggy_fifo(...);"}
  }
- Logs a detailed **manifest** of each mutation attempt, including compiler results and mutator type
- Skips or includes non-compiling mutants depending on command-line options

---

## 🧩 Requirements

### 1. System dependencies

#### 🧱 Verilator (v5.0 or newer required)
Verilator is used as the **primary linter and syntax validator**.
Mutants are considered valid if they compile successfully under:

verilator --lint-only --sv -Wall -Wno-fatal <file.sv>

Flags explained:
| Flag | Purpose |
|------|----------|
| --lint-only | Lint / syntax check only (no simulation) |
| --sv | Enable SystemVerilog parsing |
| -Wall | Show all warnings |
| -Wno-fatal | Prevent warnings from aborting the process |

⚠️ Minimum tested version: **Verilator 5.0+**  
Older versions (<4.2) may not support `--sv` or handle modern constructs correctly.

#### ⚙️ Icarus Verilog (optional secondary check)
Used for cross-validation (Verilog-2005 / SystemVerilog-2012):

iverilog -g2012 -tnull <file.sv>

The tool will report:
- “COMPILES” if Verilator succeeds,  
- “COMPILES WITH VERILATOR, FAILS IN ICARUS” if only Verilator passes,  
- “DOES NOT COMPILE (verilator)” otherwise.

##### Install on macOS:
brew install verilator icarus-verilog

##### Install on Ubuntu / Debian:
sudo apt update
sudo apt install verilator iverilog

##### Check installation:
verilator --version
iverilog -V

---

### 2. Python dependencies
Create a virtual environment and install requirements:

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

requirements.txt:
requests>=2.31.0
pandas>=2.0.0

---

## 🚀 Usage

### 1. Set your OpenAI API key
export OPENAI_API_KEY="sk-your-key-here"

### 2. Directory layout
project_root/
├── mutate.py
├── input/
│   ├── rtl.json          # clean RTL dataset
│   └── mutators.json     # mutation definitions

### 3. Example mutators.json
[
  {
    "name": "reset_polarity_flip",
    "content": "If the design has async or sync reset, invert its polarity once (e.g., if(rst)->if(!rst)) and make minimal changes so code still compiles."
  },
  {
    "name": "off_by_one_counter",
    "content": "If there is a counter or loop, change exactly one terminal comparison or increment by ±1 to introduce an off-by-one bug."
  }
]

---

### 4. Run the tool
python mutate.py input/rtl.json -n 6 --mutators input/mutators.json --check verilator

Options:

| Option | Description |
|---------|-------------|
| -n N | Process only the first **N** JSON records |
| --check both | Run **both Verilator and Icarus** for compile validation |
| --emit-noncompiling | Include mutants that fail compile checks in the output JSON |
| --sleep 0.4 | Delay (seconds) between API calls (to avoid rate limits) |
| --mutators | Path to the mutators file (.json, .csv, or .txt) |

---

### 5. Output files
After execution:

out/
├── mutants.json                # BRIDGES-compatible mutants
└── mutations_manifest.jsonl    # Per-mutant metadata and results

Example: mutants.json
{
  "0": {"verilog": "module calculator_bug(...);"},
  "1": {"verilog": "module edge_detector_bug(...);"}
}

Example: mutations_manifest.jsonl
{"json_index":"0","mutator_primary":"reset_polarity_flip","verilator_ok":true,"iverilog_ok":true,"compile_ok":true}

---

## 🧠 Design notes
- Uses **Verilator** as the main correctness signal — it supports nearly all SystemVerilog-2012 syntax used in BRIDGES.
- Automatically skips source entries that fail a Verilator **preflight compile** (to avoid wasting API calls).
- If the design has **multiple modules**, the LLM keeps all of them in one output while mutating only one module.

---

## ⚙️ Development tips
- Start with small batches: -n 2 or -n 3.
- Use --check both occasionally to verify compatibility with both simulators.
- You can reorder or edit bug types by modifying mutators.json (no code change needed).
- Run verilator --lint-only --sv manually on suspicious mutants for deeper diagnostics.

---

## 🧾 License
This repository is intended for research use within the **BRIDGES project**.

---

## 📚 Citation
If you use this tool to generate Verilog mutation datasets or train repair models,
please cite the BRIDGES framework or related publications.
