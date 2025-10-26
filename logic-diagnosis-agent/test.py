# main.py
import os, io, glob, shlex, subprocess, typing as T
from typing import Optional, List
import pandas as pd
import networkx as nx

from langchain.tools import tool
from langchain.agents import create_agent
from langchain.agents.middleware import SummarizationMiddleware
# --- Config
WORK_DIR = os.path.abspath("workspace")
os.makedirs(WORK_DIR, exist_ok=True)

ALLOWED_BINARIES = {
    "backconer": "./env/backconer",
    "ganga": "./env/ganga",
    "matcher": "./env/matcher",
    "atalanta": "./env/atalanta",
    "hope": "./env/hope",
}
MAX_STDOUT_CHARS = 8000
DEFAULT_TIMEOUT_SEC = 60

# --- Domain state (optional for your python_data_tool or future use)
graph = nx.DiGraph()
graph.add_edges_from([("PI_a","U1"),("PI_b","U1"),("U1","U2"),("U2","PO_y")])
nx.set_node_attributes(graph, {"U1":{"type":"NAND2","location":(12,34)}, "U2":{"type":"INV","location":(20,40)}})
df = pd.DataFrame([
    {"fault":"U1/SA0","observed":0,"predicted":0.2},
    {"fault":"U1/SA1","observed":1,"predicted":0.7},
    {"fault":"U2/SA0","observed":0,"predicted":0.1},
])

def _truncate(text: str, limit: int = MAX_STDOUT_CHARS) -> str:
    return text if len(text) <= limit else text[:limit] + f"\n... [truncated {len(text)-limit} chars]"

def _file_snapshot(dirpath: str) -> set[str]:
    return set(sorted([
        os.path.relpath(p, dirpath)
        for p in glob.glob(os.path.join(dirpath, "**/*"), recursive=True)
        if os.path.isfile(p)
    ]))

def _diff_files(before: set[str], after: set[str]) -> list[str]:
    return sorted(list(after - before))


def _expand_globs(tokens: List[str]) -> List[str]:
    # For non-flag tokens that contain glob chars, expand relative to WORK_DIR
    out: List[str] = []
    for i, t in enumerate(tokens):
        if t.startswith("-") or not any(ch in t for ch in "*?[]"):
            out.append(t); continue
        matches = glob.glob(os.path.join(WORK_DIR, t))
        rels = [os.path.relpath(m, WORK_DIR) for m in matches]
        out.extend(rels if rels else [t])  # if no match, keep original
    return out

def _run_list(cmd_list: List[str], timeout_sec: int) -> dict:
    before = _file_snapshot(WORK_DIR)
    try:
        proc = subprocess.run(
            cmd_list,
            cwd=WORK_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=int(timeout_sec),
            check=False,
        )
        stdout = _truncate(proc.stdout or "")
        stderr = _truncate(proc.stderr or "")
    except subprocess.TimeoutExpired:
        return {"cmd": " ".join(shlex.quote(x) for x in cmd_list), "error": f"Timeout after {timeout_sec}s."}
    except FileNotFoundError as e:
        return {"cmd": " ".join(shlex.quote(x) for x in cmd_list), "error": f"Binary not found: {cmd_list[0]}"}
    after = _file_snapshot(WORK_DIR)
    return {
        "cmd": " ".join(shlex.quote(x) for x in cmd_list),
        "stdout": stdout,
        "stderr": stderr,
        "created_files": _diff_files(before, after),
        "returncode": proc.returncode,
    }

def _safe_path(rel_or_abs: str) -> Optional[str]:
    abs_path = os.path.abspath(os.path.join(WORK_DIR, rel_or_abs))
    return abs_path if abs_path.startswith(os.path.join(WORK_DIR, "")) else None

@tool
def run_terminal(command: str, timeout_sec: int = DEFAULT_TIMEOUT_SEC) -> dict:
    """
    Run any shell command (pipelines/redirects allowed) EXCEPT `rm` and `mv`.
    If the command starts with a known alias in ALLOWED_BINARIES, rewrite it
    to the absolute path (e.g., 'ganga' -> './env/ganga'). Also prepends ./env
    to PATH so these binaries are discoverable in pipelines/subshells.
    Returns: {cmd, stdout, stderr, returncode, created_files} | {error}
    """
    if not command or not isinstance(command, str):
        return {"error": "Provide a non-empty command string."}

    # Block only `rm` and `mv` anywhere as standalone tokens
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError as e:
        return {"error": f"Parse error: {e}"}
    if any(tok in {"rm", "mv"} for tok in tokens):
        return {"error": "Commands 'rm' and 'mv' are not allowed."}

    # Optional alias rewrite when the command STARTS with a known tool
    rewritten_cmd = command
    if tokens and tokens[0] in ALLOWED_BINARIES:
        tool_path = ALLOWED_BINARIES[tokens[0]]
        # Reconstruct the command safely with the resolved path as argv[0]
        rewritten_cmd = " ".join([shlex.quote(tool_path)] + [shlex.quote(t) for t in tokens[1:]])

    def _list_files_under(base: str) -> set:
        out = set()
        for root, _, files in os.walk(base):
            for f in files:
                out.add(os.path.relpath(os.path.join(root, f), base))
        return out

    before = _list_files_under(WORK_DIR)

    # Also make ./env tools available anywhere in the pipeline via PATH
    env = os.environ.copy()
    env_dir = os.path.abspath("./env")
    env["PATH"] = env_dir + os.pathsep + env.get("PATH", "")

    try:
        proc = subprocess.run(
            rewritten_cmd,
            shell=True,              # allow pipes/redirects/&&/globs
            cwd=WORK_DIR,
            capture_output=True,
            text=True,
            timeout=timeout_sec,
            env=env,
        )
        after = _list_files_under(WORK_DIR)
        created = sorted(after - before)
        return {
            "cmd": command,
            "stdout": _truncate(proc.stdout or ""),
            "stderr": _truncate(proc.stderr or ""),
            "created_files": created,
            "returncode": proc.returncode,
        }

    except subprocess.TimeoutExpired as e:
        return {
            "cmd": command,
            "stdout": _truncate(e.output or ""),
            "stderr": _truncate(e.stderr or ""),
            "created_files": [],
            "returncode": 124,
            "error": f"TimeoutExpired after {timeout_sec}s",
        }
    except Exception as e:
        return {"cmd": command, "error": f"{type(e).__name__}: {e}"}


# --- Agent
SYSTEM_PROMPT = """
You are a logic diagnosis agent. Your task is to find the fault location and behavior based on the given tester response and available tools.

The data you are provided include: 
./data/cut.bench, Circuit Under Test (CUT) 
./data/cut.test, test patterns applied 
./data/cut.tester, test responser from tester

You have ONE tool, run_terminal(command), that can run ONLY:
- backconer, ganga, matcher, atalanta, hope (see manuals below),
- or the safe helpers: ls (glob supported), cat, echo.

Rules:
- Run exactly ONE command per call (no pipes/&&/;).
- Always specify full arguments and file paths relative to the workspace.
- If you need files, first check with: ls **/*.bench, ls **/*.test, etc.
- Prefer deterministic flows: (1) ls → (2) run the relevant binary → (3) cat/read outputs.
- If a command fails, read stderr and adjust flags; then retry ONCE.

Below are mannul/examples for tools:

=============
1. backconer
 Example use of the backconer:
  In order to obtain the backcone of the primary outputs U31 and U33 of
  cut.bench benchmark, backconer is run as follows:
   prompt> backconer ./data/cut.bench U31 U33

=============
2. ganga
 ganga can be used to generate the test for a circuit, it can also find
 all equivalent fault classes and all faults in the circuit.

  prompt> ganga cut.bench

 This will generate 2 files and one folder.
  
  file 1: cut.fclass    fault colapsing tree
  file 2: cut.order     all faults in the circuit. 
  Note that this .order fault file has a different format with .ssl file format required by other programs. Specifically, .ssl requires the first line indicating number of faults in the file, while generated .order does not provide such a line.
  folder: result        generated test

 A new feature added to ganga to help you with your diagnosis project
 is response file generation. For a set of SSL faults and a given test
 set ganga is able to generate the response file for each SSL
 fault. You can also input your selected list of SSL fault using the
 "--ssls <FILE>" option. The format of the SSLs file is:

  <number-of-SSL-faults>
  1: SSL-fault-1
  2: SSL-fault-2
  ...and so on.

 An example SSL fault file for ./data/cut.bench is:

  2
  1: U31 SA1
  2: U36 SA0

 The responses for SSL faults can be generated as follows:

  prompt> ganga ./data/cut.bench --ssls cut.ssls --test cut.test --diagnosis

 The responses are stored in the following directory:

  results/responses/cut/

 An example response file looks as follows:

   1: 10001  01  01 
   2: 11111  10  10 

 The format is: <pattern-number>: PI-values Good-PO-values Faulty-PO-values

=======
3. matcher
Example use of matcher:
  Lets say you are provided with a tester file "cut.tester". After
  performing some kind of diagnosis you have come up with a set of
  likely SSL faults that explain the tester results. These are placed
  in the file "cut.ssls". The format for this file is the same as the
  format expected by ganga for the SSL faults file (please see README.ganga 
  for the format). The test set used to obtain the tester results are 
  placed in "cut.tests". The matcher can be used as follows:

   prompt> bin/matcher cut.bench cut.tester cut.ssls cut.tests

=========
4. atalanta
EXAMPLES:
	atalanta c432.bench
	   --- generates test patterns for the circuit c432.bench
	       with default options (i.e., the same as
	       atalanta -r 16 -R -s 0 -b 10 -B 20 -c 2 -t c432.test 
       	       c432.bench).
	       The generated test patterns are stored in file 
	       c432.test and the summary of the test pattern
	       is reported to the standard output (CRT terminal).

        atalanta -A -f c432.flt c432.bench
           --- Diagnostic mode run
               reads the fault list from the file c432.flt, and
               generates all test patterns for each fault.

        atalanta -D 2 c432.bench
           --- Diagnostic mode run
               Generates n test patterns for each fault.

======
5. hope
EXAMPLES: 
hope -t cut.test ./data/cut.bench 
--- simulates the circuit ./data/cut.bench  using the test patterns in the file "cut.test". 
The fault simulation stops when all test patterns in the file "cut.test" are simulated or all faults are detected. 
The summary of the fault simulation is reported to the standard output (CRT terminal). 

hope -f cut.fault -t cut.test -l cut.dict -N -D cut.bench 
--- reads the fault list from the file "cut.fault" and simulates faults in a diagnostic mode, i.e., no fault dropping is applied. 
The result of fault simulation is reported in the log file "cut.dict". In the log file, the list of faults detected by each test pattern is reported. 


NOTE, you are not allowed to run more test patterns (diagnostic ATPG) to distinguish faults.
./data/cut.test is the only test files and ./data/cut.tester is the only tester response you can diagnosis.
Finnally, even if you cannot make an exact diagnosis, report all possible callouts as your diagnosis result.

Some hint about diagnosis:
Used ganga and matcher first to check the circuit behavior. By running ganga, you could generate a fclass(list of all faults based on dominance and equivalence relationship) and b02.order(list of stuck at faults) files. 
Diagnosis can be performed by fault simulating all the possible SSL faults using the supplied test set and then comparing the provided CUT (circuit under test) tester response with each fault simulation response. 

NEVER exit UNTIL you find some reasonable callout. 
Your final results MUST include a reasonable diagnosis callout.
"""

MODEL = "openai:gpt-4o"

agent = create_agent(
    model=MODEL,
    tools=[run_terminal],
    middleware=[
    SummarizationMiddleware(
        model="openai:gpt-4o",
        max_tokens_before_summary=4000,  # Trigger summarization at 4000 tokens
        messages_to_keep=20,  # Keep last 20 messages after summary
    )
    ],
    system_prompt=SYSTEM_PROMPT,
)

from rich.console import Console, Group
from rich.panel import Panel
from rich.rule import Rule
from rich.syntax import Syntax
from rich.text import Text   

import json, shutil

console = Console(width=shutil.get_terminal_size((100, 20)).columns)
TRUNC = 800

def _trim(s, n=TRUNC):
    if s is None: return ""
    s = str(s)
    return s if len(s) <= n else s[:n] + f"\n... [truncated {len(s)-n} chars]"

def _code_block(d):
    try:
        return Syntax(json.dumps(d, indent=2, ensure_ascii=False), "json", word_wrap=True)
    except Exception:
        return Syntax(str(d), "text", word_wrap=True)

def pretty_print_update_rich(upd: dict):
    # Tool observations
    if "tools" in upd and "messages" in upd["tools"]:
        for m in upd["tools"]["messages"]:
            name = "tool"
            content = m.content
            try:
                parsed = json.loads(content) if isinstance(content, str) else content
            except Exception:
                parsed = content

            items = []  # list of Rich renderables

            if isinstance(parsed, dict):
                if parsed.get("cmd"):
                    items.append(Text.from_markup(f"[bold]cmd:[/bold] {parsed['cmd']}"))

                if "stdout" in parsed:
                    items.append(Panel.fit(_trim(parsed.get("stdout", "")), title="stdout"))

                if parsed.get("stderr"):
                    items.append(Panel.fit(_trim(parsed.get("stderr", "")), title="stderr", border_style="red"))

                if parsed.get("error"):
                    items.append(Text.from_markup(f"[red]error:[/red] {parsed['error']}"))

                if parsed.get("created_files"):
                    items.append(Text.from_markup(f"[green]created_files:[/green] {parsed['created_files']}"))

                if parsed.get("returncode") is not None:
                    items.append(Text.from_markup(f"[bold]returncode:[/bold] {parsed['returncode']}"))
            else:
                items.append(Text(_trim(str(parsed))))

            console.print(Rule())
            console.print(Panel(Group(*items), title=f"👀 Observation · {name}", border_style="green"))
            return

    # Model messages (thoughts, tool calls, final)
    if "model" in upd and "messages" in upd["model"]:
        for m in upd["model"]["messages"]:
            tool_calls = getattr(m, "additional_kwargs", {}).get("tool_calls")
            content = getattr(m, "content", None)

            if tool_calls:
                if content:
                    console.print(Rule())
                    console.print(Panel.fit(content, title="🧠 Thought", border_style="cyan"))
                for tc in tool_calls:
                    name = tc.get("name", "tool")
                    args = tc.get("args", {})
                    console.print(Rule())
                    console.print(Panel(_code_block(args), title=f"⚙️ Action · {name}", border_style="yellow"))
                return

            if content:
                console.print(Rule())
                console.print(Panel.fit(content, title="✅ Final", border_style="magenta"))
                return

    # Fallback
    console.print(Rule())
    console.print(Panel.fit(_trim(str(upd)), title="Raw update", border_style="grey50"))

# Use it like:
def run_demo(question: str):
    console.print(Panel.fit(f"Q: {question}", title="🤖 Agent session"))
    for upd in agent.stream({"messages": [{"role": "user", "content": question}]},{"recursion_limit": 100}, stream_mode="updates"):
        pretty_print_update_rich(upd)
    console.print(Rule(style="grey50"))
if __name__ == "__main__":
    run_demo("Please start diagnosis.")
