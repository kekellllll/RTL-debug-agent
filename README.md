# VerilogEval on HPC — Setup & Usage (incl. Custom LLMs)

A copy-paste guide to get **NVLabs/VerilogEval** running on a shared HPC (PSC Bridges-2), from login → environment → build → run → plug in your own LLM via an OpenAI-compatible endpoint (vLLM/TGI).

> This README assumes basic Linux shell access and Slurm.

---

## 0) What you’re running

- **VerilogEval**: evaluation harness + datasets for two tasks:
  - `spec-to-rtl`
  - `code-complete-iccad2023`  
  The standard workflow is `configure → make`. Tasks live in `dataset_$task/`.

---

## 1) Log in to HPC and start an interactive session

**SSH to the login node (example for PSC Bridges-2):**
```bash
ssh <username>@bridges2.psc.edu
```

**Request an interactive GPU session (shared GPU node):**
```bash
# Example: 1 x V100-32 for 30 minutes
interact -p GPU-shared --gres=gpu:1 -t 04:00:00
```

Notes for Bridges-2:
- `GPU` = whole GPU node (all 8 GPUs).
- `GPU-shared` = up to 4 GPUs on a shared node; charged only for what you request.

---

## 2) Shell environment (Conda + Python packages)

```bash
module load anaconda3
conda create -y -n verilog-eval python=3.11
conda activate verilog-eval
```

Install packages (LangChain split packages are required in recent versions):
```bash
pip install -U langchain langchain-openai langchain-community
# If you might use NVIDIA NIM endpoints:
pip install -U langchain-nvidia-ai-endpoints
```

---

## 3) Install Icarus Verilog **v12** (required)

VerilogEval expects **Icarus Verilog 12.x**. Build from source to a user prefix if your site doesn’t provide modules:

```bash
# Build prerequisites depend on your OS/site; commonly needed:
# autoconf, gperf, make, gcc/g++, bison, flex

git clone https://github.com/steveicarus/iverilog.git
cd iverilog
git checkout v12-branch
sh ./autoconf.sh
./configure --prefix="$HOME/local"
make -j$(nproc)
make install

# Make it visible in this shell:
export PATH="$HOME/local/bin:$PATH"
iverilog -v | head -n1    # should print Icarus Verilog version 12.x
```

> On clusters without `sudo`, install prerequisites via modules and use `--prefix` to a user-writable path, as shown above.

---

## 4) Get VerilogEval and create a build directory

```bash
# If this branch already contains VerilogEval, cd into it; otherwise:
git clone https://github.com/NVlabs/verilog-eval.git
cd verilog-eval
mkdir -p build && cd build
```

Tasks live in `dataset_spec-to-rtl/` and `dataset_code-complete-iccad2023/`; `configure` selects the right one from your `--with-task` flag.

---

## 5) Configure the run

Set your task, model string (must be one the script recognizes), few-shot examples, sampling count, and sampling params:

```bash
TASK=spec-to-rtl             # or: code-complete-iccad2023
MODEL=gpt-4o                 # see “Custom LLMs” below for using your own endpoint
SHOTS=0                      # in-context examples: 0..4
SAMPLES=1                    # samples per problem
TEMP=0                       # low temperature = more stable
TOPP=0.01

../configure   --with-task="$TASK"   --with-model="$MODEL"   --with-examples="$SHOTS"   --with-samples="$SAMPLES"   --with-temperature="$TEMP"   --with-top-p="$TOPP"
```

> Model strings are checked against a whitelist in the driver script. You can still route traffic to **your** backend via a custom base URL (next section).

---

## 6) Provide credentials (and optionally a custom **base URL**)

VerilogEval calls LLMs via **LangChain** (e.g., `ChatOpenAI`). That client supports a custom **`openai_api_base` (alias `base_url`)** and reads keys from env vars:

```bash
# If using OpenAI, set your key:
export OPENAI_API_KEY=YOUR_KEY

# If using your own OpenAI-compatible server (vLLM/TGI), set a base URL:
export OPENAI_BASE_URL=http://YOUR_HOST:8000/v1   # keep the /v1 suffix!
```

Leave `OPENAI_BASE_URL` empty when calling the official OpenAI API.

---

## 7) Run the benchmark

```bash
# Start with single-thread to avoid rate limits and simplify logs:
make -j1 V=1

# Once stable, scale up carefully:
make -j2
make -j4
```

Per-problem artifacts/logs appear under `build/ProbXXX_*`, and an overall **`summary.txt`** aggregates pass rates.

---

## 8) Using a **custom LLM** (OpenAI-compatible)

VerilogEval doesn’t require OpenAI’s hosted models; it only needs a **Chat/Completions-style API**. Two common ways to expose your own model:

### A) vLLM’s OpenAI-compatible server (recommended)

**Launch a server that implements OpenAI Chat/Completions:**
```bash
pip install -U vllm
python -m vllm.entrypoints.openai.api_server   --model deepseek-ai/deepseek-coder-6.7b-instruct   --dtype auto   --api-key token-abc123   --host 0.0.0.0 --port 8000
# Endpoint: http://HOST:8000/v1/chat/completions
```

**Point VerilogEval to your vLLM server:**
```bash
export OPENAI_API_KEY=token-abc123
export OPENAI_BASE_URL=http://HOST:8000/v1

../configure --with-task="$TASK" --with-model="gpt-4o"              --with-examples="$SHOTS" --with-samples="$SAMPLES"              --with-temperature="$TEMP" --with-top-p="$TOPP"
make -j1
```

> Keeping `--with-model=gpt-4o` is fine because the script whitelists strings locally; routing is handled by `OPENAI_BASE_URL`, so requests go to **your** endpoint.

### B) Hugging Face **Text Generation Inference (TGI)**

TGI exposes an **OpenAI-compatible “Messages API”** at `/v1/chat/completions`. Use the same env vars (`OPENAI_BASE_URL`, `OPENAI_API_KEY`) and the same VerilogEval commands.

---

## 9) Troubleshooting

- **`conda: command not found`** after re-connecting  
  Load Anaconda again and re-activate the env (`module load anaconda3 && conda activate verilog-eval`). HPC sessions don’t persist modules by default.

- **Icarus not found or wrong version**  
  Ensure `iverilog -v` prints **12.x** and your `$PATH` includes the install prefix. Icarus needs `autoconf`, `gperf`, `bison`, `flex`, etc., when building from source.

- **Unknown model**  
  Use a model string that the driver script accepts (e.g., `gpt-4o`) and steer requests via `OPENAI_BASE_URL`.

- **401/403/429 or timeouts in `*-sv-generate.log`**  
  Re-export keys; drop to `make -j1`; gradually increase `-j` to respect rate limits.

- **LangChain callback import warning**  
  Newer LangChain places `get_openai_callback` in `langchain_community`; install that package to avoid `ModuleNotFoundError`.

---

## 10) Quick “cheat sheet”

```bash
# HPC login → interactive job (Bridges-2 example)
ssh <user>@bridges2.psc.edu
interact -p GPU-shared --gres=gpu:1 -t 04:00:00

# Conda env
module load anaconda3
conda create -y -n verilog-eval python=3.11
conda activate verilog-eval
pip install -U langchain langchain-openai langchain-community

# Icarus Verilog v12 (user prefix)
git clone https://github.com/steveicarus/iverilog.git && cd iverilog
git checkout v12-branch && sh ./autoconf.sh
./configure --prefix="$HOME/local" && make -j$(nproc) && make install
export PATH="$HOME/local/bin:$PATH" && iverilog -v | head -n1
cd ..

# VerilogEval
git clone https://github.com/NVlabs/verilog-eval.git
cd verilog-eval && mkdir -p build && cd build

# Choose task/model; set keys or base URL
export OPENAI_API_KEY=YOUR_KEY
# export OPENAI_BASE_URL=http://HOST:8000/v1    # if using vLLM/TGI

../configure --with-task=spec-to-rtl --with-model="gpt-4o"              --with-examples=0 --with-samples=1 --with-temperature=0 --with-top-p=0.01
make -j1
```

---

### License

If you vendor or redistribute VerilogEval, keep its upstream license file with the code.
