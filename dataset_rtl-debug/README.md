# RTL Debug Dataset

This dataset is designed to evaluate the debugging capabilities of Large Language Models (LLMs) on Verilog RTL code. The task presents buggy Verilog code to the LLM and requires it to identify and fix the bugs.

## Dataset Structure

Each problem in the dataset consists of:

- **`ProbXXX_name_prompt.txt`**: Contains the buggy Verilog code and instructions for debugging
- **`ProbXXX_name_ref.sv`**: The correct reference implementation
- **`ProbXXX_name_test.sv`**: Testbench to verify correctness

## Bug Types

The dataset includes various types of bugs:

1. **Bitwidth Mismatches**: Output width doesn't match the required specification
2. **Missing reg/logic Declarations**: Signals used in procedural blocks without proper declaration
3. **Combinational Logic Bugs**: Missing default assignments causing latches
4. **Logical Errors**: Incorrect operators or expressions
5. **FSM Bugs**: State machine transition or output logic errors

## Current Problems

1. **Prob001_mux_bitwidth_debug**: 8-bit mux with output width bug
2. **Prob002_counter_reset_debug**: Counter with missing reg declaration for output
3. **Prob003_fsm_logic_debug**: FSM with missing default assignment in combinational logic

## Usage

### Basic Usage

```bash
# Set up iverilog path (if needed)
export PATH="/path/to/iverilog:$PATH"

# Create build directory
mkdir -p build-rtl-debug
cd build-rtl-debug

# Configure for rtl-debug task
../configure \
  --with-task=rtl-debug \
  --with-model=gpt-4 \
  --with-samples=20 \
  --with-temperature=0.8

# Set your API key
export OPENAI_API_KEY='your-api-key-here'

# Run evaluation
make -j4

# View results
cat summary.txt
```

### Example Output Format

The LLM is expected to return corrected Verilog code enclosed in `[BEGIN]` and `[DONE]` markers:

```verilog
[BEGIN]
module TopModule (
    input        sel,
    input  [7:0] a,
    input  [7:0] b,
    output [7:0] out
);

    assign out = sel ? a : b;

endmodule
[DONE]
```

### Evaluation Metrics

The evaluation computes:
- **Pass@k**: Percentage of problems where at least one of k samples passes all tests
- **Syntax Error Rate**: Percentage of samples with Verilog syntax errors
- **Compilation Error Rate**: Percentage of samples that fail iverilog compilation
- **Functional Error Rate**: Percentage of samples that compile but fail tests

## Adding New Problems

To add a new debugging problem:

1. Create three files:
   - `ProbXXX_name_prompt.txt`: Buggy code + debugging instructions
   - `ProbXXX_name_ref.sv`: Correct implementation
   - `ProbXXX_name_test.sv`: Testbench

2. Add the problem name to `problems.txt`:
   ```
   ProbXXX_name
   ```

3. Follow the naming convention: `ProbXXX_descriptive_name_debug`

### Template for Prompt File

```text
The following Verilog module has one or more bugs. Please identify and fix all bugs:

module TopModule (
    // ... buggy code here ...
);

    // ... buggy implementation ...

endmodule

Debug this code and provide a corrected implementation. [Brief description of intended functionality].
```

### Template for Reference File

```verilog
module RefModule (
    // ... correct interface ...
);

    // ... correct implementation ...

endmodule
```

## Comparison with Other Tasks

| Task | Input | Output | Focus |
|------|-------|--------|-------|
| **code-complete** | Spec + Interface | Complete implementation | Code generation |
| **spec-to-rtl** | Functional description | Complete module | RTL design |
| **rtl-debug** | Buggy code | Fixed code | Bug identification & fixing |

## Future Enhancements

Potential improvements for this dataset:

1. **Bug Difficulty Levels**: Easy, Medium, Hard
2. **Multiple Bugs**: Problems with multiple independent bugs
3. **Bug Categories**: Syntax, Logic, Timing, Synthesis-related
4. **Bug Explanations**: Require LLM to explain what was wrong
5. **Partial Credit**: Award points for identifying bugs even if fix is incomplete

## Citation

If you use this dataset, please cite:

```bibtex
@misc{verilogeval-rtl-debug,
  title={VerilogEval RTL Debug Extension},
  year={2024},
  note={Extension to VerilogEval for evaluating RTL debugging capabilities}
}
```

Also cite the original VerilogEval papers as described in the main README.

