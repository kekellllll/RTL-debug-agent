# RTL Debug Agent Project Documentation

## Table of Contents
1. [Project Overview](#project-overview)
2. [Test Baseline](#test-baseline)
3. [Test Full Agent](#test-full-agent)
4. [Full Agent Usage](#full-agent-usage)
5. [Tool Logic Summary](#tool-logic-summary)

---

## Project Overview

This project implements an AI-powered RTL (Register Transfer Level) debugging agent that can automatically identify and fix bugs in SystemVerilog code. The project includes two main testing approaches:

- **Baseline Agent**: Simple LLM-based agent without tools (for comparison)
- **Full Agent**: Advanced agent with multiple analysis and verification tools

The dataset contains 8 RTL debugging problems (`Prob001` through `Prob008`) covering various bug types:
- Bit width mismatches
- Counter reset logic
- FSM logic errors
- FPU operations
- Softmax core
- DLA (Deep Learning Accelerator)
- Floating-point to fixed-point conversion
- Multi-cycle divider

---

## Test Baseline

### Overview
The baseline agent (`test_dataset_baseline.py`) uses a simple LLM-based approach without any tools or post-processing. It serves as a baseline for comparison.

### Key Characteristics
- **No tools**: Agent only uses LLM to analyze and fix code
- **No post-processing**: Code is used as-is from the agent output
- **No iterative debugging**: Single-pass analysis
- **Failures count as failures**: No automatic fixes or retries

### Usage

#### Command Line
```bash
./run_baseline.sh [--model MODEL] [--api-key KEY]
```

#### Environment Variables
```bash
export OPENAI_API_KEY="your-api-key"
export MODEL="gpt-4o"  # Optional, defaults to gpt-4o
```

#### Example
```bash
./run_baseline.sh --model gpt-4o --api-key sk-xxx
```

### Output
- Results saved to: `logic-diagnosis-agent/test_results_baseline/`
- For each problem:
  - `{problem_name}_analysis.txt`: Agent analysis output
  - `{problem_name}_candidate.sv`: Generated fixed code
  - `{problem_name}_debug.txt`: Debug logs (stdout/stderr)

### Workflow
1. Read problem prompt from `dataset_rtl-debug/{problem_name}_prompt.txt`
2. Extract buggy RTL code from prompt
3. Call baseline agent (`rtl_debug_agent.py`) with `--batch` mode
4. Extract candidate code from agent output
5. Compile and simulate using Icarus Verilog
6. Report success/failure

### Limitations
- No automatic error detection before compilation
- No iterative refinement based on compilation/simulation errors
- No tool-assisted analysis (DFG, logic verification, etc.)
- Code must be correct on first attempt

---

## Test Full Agent

### Overview
The full agent (`test_dataset_full_agent.py`) uses the advanced `rtl_debug_agent_tooled.py` with all available tools for iterative debugging.

### Key Characteristics
- **All tools available**: DFG analysis, logic verification, test failure analysis, etc.
- **Iterative debugging**: Agent can refine code based on tool feedback
- **Post-processing**: Automatic fixes (e.g., moving variable declarations to module level)
- **Tool-assisted verification**: Uses `run_iverilog` and `simulate` tools

### Usage

#### Command Line
```bash
./run_full_agent.sh [--model MODEL] [--api-key KEY] [--max-iterations N]
```

#### Environment Variables
```bash
export OPENAI_API_KEY="your-api-key"
export MODEL="gpt-4o"  # Optional, defaults to gpt-4o
export MAX_ITERATIONS="10"  # Optional, defaults to 10
```

#### Example
```bash
./run_full_agent.sh --model gpt-4o --api-key sk-xxx --max-iterations 10
```

### Output
- Results saved to: `logic-diagnosis-agent/test_results_full/`
- For each problem:
  - `{problem_name}_analysis.txt`: Agent analysis output
  - `{problem_name}_candidate.sv`: Generated fixed code (post-processed)
  - `{problem_name}_debug.txt`: Debug logs (stdout/stderr)

### Workflow
1. Read problem prompt from `dataset_rtl-debug/{problem_name}_prompt.txt`
2. Extract buggy RTL code and requirement
3. Call full agent (`rtl_debug_agent_tooled.py`) with:
   - Testbench path: `{problem_name}_test.sv`
   - Reference path: `{problem_name}_ref.sv`
   - Max iterations: 10 (default)
4. Agent performs iterative debugging using tools
5. Extract final code from agent output
6. Post-process code (move variable declarations to module level)
7. Compile and simulate using Icarus Verilog
8. Report success/failure

### Advantages Over Baseline
- **Tool-assisted analysis**: Detects errors before compilation
- **Iterative refinement**: Can fix errors based on compilation/simulation feedback
- **Automatic post-processing**: Fixes common Icarus Verilog compatibility issues
- **Better error diagnosis**: Uses DFG and failure analysis tools

---

## Full Agent Usage

### Direct Usage

#### Command Line Interface
```bash
python3 logic-diagnosis-agent/rtl_debug_agent_tooled.py \
    --rtl buggy_code.sv \
    --requirement "Fix the bugs in the RTL code" \
    --testbench test.sv \
    --ref ref.sv \
    --problem-name Prob001 \
    --max-iterations 10 \
    --model gpt-4o \
    --api-key sk-xxx
```

#### Parameters
- `--rtl`: Path to buggy RTL code file
- `--requirement`: Natural language description of what the module should do
- `--testbench`: Path to testbench file (optional, agent can generate one)
- `--ref`: Path to reference implementation (optional)
- `--problem-name`: Name of the problem (for logging)
- `--max-iterations`: Maximum number of debugging iterations (default: 10)
- `--model`: OpenAI model to use (default: gpt-4o)
- `--api-key`: OpenAI API key (can also use `OPENAI_API_KEY` env var)

#### Python API
```python
from logic_diagnosis_agent.rtl_debug_agent_tooled import run_debug_session

result = run_debug_session(
    rtl_code=buggy_code,
    requirement="Fix the bugs in the RTL code",
    testbench_path="test.sv",
    ref_path="ref.sv",
    problem_name="Prob001",
    api_key="sk-xxx",
    model="gpt-4o",
    max_iterations=10
)

if result["success"]:
    print("Fixed code:", result["final_code"])
else:
    print("Error:", result["error"])
```

### Agent Workflow

The full agent follows this iterative workflow:

1. **Initial Analysis**
   - Analyze buggy code and requirement
   - Understand what the module should do

2. **Generate Initial Fix**
   - Create a fixed version of the code
   - Follow Icarus Verilog compatibility rules

3. **Tool-Assisted Verification** (iterative)
   - **`analyze_dataflow`**: Check for unused signals or missing logic
   - **`verify_code_logic`**: Verify shift calculations, signed arithmetic, etc.
   - **`run_iverilog`**: Compile the code (automatically runs DFG analysis)
   - **`simulate`**: Run simulation (automatically analyzes failures if needed)
   - **`analyze_test_failures`**: Analyze simulation failures and suggest fixes

4. **Refinement**
   - Based on tool feedback, refine the code
   - Fix compilation errors
   - Fix simulation failures
   - Repeat until both compilation and simulation pass

5. **Final Output**
   - Return the fixed code
   - Post-process if needed (move variable declarations)

---

## Tool Logic Summary

### Tool Output Format

**Important**: All tools return **text strings (prompt format)**, NOT JSON files. The reports are formatted as human-readable text that is directly passed to the LLM through LangChain's `ToolMessage` mechanism.

#### How Tools Pass Reports to LLM

1. **Tool Function Returns String**: Each tool function (e.g., `analyze_dataflow`, `verify_code_logic`) returns a formatted string
2. **LangChain ToolMessage**: The string is wrapped in a `ToolMessage` object by LangChain
3. **Direct Text Injection**: The tool output is injected into the conversation as text, not as structured JSON
4. **LLM Receives Text**: The LLM sees the report as plain text in the conversation history

#### Example Tool Output Format

```python
# Tool function returns a string
def analyze_dataflow(rtl_code: str) -> str:
    # ... analysis logic ...
    detailed_report = "=== Data Flow Graph (DFG) Analysis ===\n\n"
    detailed_report += "⚠️  WARNINGS (Potential Logic Errors):\n"
    detailed_report += "  • Signal 'sign' is not used in output calculations\n"
    detailed_report += "    → Action: Check if sign should be used in output calculations\n"
    return detailed_report  # Returns plain text string
```

The LLM receives this as:
```
=== Data Flow Graph (DFG) Analysis ===

⚠️  WARNINGS (Potential Logic Errors):
  • Signal 'sign' is not used in output calculations
    → Action: Check if sign should be used in output calculations
```

#### Why Text Format (Not JSON)?

- **Natural Language Processing**: LLMs are optimized for natural language text
- **Readability**: Human-readable format is easier for the LLM to understand and reason about
- **Flexibility**: Text format allows for rich formatting (emojis, bullet points, code blocks)
- **Simplicity**: No need for JSON parsing - direct text injection is more efficient

---

### 1. DFG (Data Flow Graph) Analysis

#### Purpose
Detect potential logic errors by analyzing signal dependencies and usage.

#### Implementation Priority
1. **`pyverilog_dfg_analyzer.py`** (most accurate)
   - Uses pyverilog library to parse SystemVerilog AST
   - Extracts signals, assignments, and conditions from AST
   - Builds dependency graph: `{signal: {used_signals}}`

2. **`ast_based_dfg_analyzer.py`** (fallback)
   - Uses custom recursive descent parser
   - Similar logic to pyverilog version

3. **`simple_dfg_analyzer.py`** (regex fallback)
   - Uses regular expressions to extract signals and assignments
   - Less accurate but more robust

#### DFG Generation Process
1. **Extract Signals**: Find all signal declarations (logic, reg, wire, integer, etc.)
2. **Extract Assignments**: Find all assignments (`variable = expression`)
3. **Extract Conditions**: Find all conditional expressions (if, case, while)
4. **Build DFG**: For each signal, find which other signals it depends on
   - From assignments: `lhs` depends on signals used in `rhs`
   - From conditions: Outputs depend on signals used in conditions
5. **Check Key Signals**: Verify that key signals (sign, reset, enable, etc.) are used in outputs
6. **Check Unused Signals**: Identify signals that are declared but never used

#### Warnings Generated
- **Unused key signal**: Key signal exists but not used in output calculations
  - Example: `sign` signal exists but doesn't affect `integer_out`
  - Indicates missing sign handling logic
- **Unused signals**: Signals declared but never referenced

#### Tool: `analyze_dataflow`
- **Input**: Complete SystemVerilog module code
- **Output**: DFG analysis report with warnings
- **Usage**: Call before compilation to catch logic errors early

---

### 2. Logic Verification (`verify_code_logic`)

#### Purpose
Verify common logic issues in RTL code before compilation.

#### Verification Functions

##### `verify_shift_calculation`
- **Checks**: Shift calculation formulas
- **Patterns**: Looks for `shift_amt` or similar variables
- **Issues Detected**:
  - Wrong formula: `19 - e_unbiased` (should be `BIAS - exponent`)
  - Correct formula: `BIAS - exponent`

##### `verify_exponent_zero_handling`
- **Checks**: Handling of `exponent == 0` case
- **Issues Detected**:
  - Missing `exponent == 0` check
  - Sign encoding applied after `exponent == 0` block incorrectly

##### `verify_signed_arithmetic`
- **Checks**: Use of signed arithmetic
- **Issues Detected**:
  - Unsigned variables used in subtraction that may be negative
  - Example: `logic [7:0] E = exponent - BIAS` (if `exponent < BIAS`, E becomes large positive number)
  - Suggestion: Use `integer` type for signed arithmetic

#### Tool: `verify_code_logic`
- **Input**: RTL code string
- **Output**: Verification report with issues and suggestions
- **Usage**: Call before `run_iverilog` to catch logic errors early

---

### 3. Test Failure Analysis (`analyze_test_failures`)

#### Purpose
Analyze simulation failures to identify patterns and suggest fixes.

#### Analysis Process

##### 1. Parse Simulation Output
- Extract failing test cases: `Test N (value): got k=X idx=Y, exp k=A idx=B`
- Extract passing test cases: `PASS Test N`
- Parse test values (floating-point numbers, "zero", "random", etc.)

##### 2. Classify Failures
- **By value range**:
  - Zero value failures (`value == 0`)
  - Small value failures (`0 < value < 1.0`)
  - Normal value failures (`1 <= value < 256`)
  - Large value failures (`value >= 256`)
- **By error type**:
  - Only `k` (integer_out) mismatches
  - Only `idx` (frac_out) mismatches
  - Both `k` and `idx` mismatch
- **By special patterns**:
  - `got_k == 127` (BIAS) → Encoding applied to zero incorrectly
  - `got_k == 0` but `exp_k != 0` → Small value handling error
  - `got_k == 255` → Saturation handling error
  - `got_k == 126` (near BIAS) → Encoding applied to small values incorrectly

##### 3. Generate Fix Suggestions
Based on failure patterns, provides specific fix suggestions:

- **Small value wrong k**: Encoding applied incorrectly to values < 1.0
  - Issue: `integer_out = 0 + BIAS = 127` for small values
  - Fix: Check `integer_part == 0` FIRST, not `(integer_part == 0 && fractional_part == 0)`
  
- **Got k equals bias**: Zero values encoded to BIAS
  - Issue: Encoding step executes even when `int_mag = 0`
  - Fix: Add zero-check in BOTH positive and negative encoding branches

- **Got k equals 255**: Incorrect saturation
  - Issue: Values incorrectly saturated
  - Fix: Check signed arithmetic (use `integer` type)

- **Idx mismatch only**: Fractional part calculation incorrect
  - Issue: Wrong bit selection or shift operations
  - Fix: Verify `shift_amt` calculation and bit selection

#### Tool: `analyze_test_failures`
- **Input**: Simulation output string
- **Output**: Failure analysis report with patterns and fix suggestions
- **Usage**: Call after simulation fails (automatically called by `simulate` tool)

---

### 4. Compilation Tool (`run_iverilog`)

#### Purpose
Compile RTL code using Icarus Verilog.

#### Features
- **Automatic DFG Analysis**: Runs DFG analysis before compilation
- **Enhanced Error Messages**: Provides suggestions for common errors
- **State Cast Fixes**: Automatically fixes enum type assignments

#### Process
1. Run DFG analysis (if available)
2. Apply state_t cast fixes
3. Create temporary file for candidate RTL
4. Build compilation command with testbench and reference (if needed)
5. Run `iverilog` compiler
6. Return compilation result with binary path or error message

#### Output
- **Success**: `COMPILATION SUCCESS\nBinary created at: <path>`
- **Failure**: `COMPILATION ERROR: <error details>` with suggestions

#### Common Error Handling
- **Variable declaration in always block**: Suggests moving to module level
- **Syntax errors**: Provides line numbers and likely causes
- **Type casting**: Suggests explicit enum casts

---

### 5. Simulation Tool (`simulate`)

#### Purpose
Run simulation using Icarus Verilog's `vvp` simulator.

#### Features
- **Automatic Failure Analysis**: If simulation fails, automatically calls `analyze_test_failures`
- **Timeout Protection**: 60-second timeout per simulation
- **Output Parsing**: Extracts pass/fail information

#### Process
1. Run `vvp` simulator with binary path
2. Parse simulation output
3. Check for "SIMULATION PASSED" or "SIMULATION FAILED"
4. If failed, automatically call `analyze_test_failures` tool
5. Return simulation result with failure analysis (if applicable)

#### Output
- **Success**: `SIMULATION PASSED\n<statistics>`
- **Failure**: `SIMULATION FAILED\n<failure details>\n\n=== TEST FAILURE ANALYSIS ===\n<analysis report>`

---

### 6. Testbench Generation Tool (`generate_testbench`)

#### Purpose
Generate testbench from specification or test vectors.

#### Methods

##### Method 1: Expected Formula
- **Input**: Verilog expression (e.g., `"sel ? b : a"`)
- **Process**: Generate testbench that validates output matches formula
- **Use case**: When you know the expected behavior as a formula

##### Method 2: Test Vectors
- **Input**: JSON array of test vectors
  ```json
  [{"inputs": {"sel": 0, "a": 170, "b": 187}, "expected_outputs": {"out": 170}}, ...]
  ```
- **Process**: 
  1. Try to infer formula from test vectors
  2. If inference succeeds, generate testbench with formula
  3. If inference fails, generate testbench with explicit test vectors
- **Use case**: When you have input-output pairs but no formula

#### Formula Inference
The tool attempts to infer formulas from test vectors:
- **Mux pattern**: If `sel=0 -> out=a, sel=1 -> out=b`, infers `sel ? b : a`
- **Other patterns**: Tries to identify common logic patterns

#### Output
- Path to generated testbench file (`.sv`)
- Or error message with hints if generation fails

---

## Tool Integration

### Automatic Tool Calls

#### In `run_iverilog`
- Automatically runs DFG analysis before compilation
- DFG warnings are included in compilation output

#### In `simulate`
- Automatically calls `analyze_test_failures` if simulation fails
- Failure analysis is included in simulation output

### Tool Workflow Recommendation

1. **Generate initial fix**
2. **Call `analyze_dataflow`**: Check for unused signals or missing logic
3. **Call `verify_code_logic`**: Check for common logic errors
4. **Call `run_iverilog`**: Compile (automatically runs DFG)
5. **If compilation succeeds**: Extract binary path
6. **Call `simulate`**: Run simulation (automatically analyzes failures if needed)
7. **If simulation fails**: Use `analyze_test_failures` suggestions to fix
8. **Repeat** until both compilation and simulation pass

---

## Key Differences: Baseline vs Full Agent

| Feature | Baseline Agent | Full Agent |
|---------|---------------|------------|
| **Tools** | None | All tools available |
| **DFG Analysis** | No | Yes (automatic in `run_iverilog`) |
| **Logic Verification** | No | Yes (`verify_code_logic`) |
| **Failure Analysis** | No | Yes (automatic in `simulate`) |
| **Iterative Debugging** | No | Yes (up to max_iterations) |
| **Post-processing** | No | Yes (variable declarations) |
| **Error Recovery** | No | Yes (can fix based on tool feedback) |
| **Timeout** | 10 minutes | 15 minutes |
| **Success Rate** | Lower | Higher |

---

## Dataset Structure

```
dataset_rtl-debug/
├── Prob001_mux_bitwidth_debug_prompt.txt    # Problem description + buggy code
├── Prob001_mux_bitwidth_debug_test.sv      # Testbench
├── Prob001_mux_bitwidth_debug_ref.sv       # Reference implementation
├── Prob002_counter_reset_debug_prompt.txt
├── Prob002_counter_reset_debug_test.sv
├── Prob002_counter_reset_debug_ref.sv
├── ... (Prob003 through Prob008)
└── problems.txt                             # List of problem names
```

---

## Environment Setup

### Required Tools
- **Python 3.8+**
- **Icarus Verilog** (`iverilog`, `vvp`)
- **OpenAI API Key**

### Python Dependencies
```bash
pip install openai langchain langchain-openai rich pyverilog
```

### Environment Variables
```bash
export OPENAI_API_KEY="your-api-key"
export MODEL="gpt-4o"  # Optional
export MAX_ITERATIONS="10"  # Optional (for full agent)
```

---

## Output Directories

### Baseline Results
- **Location**: `logic-diagnosis-agent/test_results_baseline/`
- **Files per problem**:
  - `{problem}_analysis.txt`: Agent output
  - `{problem}_candidate.sv`: Generated code
  - `{problem}_debug.txt`: Debug logs

### Full Agent Results
- **Location**: `logic-diagnosis-agent/test_results_full/`
- **Files per problem**:
  - `{problem}_analysis.txt`: Agent output
  - `{problem}_candidate.sv`: Generated code (post-processed)
  - `{problem}_debug.txt`: Debug logs

---

## Best Practices

### For Baseline Testing
1. Use simple, straightforward prompts
2. Expect lower success rates
3. Useful for comparing LLM capabilities without tools

### For Full Agent Testing
1. Provide clear requirement descriptions
2. Include testbench if available (or let agent generate one)
3. Set appropriate `max_iterations` (10 is usually sufficient)
4. Monitor tool usage to understand agent behavior
5. Review failure analysis reports for debugging insights

### For Tool Usage
1. **Always call `analyze_dataflow` first** after generating initial fix
2. **Call `verify_code_logic`** before compilation to catch logic errors
3. **Use `analyze_test_failures`** when simulation fails (automatic)
4. **Follow tool suggestions** - they're based on failure patterns
5. **Don't ignore DFG warnings** - they often indicate missing logic

---

## Troubleshooting

### Common Issues

#### API Rate Limits
- **Symptom**: 429 errors or rate limit messages
- **Solution**: Add delays between problems, use different API key, or reduce `max_iterations`

#### Compilation Errors
- **Symptom**: "syntax error" or "malformed statement"
- **Solution**: Check for variable declarations in always blocks, use tool suggestions

#### Simulation Failures
- **Symptom**: Most or all tests fail
- **Solution**: Use `analyze_test_failures` tool, check signed arithmetic, verify bit selection formulas

#### Empty Agent Output
- **Symptom**: Analysis file is empty
- **Solution**: Check API key, model availability, timeout settings

---

## Summary

This project provides a comprehensive framework for automated RTL debugging:

- **Baseline Agent**: Simple LLM-based approach for comparison
- **Full Agent**: Advanced tool-assisted iterative debugging
- **Multiple Tools**: DFG analysis, logic verification, failure analysis, compilation, simulation
- **Automatic Integration**: Tools work together seamlessly
- **Post-processing**: Automatic fixes for common compatibility issues

The full agent significantly improves success rates by:
1. Detecting errors before compilation
2. Providing specific fix suggestions
3. Enabling iterative refinement
4. Automatically handling common issues

