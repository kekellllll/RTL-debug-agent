#!/usr/bin/env python3
"""
RTL Code Debugging Agent Script
- Input buggy RTL code
- Agent analyzes and fixes bugs in one round
- Then enters free conversation mode
"""

import os
import sys
import argparse
from openai import OpenAI
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.prompt import Prompt
from rich.syntax import Syntax

console = Console()

# ============================================================================
# OpenAI API Configuration
# ============================================================================

DEFAULT_API_KEY = None  # API key should be provided via OPENAI_API_KEY environment variable or --api-key parameter

# ============================================================================
# Built-in Buggy RTL Code Example
# ============================================================================

EXAMPLE_BUGGY_RTL = """
module sequence_detector_1011 (
    input wire clk,
    input wire rst_n,
    input wire data_in,
    output reg detected
);

localparam [2:0] IDLE  = 3'b000;
localparam [2:0] S1    = 3'b001;
localparam [2:0] S10   = 3'b010;
localparam [2:0] S101  = 3'b011;
localparam [2:0] S1011 = 3'b100;

reg [2:0] state, next_state;

always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        state <= IDLE;
    else
        state <= next_state;
end

always @(*) begin
    next_state = state;
    case (state)
        IDLE: begin
            if (data_in == 1'b1)
                next_state = S1;
            else
                next_state = IDLE;
        end
        
        S1: begin
            if (data_in == 1'b0)
                next_state = S10;
            else
                next_state = S1;
        end
        
        S10: begin
            if (data_in == 1'b1)
                next_state = S101;
            else
                next_state = IDLE;
        end
        
        S101: begin
            if (data_in == 1'b1)
                next_state = S1011;
            else
                next_state = S10;
        end
        
        S1011: begin
            if (data_in == 1'b1)
                next_state = IDLE;
            else
                next_state = IDLE;
        end
        
        default: next_state = IDLE;
    endcase
end

always @(posedge clk or negedge rst_n) begin
    if (!rst_n)
        detected <= 1'b0;
    else if (state == S1011)
        detected <= 1'b1;
    else
        detected <= 1'b0;
end

endmodule
"""

# ============================================================================
# System Prompt for RTL Debugging
# ============================================================================

SYSTEM_PROMPT = """You are an experienced hardware design engineer specializing in RTL code debugging and verification.

⚠️⚠️⚠️ CRITICAL REQUIREMENTS - READ THIS FIRST ⚠️⚠️⚠️

1. **MANDATORY HEADER**: Your fixed code MUST start with these two lines:
   ```
   `timescale 1ns/1ps
   `default_nettype none
   ```
   ❌ FORBIDDEN: Providing code without these directives
   ✅ REQUIRED: ALWAYS include these at the very beginning of your code

2. **MANDATORY: NEVER declare variables inside always blocks (CRITICAL - MOST COMMON ERROR)**:
   **⚠️⚠️⚠️ THIS IS THE #1 MOST COMMON ERROR THAT CAUSES COMPILATION FAILURES ⚠️⚠️⚠️**
   - ❌ FORBIDDEN: Declaring ANY variables (int, integer, logic, reg, wire, etc.) INSIDE always_comb or always_ff blocks
   - ❌ FORBIDDEN: `int remaining_bits;` inside always_comb
   - ❌ FORBIDDEN: `logic [46:0] w_div_shift;` inside always_comb
   - ❌ FORBIDDEN: `integer i;` inside always_comb
   - ❌ FORBIDDEN: `logic [31:0] temp;` inside always_comb
   - ✅ REQUIRED: ALL variables (int, integer, logic, reg, wire) MUST be declared at MODULE LEVEL (outside always blocks)
   - ✅ REQUIRED: Even if you use SystemVerilog syntax (`logic`, `always_comb`), you STILL cannot declare variables inside always blocks
   - **CRITICAL**: This rule applies to BOTH Verilog-2005 AND SystemVerilog syntax
   - **CRITICAL**: Icarus Verilog does NOT support variable declarations inside always blocks, regardless of syntax style
   - Example:
     ```systemverilog
     // ❌ WRONG - Declaring variables inside always_comb:
     always_comb begin
         int remaining_bits;  // ❌ ERROR: syntax error
         logic [46:0] w_div_shift;  // ❌ ERROR: syntax error
         remaining_bits = 24 - bit_count;
     end
     
     // ✅ CORRECT - Declare ALL variables at module level:
     module TopModule (...);
         int remaining_bits;  // ✅ Declare at module level
         logic [46:0] w_div_shift;  // ✅ Declare at module level
         logic [24:0] w_rem;  // ✅ Declare at module level
         
         always_comb begin
             // Only use variables, never declare them here
             remaining_bits = 24 - bit_count;
             w_div_shift = div_shift;
         end
     endmodule
     ```

3. **MANDATORY: Match reference module syntax style**:
   **CRITICAL**: Check the original buggy code and reference module (if visible) to determine the syntax style:
   - If the original code uses SystemVerilog syntax (`logic`, `always_comb`, `always_ff`), you MUST use SystemVerilog syntax
   - If the original code uses Verilog-2005 syntax (`wire`/`reg`, `always @(*)`), you can use either, but SystemVerilog is preferred for consistency
   - **IMPORTANT**: Using SystemVerilog syntax (`logic`, `always_comb`) ensures consistent handling of uninitialized values ('x') with reference modules that also use SystemVerilog
   
   **SystemVerilog syntax (PREFERRED when original uses it):**
   - ✅ ALLOWED: `logic` type (preferred over `wire`/`reg` for consistency)
   - ✅ ALLOWED: `parameter int` or `parameter integer` (but `parameter` without type also works)
   - ✅ ALLOWED: `always_comb` (preferred over `always @(*)` for combinational logic)
   - ✅ ALLOWED: `always_ff` (preferred over `always @(posedge clk)` for sequential logic)
   - ✅ ALLOWED: `typedef enum` (when needed)
   
   **Verilog-2005 syntax (fallback if SystemVerilog causes issues):**
   - ✅ ALLOWED: `wire` for combinational signals
   - ✅ ALLOWED: `reg` for signals assigned in always blocks
   - ✅ ALLOWED: `parameter` without type specifier: `parameter WIDTH = 8;`
   - ✅ ALLOWED: `always @(*)` for combinational logic
   - ✅ ALLOWED: `always @(posedge clk)` or `always @(negedge clk)` for sequential logic
   
   **CRITICAL NOTE**: The code will be compiled using Icarus Verilog (iverilog) with `-g2012` flag. Most SystemVerilog features are supported, but follow the Icarus Verilog compatibility rules below.

3. **MANDATORY: Preserve exact port bit widths**:
   - ❌ FORBIDDEN: Changing output bit widths (e.g., `output out` when original has `output [7:0] out`)
   - ✅ REQUIRED: Check the original port declarations and preserve them EXACTLY
   - ✅ REQUIRED: If original has `output [7:0] out`, your fixed code MUST also have `output [7:0] out`

ICARUS VERILOG COMPATIBILITY RULES (CRITICAL - MUST FOLLOW):
1. **Array Assignments - NEVER use whole-array assignment (THIS IS THE MOST COMMON ERROR):**
   - ❌ FORBIDDEN: `array_reg <= array_comb;` (even inside for loops)
   - ❌ FORBIDDEN: `for (int i = 0; i < N; i++) array_reg <= array_comb;`  ← WRONG!
   - ❌ FORBIDDEN: `for (int i = 0; i < N; i++) array_reg <= 32'd0;`  ← WRONG!
   - ✅ REQUIRED: `for (int i = 0; i < N; i++) array_reg[i] <= array_comb[i];`  ← CORRECT!
   - ✅ REQUIRED: `for (int i = 0; i < N; i++) array_reg[i] <= 32'd0;`  ← CORRECT!
   - **CRITICAL**: Even inside for loops, you MUST use array indexing [i] on the left side
   - Always use element-wise assignment: `array_reg[i] <= value;`

2. **Variable Declarations in always blocks (CRITICAL - COMMON ERROR - REPEATED FOR EMPHASIS):**
   **⚠️⚠️⚠️ THIS IS THE #1 MOST COMMON ERROR - READ CAREFULLY ⚠️⚠️⚠️**
   - ❌ FORBIDDEN: Declaring ANY variables (int, integer, logic, reg, wire, etc.) INSIDE always_comb or always_ff blocks
   - ❌ FORBIDDEN: `int remaining_bits;` inside always_comb (THIS CAUSES "syntax error" on line 97)
   - ❌ FORBIDDEN: `logic [46:0] w_div_shift;` inside always_comb (THIS CAUSES "syntax error")
   - ❌ FORBIDDEN: `integer signed_exp;` or `integer shift_amt;` inside always blocks (even at the beginning)
   - ❌ FORBIDDEN: `integer signed [9:0] exp_unb;` or `integer signed [9:0] shift_e;` inside always blocks
   - ❌ FORBIDDEN: `reg [31:0] temp;` or `wire [31:0] temp;` inside always blocks
   - ✅ REQUIRED: Declare ALL variables (int, integer, integer signed, logic, reg, wire) OUTSIDE the always block, at MODULE LEVEL
   - ✅ REQUIRED: For ALL types (int, integer, integer signed [N:0], logic [N:0], reg [N:0], wire [N:0]), ALWAYS declare at module level, NEVER inside always blocks
   - **CRITICAL**: This includes ALL variations: `int`, `integer`, `integer signed`, `integer signed [N:0]`, `logic [N:0]`, `reg [N:0]`, `wire [N:0]`
   - **CRITICAL**: This rule applies to BOTH Verilog-2005 AND SystemVerilog syntax
   - **CRITICAL**: Even if you use SystemVerilog syntax (`logic`, `always_comb`), you STILL cannot declare variables inside always blocks
   - **CRITICAL**: Icarus Verilog will show "syntax error" or "Malformed statement" if you declare variables inside always blocks
   - Example:
     ```verilog
     // ❌ WRONG - Declaring in middle of always block (using SystemVerilog syntax):
     always @(*) begin
         if (condition) begin
             integer signed_exp;  // ❌ ERROR: syntax error
             reg [31:0] temp;     // ❌ ERROR: syntax error (cannot declare in always block)
             temp = a + b;
         end
     end
     
     // ❌ WRONG - Declaring in if-else branch inside always block:
     always @(*) begin
         if (condition) begin
             // Some code
         end else begin
             reg [61:0] tmp;  // ❌ ERROR: Cannot declare variables in if-else branches either!
             tmp = some_value;
         end
     end
     
     // ❌ WRONG - Declaring integer at beginning of always block:
     always @(*) begin
         integer shift_amt;  // ❌ ERROR: Icarus Verilog doesn't support this
         shift_amt = 5;
     end
     
     // ❌ WRONG - Declaring integer signed with bit width in always block:
     always @(*) begin
         integer signed [9:0] exp_unb;  // ❌ ERROR: Even with bit width, cannot declare in always block
         exp_unb = exponent - BIAS;
     end
     
     // ❌ WRONG - Using SystemVerilog syntax (forbidden):
     always_comb begin
         logic [31:0] temp;  // ❌ ERROR: Cannot use `logic` or `always_comb` with `-g2012`
         temp = a + b;
     end
     
     // ✅ CORRECT - Declare ALL variables at module level (using Verilog-2005 syntax):
     module TopModule (...);
         reg [31:0] temp;                // ✅ Use `reg` instead of `logic`, declare at module level
         integer signed_exp;              // ✅ Declare at module level
         integer shift_amt;               // ✅ Declare at module level
         integer signed [9:0] exp_unb;    // ✅ Declare at module level (with bit width OK here)
         integer signed [9:0] shift_e;   // ✅ Declare at module level
         reg [31:0] scaled;               // ✅ Use `reg` instead of `logic`, declare at module level
         
         always @(*) begin               // ✅ Use `always @(*)` instead of `always_comb`
             // Only use variables, never declare them here
             temp = a + b;
             signed_exp = exponent - BIAS;
             shift_amt = signed_exp + 4;
             exp_unb = $signed({1'b0, exponent}) - $signed({1'b0, BIAS});
             shift_e = exp_unb - 10'sd19;
         end
     endmodule
     ```
   - **CRITICAL**: Icarus Verilog does NOT support declaring ANY variables (integer, reg, wire, etc.) inside always blocks
   - **CRITICAL**: This includes: `integer`, `integer signed`, `integer signed [N:0]`, `reg [N:0]`, `wire [N:0]`
   - **CRITICAL**: Even if the variable has a bit width like `integer signed [9:0]` or `reg [61:0]`, it MUST be declared at module level, NOT inside always blocks
   - **CRITICAL**: This applies to ALL locations inside always blocks: beginning, middle, if-else branches, case branches, for loops, etc.
   - **CRITICAL**: If you see "syntax error" or "Malformed statement" on a variable declaration line inside an always block, move that declaration to module level
   - **CRITICAL**: Use `reg` for signals assigned in always blocks, `wire` for combinational signals (NOT `logic`)

3. **Enum Type Assignments:**
   - ❌ FORBIDDEN: Implicit enum conversion: `next_state = condition ? S1 : S0;`
   - ✅ REQUIRED: Explicit type cast: `next_state = state_t'(condition ? S1 : S0);`
   - Or use if-else statements instead of ternary operators for enum assignments

4. **System Functions:**
   - ❌ NOT SUPPORTED: `$bitstoshortreal()`, `$shortrealtobits()`
   - ✅ Use: `$bitstoreal()`, `$realtobits()` (for 64-bit real) and manual conversion for 32-bit float

5. **Unpacked Arrays in Function/Task Ports:**
   - ❌ FORBIDDEN: `function logic get(input logic [31:0] arr[N-1:0]);`
   - ✅ REQUIRED: Use individual parameters or packed arrays

6. **Return Statements in Tasks:**
   - ❌ FORBIDDEN: `return;` in tasks
   - ✅ REQUIRED: Use `disable task_name;` instead

7. **Constant Selects (Dynamic Bit Selection) - CRITICAL:**
   - ❌ FORBIDDEN: `array[base - offset -: width]` in always blocks (e.g., `tmp[idx_hi -: 12]`)
   - ❌ FORBIDDEN: `array[base + offset -: width]` in always blocks (e.g., `tmp[30 + shift -: 12]`)
   - ❌ FORBIDDEN: Any bit selection with variable index in always blocks (Icarus Verilog will show "sorry: constant selects in always_* processes are not currently supported")
   - ✅ REQUIRED: Calculate index first, then use explicit bit range with fixed indices
   - Example:
     ```verilog
     // ❌ WRONG - Dynamic bit selection:
     always @(*) begin
         idx_hi = 30 + shift;
         fix_mag = tmp[idx_hi -: 12];  // ❌ ERROR: constant selects not supported
     end
     
     // ✅ CORRECT - Use explicit bit range:
     reg [7:0] idx_hi;
     always @(*) begin
         idx_hi = 30 + shift;
         // Use case statement or if-else with explicit ranges
         if (idx_hi == 41) begin
             fix_mag = tmp[41:30];
         end else if (idx_hi == 40) begin
             fix_mag = tmp[40:29];
         end else begin
             // Handle other cases or use a different approach
             fix_mag = (tmp >> (idx_hi - 11))[11:0];  // Alternative: use shift
         end
     end
     ```
   - **CRITICAL**: If you see "sorry: constant selects in always_* processes are not currently supported", you MUST rewrite the code to avoid variable-indexed bit selection

8. **Variable Lifetime Specifiers:**
   - ❌ FORBIDDEN: `automatic` keyword in function variable declarations (in some contexts)
   - ✅ REQUIRED: Declare variables at function beginning without `automatic`

9. **always_ff and always_comb:**
   - ❌ FORBIDDEN: `always_comb` and `always_ff` (not fully supported with `-g2012`)
   - ✅ REQUIRED: Use `always @(*)` for combinational logic
   - ✅ REQUIRED: Use `always @(posedge clk)` or `always @(negedge clk)` for sequential logic

10. **DO NOT define dependency modules:**
   - ❌ FORBIDDEN: Do NOT define modules like sys_arr, softmax_core, exp_core, acc_core, div_core, etc.
   - These are provided as stubs in the testbench file
   - ✅ REQUIRED: Only define the TopModule that you are fixing
   - If you see these modules in the prompt, they are dependencies that will be provided by the testbench
   - Your task is ONLY to fix the TopModule, not to implement or redefine dependency modules

11. **CRITICAL: Correct bias/sign encoding logic (for floating-point to fixed-point conversion problems):**
   - If the original code uses bias encoding (e.g., `integer_out = integer_out + BIAS` for positive, `BIAS - integer_out - 1` for negative), DO NOT change it to two's complement
   - The encoding should be applied AFTER computing the unsigned magnitude (int_mag)
   - **CORRECT ENCODING (based on mathematical analysis and testbench requirements)**:
     ```
     // First, compute unsigned magnitude (int_mag) without any encoding
     if (exponent == 0) begin
         int_mag = 0;
     end else if (exponent < BIAS) begin
         int_mag = 0;  // small values
     end else begin
         int_mag = full_mantissa[30 - shift_amt -: 8];  // normal range
     end
     
     // Then, apply encoding uniformly to ALL cases (including zero):
     if (sign == 1'b1) begin
         integer_out = BIAS - int_mag - 8'd1;  // negative
     end else begin
         integer_out = int_mag + BIAS;  // positive (including zero: 0 + 127 = 127)
     end
     ```
   - **WRONG ENCODING (do NOT use this)**:
     - ❌ Introducing "mag_rounded" or "magnitude" concepts that don't exist in the original algorithm
     - ❌ Using different formulas for zero vs non-zero: `k = BIAS + mag_rounded - 1` (wrong!)
     - ❌ For negative: `k = BIAS - mag_rounded` (wrong! should be `BIAS - int_mag - 1`)
     - ❌ Special-casing zero values: `if (int_mag == 0 && frac_mag == 0) integer_out = 0;` (this skips encoding for zero)
   - **KEY POINT**: The encoding is simple: `int_mag + BIAS` for positive, `BIAS - int_mag - 1` for negative
   - **For zero values**: `int_mag = 0`, so `integer_out = 0 + BIAS = 127` (positive) or `127 - 0 - 1 = 126` (negative)
   - **CRITICAL: Do NOT special-case zero values!** The encoding should be applied uniformly to ALL cases

12. **CRITICAL: Bit selection direction and formula (for floating-point to fixed-point conversion problems):**
   - **MATHEMATICAL REASONING**: When converting floating-point to fixed-point, understand how the binary point moves:
     - As exponent increases, the binary point shifts RIGHT (toward higher bit indices)
     - As exponent decreases, the binary point shifts LEFT (toward lower bit indices)
   - **For small values (exponent < BIAS)**: The original buggy code may use `full_mantissa[22 + (BIAS - exponent) -: 4]`
     - ❌ WRONG: `22 + shift_amt` selects bits ABOVE bit 22, which is incorrect for fractional extraction
     - ✅ CORRECT: `22 - shift_amt +: 4` where `shift_amt = BIAS - exponent` (selects bits BELOW bit 22)
   - **For normal range (exponent >= BIAS)**: Use `full_mantissa[22 - shift_amt -: 4]` where `shift_amt = exponent - BIAS`
     - ❌ WRONG: `full_mantissa[22 + shift_amt +: 4]` (wrong sign and direction)
     - ✅ CORRECT: `full_mantissa[22 - shift_amt -: 4]` (selects bits going DOWN from 22-shift_amt)
   - **CRITICAL**: Always verify your bit selection formula by analyzing the mathematical relationship between exponent and bit positions
   - **CRITICAL**: Icarus Verilog DOES support `full_mantissa[30 - shift_amt -: 8]` syntax when `shift_amt` is declared as `int` or `integer` at module level

Your tasks are:
1. **Carefully analyze RTL code** - Understand module functionality, state machines, data paths, and control logic
2. **Identify potential bugs** - Check for logic errors, timing issues, and boundary conditions
3. **Provide fix solutions** - Give specific code modification suggestions and corrected code that MUST comply with Icarus Verilog compatibility rules
4. **Explain reasoning process** - Detail why bugs exist and how to fix them

Please respond in English, keeping it professional and detailed. When analyzing:
- Understand the expected functionality of the code
- Check if state transition logic is correct
- Check if output logic is correct
- Consider boundary cases and abnormal inputs
- **CRITICAL: Before providing fixed code, review it for ALL Icarus Verilog compatibility rules above**
- Provide clear fixed code that will compile with Icarus Verilog

When providing fixed code:
- Wrap code in ```systemverilog code blocks (use SystemVerilog syntax if original code uses it, otherwise either is fine)
- **CRITICAL CHECKLIST - Review your code for these common errors (CHECK EVERY ITEM BEFORE SUBMITTING):**
  1. ✅ **MANDATORY HEADER**: Code starts with `timescale 1ns/1ps` and `default_nettype none` (MUST be first two lines)
  2. ✅ **MANDATORY: NO variable declarations in always blocks**: Check EVERY always_comb and always_ff block - if you see `int`, `integer`, `logic`, `reg`, or `wire` declarations inside them, MOVE THEM TO MODULE LEVEL (THIS IS THE #1 MOST COMMON ERROR)
  3. ✅ **MANDATORY: Syntax style consistency**: If original code uses SystemVerilog (`logic`, `always_comb`), use SystemVerilog for consistency with reference modules (ensures consistent handling of uninitialized values 'x')
  4. ✅ **MANDATORY: Port bit widths**: Check original port declarations and preserve them EXACTLY (e.g., `output [7:0] out` must stay `output [7:0] out`, NOT `output out`)
  5. ✅ ALL array assignments use element-wise indexing: `array[i] <= value;` NOT `array <= value;`
  6. ✅ ALL for loops with arrays use indexing: `for (i=0; i<N; i++) array[i] <= ...;` NOT `array <= ...;`
  7. ✅ ALL variable declarations (integer, int, etc.) are OUTSIDE always blocks, at module level
  8. ✅ NO variable declarations inside always blocks (even at the beginning)
  9. ✅ ALL enum assignments use explicit type casts: `state_t'(value)` (or use `localparam` instead of `typedef enum`)
  10. ✅ DO NOT define dependency modules (sys_arr, softmax_core, etc.) - only define TopModule
  11. ✅ **For bit selection with variable indices**: Add boundary checks (e.g., `if (shift_amt <= 22) begin ... end else begin frac_true = 4'd0; end`)
  12. ✅ For bias encoding problems: Do NOT special-case zero values, apply encoding uniformly to ALL cases
  13. ✅ For bit selection: Verify the mathematical relationship between exponent and bit positions
- Test your code mentally against all Icarus Verilog rules before submitting
"""

# ============================================================================
# RTL Debug Agent
# ============================================================================

class RTLDebugAgent:
    def __init__(self, api_key: str = None, model: str = "gpt-4o"):
        """Initialize Agent"""
        # Priority: parameter > environment variable > default key
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or DEFAULT_API_KEY
        if not self.api_key:
            raise ValueError("Please set OPENAI_API_KEY environment variable or pass it as parameter")
        
        self.client = OpenAI(api_key=self.api_key)
        self.model = model
        self.messages = [
            {"role": "system", "content": SYSTEM_PROMPT}
        ]
        self.analysis_complete = False
    
    def analyze_rtl_code(self, rtl_code: str, file_path: str = None):
        """Analyze RTL code (first round)"""
        file_info = f"\nFile path: {file_path}\n" if file_path else ""
        
        user_message = f"""Please help me analyze and debug the following RTL code. This is a buggy code, please:

1. Analyze the code's functionality and expected behavior
2. Identify bugs in the code
3. Explain the cause of the bugs
4. Provide the complete fixed code

{file_info}
## RTL Code:
```systemverilog
{rtl_code}
```

Please complete all the above tasks in one round of analysis, providing detailed analysis and fix solutions."""
        
        self.messages.append({"role": "user", "content": user_message})
        
        console.print("\n[bold cyan]🤖 Agent is analyzing RTL code...[/bold cyan]\n")
        
        try:
            # gpt-5.1 uses max_completion_tokens instead of max_tokens
            api_params = {
                "model": self.model,
                "messages": self.messages,
                "temperature": 0.3
            }
            if "gpt-5" in self.model.lower():
                api_params["max_completion_tokens"] = 4000
            else:
                api_params["max_tokens"] = 4000
            
            response = self.client.chat.completions.create(**api_params)
            
            assistant_msg = response.choices[0].message.content
            if assistant_msg is None:
                error_msg = "API returned None content. This may indicate an API error or incomplete response."
                console.print(f"[red]Warning: {error_msg}[/red]")
                assistant_msg = error_msg
            
            self.messages.append({"role": "assistant", "content": assistant_msg})
            self.analysis_complete = True
            
            return assistant_msg
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise
    
    def chat(self, user_input: str):
        """Free conversation mode"""
        self.messages.append({"role": "user", "content": user_input})
        
        try:
            # gpt-5.1 uses max_completion_tokens instead of max_tokens
            api_params = {
                "model": self.model,
                "messages": self.messages,
                "temperature": 0.7
            }
            if "gpt-5" in self.model.lower():
                api_params["max_completion_tokens"] = 2000
            else:
                api_params["max_tokens"] = 2000
            
            response = self.client.chat.completions.create(**api_params)
            
            assistant_msg = response.choices[0].message.content
            if assistant_msg is None:
                error_msg = "API returned None content. This may indicate an API error or incomplete response."
                console.print(f"[red]Warning: {error_msg}[/red]")
                assistant_msg = error_msg
            
            self.messages.append({"role": "assistant", "content": assistant_msg})
            
            return assistant_msg
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            raise

# ============================================================================
# Main Functions
# ============================================================================

def read_rtl_file(file_path: str) -> str:
    """Read RTL file"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        console.print(f"[red]Error: File not found: {file_path}[/red]")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error: Failed to read file: {e}[/red]")
        sys.exit(1)

def display_analysis(analysis: str):
    """Display analysis results"""
    console.print(Panel(
        Markdown(analysis),
        title="🔍 RTL Code Analysis and Fix",
        border_style="green",
        padding=(1, 2)
    ))

def display_response(response: str):
    """Display conversation response"""
    console.print(Panel(
        Markdown(response),
        title="💬 Agent Response",
        border_style="blue",
        padding=(1, 2)
    ))

def display_rtl_code(code: str, title: str = "RTL Code"):
    """Display RTL code"""
    console.print(Panel(
        Syntax(code, "systemverilog", theme="monokai", line_numbers=True),
        title=title,
        border_style="yellow"
    ))

def run_debug_session(rtl_code: str, code_source: str = "Built-in Example", api_key: str = None, model: str = "gpt-4o", interactive: bool = True):
    """Run debug session"""
    # Display title
    if interactive:
        console.print(Panel.fit(
            "[bold cyan]RTL Code Debugging Agent[/bold cyan]\n"
            "RTL code analysis and bug fixing using OpenAI API",
            border_style="cyan"
        ))
        console.print()
    
    # Display code source
    console.print(f"[dim]RTL code source: {code_source}[/dim]")
    
    # Display original code
    console.print("\n[bold yellow]═══ Original RTL Code ═══[/bold yellow]")
    display_rtl_code(rtl_code, f"Original Code: {code_source}")
    
    # Initialize Agent
    try:
        agent = RTLDebugAgent(api_key=api_key, model=model)
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        console.print("Please run: export OPENAI_API_KEY='your-api-key'")
        sys.exit(1)
    
    # First round: analysis and bug fixing
    console.print("\n[bold yellow]═══ Round 1: Agent Analysis and Bug Fixing ═══[/bold yellow]")
    try:
        analysis = agent.analyze_rtl_code(rtl_code, code_source if code_source != "Built-in Example" else None)
        if interactive:
            display_analysis(analysis)
        else:
            console.print("[dim]Analysis completed (batch mode)[/dim]")
    except Exception as e:
        console.print(f"[red]Analysis failed: {e}[/red]")
        fail_msg = f"Analysis failed: {e}"
        if not interactive:
            return fail_msg
        sys.exit(1)
    
    # Enter free conversation mode
    if not interactive:
        return analysis
    
    console.print("\n[bold green]═══ Entering Free Conversation Mode ═══[/bold green]")
    console.print("[dim]You can continue asking questions, type 'quit' or 'exit' to exit[/dim]\n")
    
    while True:
        try:
            user_input = Prompt.ask("\n[cyan]Your question[/cyan]")
            
            if user_input.lower() in ['quit', 'exit', 'q']:
                console.print("\n[yellow]Conversation ended. Goodbye![/yellow]")
                break
            
            if not user_input.strip():
                continue
            
            console.print("\n[dim]Agent is thinking...[/dim]")
            response = agent.chat(user_input)
            display_response(response)
            
        except KeyboardInterrupt:
            console.print("\n\n[yellow]Conversation interrupted. Goodbye![/yellow]")
            break
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")

# ============================================================================
# Command Line Interface
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="RTL Code Debugging Agent - Analyze and fix RTL code using OpenAI API",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --use-example                    # Use built-in example buggy code
  %(prog)s seqdet_101_buggy.sv              # Read from file
  %(prog)s -m gpt-4o llm-debug-sv/adder4_carry_buggy.sv
  %(prog)s --api-key sk-xxx --use-example
        """
    )
    
    parser.add_argument(
        "rtl_file",
        nargs="?",
        default=None,
        help="Path to buggy RTL code file (optional, mutually exclusive with --use-example)"
    )
    
    parser.add_argument(
        "--use-example",
        action="store_true",
        help="Use built-in example buggy RTL code (default if no file path is specified)"
    )
    
    parser.add_argument(
        "-m", "--model",
        default="gpt-4o",
        help="OpenAI model name (default: gpt-4o)"
    )
    
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (can also be set via OPENAI_API_KEY environment variable)"
    )
    
    parser.add_argument(
        "--batch",
        action="store_true",
        help="Batch mode: analyze and exit without interactive conversation"
    )
    
    parser.add_argument(
        "--output",
        default=None,
        help="Output file for batch mode results"
    )
    
    args = parser.parse_args()
    
    # Determine which input method to use
    if args.use_example and args.rtl_file:
        console.print("[red]Error: --use-example and file path cannot be specified together[/red]")
        sys.exit(1)
    
    if args.use_example or (args.rtl_file is None):
        # Use built-in example code
        rtl_code = EXAMPLE_BUGGY_RTL
        code_source = "Built-in Example (sequence_detector_1011)"
    else:
        # Read from file
        if not os.path.exists(args.rtl_file):
            console.print(f"[red]Error: File not found: {args.rtl_file}[/red]")
            sys.exit(1)
        rtl_code = read_rtl_file(args.rtl_file)
        code_source = args.rtl_file
    
    # Run debug session
    analysis = run_debug_session(
        rtl_code=rtl_code,
        code_source=code_source,
        api_key=args.api_key,
        model=args.model,
        interactive=not args.batch
    )
    
    # Save output if in batch mode
    if args.batch and args.output:
        from rich.markdown import Markdown
        # Ensure analysis is a string, use empty string as fallback
        if isinstance(analysis, str) and len(analysis.strip()) > 0:
            text_to_write = analysis
        else:
            # If analysis is None or empty, write a placeholder message
            text_to_write = f"Analysis completed but content was empty or None.\n\nThis may indicate:\n1. API returned empty response\n2. Analysis was not properly captured\n\nPlease check the debug output for more details."
            console.print(f"[yellow]Warning: Analysis content is empty, writing placeholder to {args.output}[/yellow]")
        
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(text_to_write)
        console.print(f"\n[green]Analysis saved to: {args.output}[/green]")

    if isinstance(analysis, str) and analysis.lower().startswith("analysis failed"):
        sys.exit(1)

if __name__ == "__main__":
    main()

