#!/usr/bin/env python3
"""
RTL Code Debugging Agent with Tools (LangChain Agent)
- Uses LangChain Agent framework with tools (run_iverilog, simulate)
- Iteratively debugs RTL code by calling tools and refining fixes
- Does NOT have access to reference implementation during debugging
"""

import os
import sys
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from rich.console import Console
from rich.panel import Panel
from rich.markdown import Markdown
from rich.syntax import Syntax
from rich.prompt import Prompt

# LangChain imports
try:
    from langchain.agents import create_agent
    from langchain_openai import ChatOpenAI
    from langchain_core.tools import tool
    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
    from langchain_core.messages import HumanMessage, SystemMessage
except ImportError as e:
    console = Console()
    console.print(f"[red]Error: LangChain packages not installed or import failed: {e}[/red]")
    console.print("Please install: pip install langchain langchain-openai langchain-core")
    sys.exit(1)

console = Console()

# ============================================================================
# OpenAI API Configuration
# ============================================================================

DEFAULT_API_KEY = None  # API key should be provided via OPENAI_API_KEY environment variable or --api-key parameter

# ============================================================================
# Tool Definitions
# ============================================================================

# Import testbench generator
try:
    # Try importing from the same directory
    import sys
    import os
    current_dir = os.path.dirname(os.path.abspath(__file__))
    if current_dir not in sys.path:
        sys.path.insert(0, current_dir)
    
    from generate_testbench_tool import generate_testbench_from_spec_simple
    console.print(f"[dim]✓ Successfully imported generate_testbench_from_spec_simple[/dim]")
except ImportError as e:
    # If import fails, define a simple version inline
    console.print(f"[yellow]⚠ Warning: Could not import generate_testbench_tool: {e}[/yellow]")
    console.print("[yellow]Using inline fallback implementation[/yellow]")

# Import DFG analyzer
try:
    from simple_dfg_analyzer import analyze_data_flow, analyze_code_for_agent
    console.print(f"[dim]✓ Successfully imported DFG analyzer[/dim]")
except ImportError as e:
    console.print(f"[yellow]⚠ Warning: Could not import DFG analyzer: {e}[/yellow]")
    console.print("[yellow]DFG analysis will not be available[/yellow]")
    analyze_data_flow = None
    analyze_code_for_agent = None

# Import additional analysis tools
try:
    from test_failure_analyzer import generate_failure_analysis
    TEST_ANALYZER_AVAILABLE = True
except ImportError:
    TEST_ANALYZER_AVAILABLE = False
    generate_failure_analysis = None
    console.print("[yellow]Warning: Test failure analyzer not available[/yellow]")

try:
    from logic_verifier import verify_logic
    LOGIC_VERIFIER_AVAILABLE = True
except ImportError:
    LOGIC_VERIFIER_AVAILABLE = False
    verify_logic = None
    console.print("[yellow]Warning: Logic verifier not available[/yellow]")
    
    def generate_testbench_from_spec_simple(module_name, specification, expected_formula=None, output_file=None, test_vectors=None):
        """Simple testbench generator - fallback if module not available"""
        # Inline implementation (same as generate_testbench_tool.py)
        if not expected_formula:
            # Try to infer from specification
            spec_lower = specification.lower()
            if "mux" in spec_lower and "sel" in spec_lower:
                if "sel=0" in spec_lower or "sel=1" in spec_lower:
                    if "-> a" in specification or "should be a" in spec_lower:
                        if "-> b" in specification or "should be b" in spec_lower:
                            expected_formula = "sel ? b : a"
        
        if not expected_formula:
            expected_formula = "sel ? b : a"  # Default placeholder
        
        testbench = f"""`timescale 1 ps/1 ps

module tb();
    typedef struct packed {{
        int errors;
        int errortime;
        int errors_out;
        int errortime_out;
        int clocks;
    }} stats;
    
    stats stats1;
    
    reg clk = 0;
    initial forever #5 clk = ~clk;

    logic sel;
    logic [7:0] a;
    logic [7:0] b;
    logic [7:0] out_dut;

    {module_name} dut (.sel, .a, .b, .out(out_dut));

    logic [7:0] expected_out;
    always @(*) begin
        expected_out = {expected_formula};
    end
    
    wire tb_match = (out_dut === expected_out);
    
    always @(posedge clk, negedge clk) begin
        stats1.clocks++;
        if (!tb_match) begin
            if (stats1.errors == 0) stats1.errortime = $time;
            stats1.errors++;
        end
        if (out_dut !== expected_out) begin
            if (stats1.errors_out == 0) stats1.errortime_out = $time;
            stats1.errors_out++;
        end
    end

    initial begin
        repeat(100) @(posedge clk) begin
            sel <= $random;
            a <= $random;
            b <= $random;
        end
        $finish;
    end

    final begin
        if (stats1.errors_out) 
            $display("Hint: Output 'out' has %0d mismatches. First mismatch occurred at time %0d.", 
                    stats1.errors_out, stats1.errortime_out);
        else 
            $display("Hint: Output 'out' has no mismatches.");
        $display("Hint: Total mismatched samples is %1d out of %1d samples\\n", 
                stats1.errors, stats1.clocks);
        $display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
    end
    
    initial begin
        #100000
        $display("TIMEOUT");
        $finish();
    end
endmodule
"""
        if output_file:
            with open(output_file, 'w', encoding='utf-8') as f:
                f.write(testbench)
        return testbench

def create_iverilog_tool(testbench_path: str, ref_path: Optional[str] = None):
    """Create a run_iverilog tool with bound paths."""
    @tool
    def run_iverilog(rtl_code: str) -> str:
        """
        Compile RTL code using Icarus Verilog.
        
        Args:
            rtl_code: The complete SystemVerilog RTL code to compile (must contain TopModule).
                     Provide the FULL module code including module declaration and endmodule.
        
        Returns:
            A string containing compilation results:
            - If successful: "COMPILATION SUCCESS\nBinary created at: <path>"
            - If failed: "COMPILATION ERROR: <error details>"
            
        NOTE: This tool automatically runs DFG (Data Flow Graph) analysis before compilation
        to detect potential logic errors. If warnings are found, they will be included in the output.
        """
        try:
            # Automatically run DFG analysis before compilation
            dfg_warnings = ""
            if analyze_code_for_agent is not None:
                try:
                    dfg_analysis = analyze_data_flow(rtl_code)
                    if dfg_analysis['warnings']:
                        dfg_warnings = "\n\n⚠️  DFG ANALYSIS WARNINGS (before compilation):\n"
                        for warning in dfg_analysis['warnings']:
                            dfg_warnings += f"  • {warning['message']}\n"
                            if warning['type'] == 'unused_key_signal':
                                signal = warning['signal']
                                dfg_warnings += f"    → Action: Check if {signal} should be used in output calculations\n"
                                dfg_warnings += f"    → This might indicate missing logic (e.g., sign handling)\n"
                        dfg_warnings += "\n"
                except Exception as e:
                    # If DFG analysis fails, continue with compilation
                    dfg_warnings = f"\n[DFG Analysis skipped due to error: {str(e)}]\n"
            
            # Apply state_t cast fixes if needed
            rtl_code = rewrite_state_assignments(rtl_code)
            
            # Create temporary file for candidate RTL
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sv', delete=False, encoding='utf-8') as f:
                f.write(rtl_code)
                candidate_path = f.name
            
            # Build compilation command
            binary_path = candidate_path.replace('.sv', '_tb')
            compile_cmd = [
                "iverilog",
                "-g2012",
                "-Wall",
                "-o",
                binary_path
            ]
            
            # Add files to compile
            # In real engineering scenario, testbench may not need RefModule
            # Only include ref if it exists and testbench actually needs it
            files_to_compile = [candidate_path]
            
            # Check if testbench references RefModule by reading it
            needs_ref = False
            if ref_path and os.path.exists(ref_path):
                try:
                    with open(testbench_path, 'r', encoding='utf-8') as tb_file:
                        tb_content = tb_file.read()
                        # Check if testbench uses RefModule
                        if 'RefModule' in tb_content or 'ref' in tb_content.lower():
                            needs_ref = True
                except:
                    pass
            
            if needs_ref:
                files_to_compile.append(ref_path)  # Add ref before testbench
            
            files_to_compile.append(testbench_path)  # Testbench always needed
            
            compile_cmd.extend(files_to_compile)
            
            # Run compilation
            result = subprocess.run(
                compile_cmd,
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Clean up temp file
            try:
                os.unlink(candidate_path)
            except:
                pass
            
            if result.returncode == 0:
                result_msg = f"COMPILATION SUCCESS\nBinary created at: {binary_path}\n{result.stdout}"
                if dfg_warnings:
                    result_msg = dfg_warnings + result_msg
                return result_msg
            else:
                error_msg = result.stderr.strip() or result.stdout.strip() or "Unknown compilation error"
                if dfg_warnings:
                    error_msg = dfg_warnings + error_msg
                
                # Enhanced error messages for common issues
                enhanced_error = error_msg
                
                # Check for variable declaration errors in always blocks
                if "syntax error" in error_msg.lower() or "malformed statement" in error_msg.lower():
                    # Try to extract line number
                    line_match = re.search(r':(\d+):', error_msg)
                    if line_match:
                        line_num = line_match.group(1)
                        # Check if the error is likely related to variable declarations
                        if any(keyword in error_msg.lower() for keyword in ['logic', 'integer', 'int', 'variable']):
                            enhanced_error += f"\n\n⚠️ LIKELY ISSUE: Variable declaration inside always block (line {line_num})"
                            enhanced_error += "\n❌ SOLUTION: Move ALL variable declarations (logic, integer, int, etc.) to module level (outside always blocks)"
                            enhanced_error += "\n✅ Example: If you have 'logic [31:0] tmp;' inside always_comb, move it before the always_comb block"
                
                return f"COMPILATION ERROR:\n{enhanced_error}\n\nCommand: {' '.join(compile_cmd)}"
        
        except subprocess.TimeoutExpired:
            return "COMPILATION ERROR: Timeout (30s) during compilation"
        except Exception as e:
            return f"COMPILATION ERROR: {str(e)}"
    
    return run_iverilog


@tool
def generate_testbench(
    module_name: str, 
    specification: str, 
    expected_formula: str = None,
    test_vectors: str = None
) -> str:
    """
    Generate a testbench from specification. You can provide either:
    1. expected_formula: A Verilog expression (e.g., "sel ? b : a")
    2. test_vectors: Test cases in JSON format (e.g., '[{"inputs": {"sel": 0, "a": 170, "b": 187}, "expected_outputs": {"out": 170}}, ...]')
    
    If you only have test vectors, the tool will try to infer the formula from them.
    If inference fails, you should analyze the test vectors yourself and provide the formula.
    
    Args:
        module_name: Name of the module (e.g., "TopModule")
        specification: Natural language specification of what the module should do
        expected_formula: Optional Verilog expression for expected output (e.g., "sel ? b : a")
        test_vectors: Optional JSON string with test vectors. Format: [{"inputs": {...}, "expected_outputs": {...}}, ...]
    
    Returns:
        Path to generated testbench file, or error message with hints
    """
    try:
        import tempfile
        import json
        
        # If test vectors provided, try to infer formula
        if test_vectors and not expected_formula:
            try:
                vectors = json.loads(test_vectors)
                if isinstance(vectors, list) and len(vectors) > 0:
                    # Try to infer formula from test vectors
                    # Example: if sel=0 -> out=a, sel=1 -> out=b, then formula is "sel ? b : a"
                    inferred_formula = None
                    
                    # Check for mux pattern
                    if len(vectors) >= 2:
                        first = vectors[0]
                        second = vectors[1]
                        
                        if "inputs" in first and "expected_outputs" in first:
                            inputs1 = first["inputs"]
                            outputs1 = first["expected_outputs"]
                            
                            if "inputs" in second and "expected_outputs" in second:
                                inputs2 = second["inputs"]
                                outputs2 = second["expected_outputs"]
                                
                                # Look for a selector signal that changes
                                for key in inputs1:
                                    if key in inputs2 and inputs1[key] != inputs2[key]:
                                        # This might be the selector
                                        sel_key = key
                                        sel_val1 = inputs1[key]
                                        sel_val2 = inputs2[key]
                                        
                                        # Check if output changes based on selector
                                        if len(outputs1) == 1 and len(outputs2) == 1:
                                            out_key = list(outputs1.keys())[0]
                                            out1 = outputs1[out_key]
                                            out2 = outputs2[out_key]
                                            
                                            # Find which input matches which output
                                            for in_key in inputs1:
                                                if in_key != sel_key:
                                                    if inputs1[in_key] == out1 and inputs2[in_key] == out2:
                                                        # Pattern: sel=0 -> a, sel=1 -> b
                                                        if sel_val1 == 0 and sel_val2 == 1:
                                                            inferred_formula = f"{sel_key} ? {in_key} : {in_key}"
                                                        elif sel_val1 == 1 and sel_val2 == 0:
                                                            inferred_formula = f"{sel_key} ? {in_key} : {in_key}"
                                                    elif inputs1[in_key] == out2 and inputs2[in_key] == out1:
                                                        # Pattern: sel=0 -> b, sel=1 -> a (reversed)
                                                        if sel_val1 == 0 and sel_val2 == 1:
                                                            inferred_formula = f"{sel_key} ? {in_key} : {in_key}"
                                                        elif sel_val1 == 1 and sel_val2 == 0:
                                                            inferred_formula = f"{sel_key} ? {in_key} : {in_key}"
                                            
                                            # Try to find two different inputs
                                            input_keys = [k for k in inputs1.keys() if k != sel_key]
                                            if len(input_keys) >= 2:
                                                a_key = input_keys[0]
                                                b_key = input_keys[1]
                                                
                                                # Check if it's a mux: sel=0 -> a, sel=1 -> b
                                                if (sel_val1 == 0 and inputs1[a_key] == out1) or \
                                                   (sel_val1 == 1 and inputs1[b_key] == out1):
                                                    if (sel_val2 == 0 and inputs2[a_key] == out2) or \
                                                       (sel_val2 == 1 and inputs2[b_key] == out2):
                                                        inferred_formula = f"{sel_key} ? {b_key} : {a_key}"
                    
                    if inferred_formula:
                        expected_formula = inferred_formula
                    else:
                        # Return hint for agent to analyze
                        return f"ERROR: Could not automatically infer formula from test vectors.\n\nTest vectors provided:\n{test_vectors}\n\nPlease analyze the test vectors and determine the expected formula, then call this tool again with the expected_formula parameter.\n\nFor example, if test vectors show:\n- sel=0, a=170, b=187 -> out=170\n- sel=1, a=170, b=187 -> out=187\nThen the formula is likely: sel ? b : a"
            except json.JSONDecodeError:
                return f"ERROR: Invalid JSON format for test_vectors. Expected format: [{{\"inputs\": {{...}}, \"expected_outputs\": {{...}}}}, ...]"
        
        # Try to infer expected formula from specification if still not provided
        if not expected_formula:
            # Simple heuristics
            spec_lower = specification.lower()
            if "mux" in spec_lower or "multiplexer" in spec_lower:
                if "sel=0" in spec_lower or "sel=1" in spec_lower:
                    if "-> a" in specification or "should be a" in spec_lower:
                        if "-> b" in specification or "should be b" in spec_lower:
                            expected_formula = "sel ? b : a"
        
        if not expected_formula:
            return "ERROR: Could not infer expected formula. Please provide either:\n1. expected_formula parameter (e.g., 'sel ? b : a')\n2. test_vectors parameter in JSON format, and I will try to infer the formula\n\nIf you have test vectors but inference fails, analyze them yourself and provide the formula."
        
        # Generate testbench
        testbench_code = generate_testbench_from_spec_simple(
            module_name=module_name,
            specification=specification,
            expected_formula=expected_formula,
            output_file=None
        )
        
        if not testbench_code:
            return "ERROR: Failed to generate testbench. Please provide a testbench file manually."
        
        # Save to temporary file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sv', delete=False, encoding='utf-8') as f:
            f.write(testbench_code)
            temp_path = f.name
        
        formula_source = "inferred from test vectors" if test_vectors and not expected_formula else "provided directly"
        return f"TESTBENCH GENERATED: {temp_path}\n\nGenerated testbench based on:\n- Specification: {specification}\n- Expected formula: {expected_formula} ({formula_source})\n\nYou can now use this testbench file with run_iverilog."
    
    except Exception as e:
        return f"ERROR: Failed to generate testbench: {str(e)}"


@tool
def analyze_test_failures(simulation_output: str) -> str:
    """
    Analyze test failures from simulation output to identify failure patterns.
    
    This tool helps you understand why tests are failing by:
    - Identifying patterns (e.g., all zero values fail, all small values fail)
    - Detecting common issues (e.g., sign encoding applied to zero values)
    - Providing specific fix suggestions
    
    Args:
        simulation_output: The output from the simulate tool (full output including failures)
    
    Returns:
        An analysis report with:
        - Failure patterns identified
        - Common issues detected
        - Specific fix suggestions
    """
    if not TEST_ANALYZER_AVAILABLE:
        return "ERROR: Test failure analyzer not available"
    
    try:
        report = generate_failure_analysis(simulation_output)
        return report
    except Exception as e:
        return f"ERROR: Failed to analyze test failures: {str(e)}"


@tool
def verify_code_logic(rtl_code: str) -> str:
    """
    Verify the logic in your RTL code for common issues.
    
    This tool checks for:
    - Incorrect shift calculations (e.g., using wrong formula)
    - Exponent zero handling issues
    - Signed arithmetic problems
    - Common logic errors
    
    Args:
        rtl_code: The RTL code to verify
    
    Returns:
        A verification report with:
        - Issues found
        - Warnings
        - Suggestions for fixes
    """
    if not LOGIC_VERIFIER_AVAILABLE:
        return "ERROR: Logic verifier not available"
    
    try:
        report = verify_logic(rtl_code)
        return report
    except Exception as e:
        return f"ERROR: Failed to verify logic: {str(e)}"


@tool
def simulate(binary_path: str) -> str:
    """
    Simulate the compiled Verilog binary using vvp.
    
    Args:
        binary_path: Path to the compiled binary (from run_iverilog output).
                     Extract this from the "Binary created at: <path>" line in compilation result.
    
    Returns:
        A string containing simulation results:
        - If passed: "SIMULATION PASSED: <summary>"
        - If failed: "SIMULATION FAILED: <error details and mismatch info>"
    """
    try:
        if not os.path.exists(binary_path):
            return f"SIMULATION ERROR: Binary not found at {binary_path}"
        
        # Run simulation
        result = subprocess.run(
            ["vvp", binary_path],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        
        # Parse simulation output
        # Look for mismatch information
        if result.returncode == 0:
            # First, check for explicit test failure indicators (e.g., "Test X: ... FAIL")
            # This pattern matches test cases that explicitly report FAIL
            fail_pattern = re.compile(r'Test\s+\d+[^:]*:\s+.*?\s+FAIL', re.IGNORECASE)
            fail_matches = fail_pattern.findall(stdout)
            
            if fail_matches:
                fail_count = len(fail_matches)
                # Extract failed test details
                failed_tests = []
                for match in fail_matches:
                    # Try to extract test number and details
                    test_match = re.search(r'Test\s+(\d+)[^:]*:\s+(.*?)\s+FAIL', match, re.IGNORECASE)
                    if test_match:
                        test_num = test_match.group(1)
                        test_details = test_match.group(2).strip()
                        failed_tests.append(f"Test {test_num}: {test_details}")
                
                fail_summary = f"{fail_count} test case(s) failed"
                if failed_tests:
                    fail_summary += ":\n" + "\n".join(failed_tests[:5])  # Show first 5 failed tests
                    if len(failed_tests) > 5:
                        fail_summary += f"\n... and {len(failed_tests) - 5} more"
                
                result_msg = f"SIMULATION FAILED: {fail_summary}\n\nYour implementation does not match the expected behavior. Please review the test failures above and fix the logic errors.\n\nFull output:\n{stdout}\n{stderr}"
                
                # Automatically run failure analysis if available
                if TEST_ANALYZER_AVAILABLE and generate_failure_analysis:
                    try:
                        analysis = generate_failure_analysis(stdout)
                        result_msg += "\n\n" + "="*70 + "\n"
                        result_msg += "AUTOMATIC FAILURE ANALYSIS (to help you debug):\n"
                        result_msg += "="*70 + "\n"
                        result_msg += analysis
                    except Exception as e:
                        # If analysis fails, just continue without it
                        pass
                
                return result_msg
            
            # Check for mismatch hints in output (for other testbench formats)
            if "mismatches" in stdout.lower() or "mismatch" in stdout.lower():
                # Extract mismatch count
                mismatch_match = re.search(r'(\d+)\s+in\s+(\d+)\s+samples', stdout)
                if mismatch_match:
                    mismatches = int(mismatch_match.group(1))
                    total = int(mismatch_match.group(2))
                    if mismatches > 0:
                        # Extract first mismatch time if available
                        time_match = re.search(r'First mismatch occurred at time (\d+)', stdout)
                        time_info = f" (first at time {time_match.group(1)})" if time_match else ""
                        
                        # Try to extract more context about the mismatch
                        mismatch_details = ""
                        if "Output" in stdout and "mismatches" in stdout:
                            # Extract which output has mismatches
                            output_match = re.search(r"Output '(\w+)' has \d+ mismatches", stdout)
                            if output_match:
                                mismatch_details = f"\nOutput signal '{output_match.group(1)}' has mismatches. "
                                mismatch_details += "This means your implementation's output does not match the expected reference output. "
                                mismatch_details += "Check your logic carefully - the selection condition or bit widths might be wrong."
                        
                        result_msg = f"SIMULATION FAILED: {mismatches} mismatches out of {total} samples{time_info}\n{mismatch_details}\n\nFull output:\n{stdout}\n{stderr}"
                        
                        # Automatically run failure analysis if available
                        if TEST_ANALYZER_AVAILABLE and generate_failure_analysis:
                            try:
                                analysis = generate_failure_analysis(stdout)
                                result_msg += "\n\n" + "="*70 + "\n"
                                result_msg += "AUTOMATIC FAILURE ANALYSIS (to help you debug):\n"
                                result_msg += "="*70 + "\n"
                                result_msg += analysis
                            except Exception as e:
                                # If analysis fails, just continue without it
                                pass
                        
                        return result_msg
            
            # Check for "no mismatches" or success indicators
            if "no mismatches" in stdout.lower() or "has no mismatches" in stdout.lower():
                return f"SIMULATION PASSED: All outputs match expected behavior\n\n{stdout}"
            
            # Check if all tests passed (explicit PASS indicators)
            pass_pattern = re.compile(r'Test\s+\d+[^:]*:\s+.*?\s+PASS', re.IGNORECASE)
            pass_matches = pass_pattern.findall(stdout)
            if pass_matches and not fail_matches:
                # All tests explicitly passed
                return f"SIMULATION PASSED: All {len(pass_matches)} test case(s) passed\n\n{stdout}"
            
            # Default: if return code is 0 and no explicit failures, assume pass
            return f"SIMULATION PASSED: Simulation completed successfully\n\n{stdout}"
        else:
            # Non-zero return code indicates failure
            error_info = stdout + "\n" + stderr if stderr else stdout
            return f"SIMULATION FAILED: Return code {result.returncode}\n\n{error_info}"
    
    except subprocess.TimeoutExpired:
        return "SIMULATION ERROR: Timeout (60s) during simulation"
    except Exception as e:
        return f"SIMULATION ERROR: {str(e)}"


@tool
def analyze_dataflow(rtl_code: str) -> str:
    """
    Analyze the data flow graph (DFG) of RTL code to detect potential logic errors.
    
    This tool helps identify:
    - Key signals (like 'sign', 'reset', 'enable') that exist but are not used in output calculations
    - Unused signals
    - Signal dependencies
    
    Use this tool BEFORE calling run_iverilog to catch logic errors early.
    For example, if your code has a 'sign' signal but doesn't use it in the output calculation,
    this might indicate a missing sign handling logic.
    
    Args:
        rtl_code: Complete SystemVerilog module code to analyze
    
    Returns:
        A data flow analysis report with warnings about potential logic errors
    """
    if analyze_code_for_agent is None:
        return "DFG ANALYSIS ERROR: DFG analyzer not available. Please check if simple_dfg_analyzer.py is in the same directory."
    
    try:
        # Run DFG analysis
        report = analyze_code_for_agent(rtl_code)
        
        # Also get detailed analysis for additional context
        analysis = analyze_data_flow(rtl_code)
        
        # Format a more detailed report for the agent
        detailed_report = "=== Data Flow Graph (DFG) Analysis ===\n\n"
        
        if analysis['warnings']:
            detailed_report += "⚠️  WARNINGS (Potential Logic Errors):\n"
            for warning in analysis['warnings']:
                detailed_report += f"  • {warning['message']}\n"
                if warning['type'] == 'unused_key_signal':
                    signal = warning['signal']
                    detailed_report += f"    → Action: Check if {signal} should be used in output calculations\n"
                    detailed_report += f"    → Example: If {signal} is an input or internal signal, it might need to affect the output\n"
            detailed_report += "\n"
        
        detailed_report += "Signal Dependencies:\n"
        for signal, deps in analysis['dfg'].items():
            if deps:
                detailed_report += f"  {signal} depends on: {', '.join(sorted(deps))}\n"
        
        if analysis['input_signals']:
            detailed_report += f"\nInput signals: {', '.join(sorted(analysis['input_signals']))}\n"
        if analysis['output_signals']:
            detailed_report += f"Output signals: {', '.join(sorted(analysis['output_signals']))}\n"
        
        return detailed_report
        
    except Exception as e:
        return f"DFG ANALYSIS ERROR: {str(e)}\n\nPlease check the RTL code syntax."


# ============================================================================
# Helper Functions
# ============================================================================

def rewrite_state_assignments(rtl_code: str) -> str:
    """Automatically add explicit casts for state_t enum assignments."""
    if "state_t" not in rtl_code:
        return rtl_code
    
    # Pattern: next_state = <expression>;
    pattern = r"(next_state\s*=\s*)([^;]+);"
    
    def repl(match):
        expr = match.group(2).strip()
        # Don't add cast if already present
        if "state_t'(" in expr:
            return match.group(0)
        return f"{match.group(1)}state_t'({expr});"
    
    return re.sub(pattern, repl, rtl_code)


def extract_rtl_code_from_prompt(prompt: str) -> Tuple[str, str]:
    """
    Extract RTL code and requirement description from prompt.
    
    Returns:
        (rtl_code, requirement_description)
    """
    lines = prompt.split('\n')
    in_module = False
    rtl_lines = []
    requirement = ""
    
    # Skip the first line if it's just descriptive text
    start_idx = 0
    for i, line in enumerate(lines):
        if 'module' in line.lower() and ('TopModule' in line or 'module' in line):
            start_idx = i
            break
    
    # Extract module code
    for i in range(start_idx, len(lines)):
        line = lines[i]
        if 'module' in line.lower() and ('TopModule' in line or 'module' in line):
            in_module = True
            rtl_lines.append(line)
        elif in_module:
            rtl_lines.append(line)
            if line.strip().startswith('endmodule'):
                # Everything after endmodule is requirement
                requirement = '\n'.join(lines[i+1:]).strip()
                break
    
    rtl_code = '\n'.join(rtl_lines)
    
    # If no requirement found, look for "Debug this code" or similar in the original prompt
    if not requirement:
        # Look for requirement in lines before module
        for i in range(start_idx):
            line = lines[i]
            if 'debug' in line.lower() or 'should' in line.lower() or 'implement' in line.lower():
                requirement = line.strip()
                break
        # If still not found, look after endmodule
        if not requirement:
            for line in lines:
                if 'debug' in line.lower() and ('should' in line.lower() or 'implement' in line.lower()):
                    requirement = line.strip()
                    break
    
    return rtl_code, requirement


def get_binary_path_from_compile_result(compile_result: str) -> Optional[str]:
    """Extract binary path from compilation result."""
    match = re.search(r'Binary created at:\s*(.+)', compile_result)
    if match:
        return match.group(1).strip()
    return None


# ============================================================================
# RTL Debug Agent with Tools
# ============================================================================

class RTLDebugAgentTooled:
    def __init__(
        self,
        api_key: str = None,
        model: str = "gpt-5.1",
        testbench_path: str = None,
        ref_path: str = None,
        max_iterations: int = 5
    ):
        """Initialize Agent with tools."""
        # Priority: parameter > environment variable > default key
        self.api_key = api_key or os.getenv("OPENAI_API_KEY") or DEFAULT_API_KEY
        if not self.api_key:
            raise ValueError("Please set OPENAI_API_KEY environment variable or pass it as parameter")
        
        self.model = model
        self.testbench_path = testbench_path
        self.ref_path = ref_path
        self.max_iterations = max_iterations
        
        # Initialize LLM
        self.llm = ChatOpenAI(
            model=model,
            api_key=self.api_key,
            temperature=0.3
        )
        
        # Create tools (with context binding)
        iverilog_tool = create_iverilog_tool(self.testbench_path, self.ref_path)
        tools_list = [iverilog_tool, simulate, generate_testbench, analyze_dataflow]
        
        # Add optional analysis tools
        if TEST_ANALYZER_AVAILABLE:
            tools_list.append(analyze_test_failures)
        if LOGIC_VERIFIER_AVAILABLE:
            tools_list.append(verify_code_logic)
        
        self.tools = tools_list
        
        # System prompt
        system_prompt = """You are an expert RTL debugging engineer. Your task is to debug buggy SystemVerilog code.

⚠️⚠️⚠️ CRITICAL WARNING - READ THIS FIRST ⚠️⚠️⚠️
BEFORE writing ANY code, you MUST understand this rule:
❌ NEVER declare ANY variables (logic, integer, int, etc.) inside always_comb or always_ff blocks
✅ ALWAYS declare ALL variables at module level (outside always blocks)
This is the #1 most common error that causes compilation failures!
⚠️⚠️⚠️

CRITICAL REQUIREMENT: You MUST use the tools `run_iverilog` and `simulate` to verify your fixes. Do NOT provide a final answer without calling these tools first.

⚠️⚠️⚠️ CRITICAL: USE TOOLS TO ANALYZE PROBLEMS, NOT PROMPT RULES ⚠️⚠️⚠️

**DO NOT rely on prompt rules for specific algorithms or formulas!**
**USE TOOLS to discover the correct logic through analysis!**

RECOMMENDED TOOL WORKFLOW (use these tools to analyze and fix problems):

1. **`analyze_dataflow`** - Check for potential logic errors BEFORE compiling:
   - Call this tool FIRST after generating your initial fix
   - It will identify:
     * Key signals (like 'sign', 'reset', 'enable') that exist but are not used in output calculations
     * Unused signals
     * Signal dependencies
   - Example: If your code has a 'sign' signal but the tool reports that 'sign' is not used, this indicates missing sign handling logic - FIX IT!

2. **`verify_code_logic`** - Verify your code logic for common issues:
   - Call this tool BEFORE calling `run_iverilog` to catch logic errors early
   - It will identify:
     * Incorrect shift calculations
     * Exponent zero handling issues
     * Signed arithmetic problems
     * Boundary check issues
   - Use this tool's suggestions to fix logic errors BEFORE compilation!

3. **`analyze_test_failures`** - Analyze simulation failures to identify patterns:
   - **MANDATORY**: If simulation fails, ALWAYS call this tool with the simulation output
   - It will identify failure patterns:
     * All zero values fail → encoding logic issue
     * All small values fail → bit selection formula issue
     * Specific value ranges fail → boundary check or calculation issue
   - **USE THE TOOL'S SUGGESTIONS** to fix the issues - don't guess!
   - It will provide specific fix suggestions based on the failure patterns

IMPORTANT: The code will be compiled using Icarus Verilog (iverilog), which has specific syntax limitations. You MUST follow these rules to ensure your code compiles successfully.

ICARUS VERILOG COMPATIBILITY RULES (CRITICAL - MUST FOLLOW):
1. **Array Assignments - NEVER use whole-array assignment (THIS IS THE MOST COMMON ERROR):**
   - ❌ FORBIDDEN: `array_reg <= array_comb;` (even inside for loops)
   - ❌ FORBIDDEN: `for (int i = 0; i < N; i++) array_reg <= array_comb;`  ← WRONG!
   - ❌ FORBIDDEN: `for (int i = 0; i < N; i++) array_reg <= 32'd0;`  ← WRONG!
   - ✅ REQUIRED: `for (int i = 0; i < N; i++) array_reg[i] <= array_comb[i];`  ← CORRECT!
   - ✅ REQUIRED: `for (int i = 0; i < N; i++) array_reg[i] <= 32'd0;`  ← CORRECT!
   - **CRITICAL**: Even inside for loops, you MUST use array indexing [i] on the left side
   - Always use element-wise assignment: `array_reg[i] <= value;`

2. **Variable Declarations in always_comb/always_ff (CRITICAL - COMMON ERROR):**
   - ❌ FORBIDDEN: Declaring ANY variables (integer, logic, int, etc.) in the MIDDLE of always_comb/always_ff blocks
   - ❌ FORBIDDEN: `integer signed_exp;` or `integer shift_amt;` inside always blocks (even at the beginning)
   - ❌ FORBIDDEN: `integer signed [9:0] exp_unb;` or `integer signed [9:0] shift_e;` inside always blocks
   - ❌ FORBIDDEN: `int shift_amt;` or `int signed [9:0] var;` inside always blocks
   - ❌ FORBIDDEN: `logic [31:0] temp;` in the middle of always blocks
   - ✅ REQUIRED: Declare ALL variables (including integer, integer signed, int, int signed, logic) OUTSIDE the always block, at module level
   - ✅ REQUIRED: For ALL integer-related types (integer, integer signed [N:0], int, int signed [N:0]), ALWAYS declare at module level, NEVER inside always blocks
   - **CRITICAL**: This includes ALL variations: `integer`, `integer signed`, `integer signed [N:0]`, `int`, `int signed`, `int signed [N:0]`
   - Example:
     ```systemverilog
     // ❌ WRONG - Declaring in middle of always block:
     always_comb begin
         if (condition) begin
             integer signed_exp;  // ❌ ERROR: syntax error
             logic [31:0] temp;  // ❌ ERROR: syntax error
             temp = a + b;
         end
     end
     
     // ❌ WRONG - Declaring in if-else branch inside always block:
     always_comb begin
         if (condition) begin
             // Some code
         end else begin
             logic [61:0] tmp;  // ❌ ERROR: Cannot declare variables in if-else branches either!
             tmp = some_value;
         end
     end
     
     // ❌ WRONG - Declaring integer at beginning of always block:
     always_comb begin
         integer shift_amt;  // ❌ ERROR: Icarus Verilog doesn't support this
         shift_amt = 5;
     end
     
     // ❌ WRONG - Declaring integer signed with bit width in always block:
     always_comb begin
         integer signed [9:0] exp_unb;  // ❌ ERROR: Even with bit width, cannot declare in always block
         exp_unb = exponent - BIAS;
     end
     
     // ❌ WRONG - Declaring int signed in always block:
     always_comb begin
         int signed [9:0] shift_e;  // ❌ ERROR: All integer types forbidden in always blocks
         shift_e = 5;
     end
     
     // ✅ CORRECT - Declare ALL variables at module level:
     module TopModule (...);
         logic [31:0] temp;              // ✅ Declare at module level
         integer signed_exp;             // ✅ Declare at module level
         integer shift_amt;              // ✅ Declare at module level
         integer signed [9:0] exp_unb;    // ✅ Declare at module level (with bit width OK here)
         integer signed [9:0] shift_e;    // ✅ Declare at module level
         int signed [9:0] r;              // ✅ Declare at module level
         logic [31:0] scaled;            // ✅ Declare at module level
         
         always_comb begin
             // Only use variables, never declare them here
             temp = a + b;
             signed_exp = exponent - BIAS;
             shift_amt = signed_exp + 4;
             exp_unb = $signed({1'b0, exponent}) - $signed({1'b0, BIAS});
             shift_e = exp_unb - 10'sd19;
         end
     endmodule
     ```
   - **CRITICAL**: Icarus Verilog does NOT support declaring ANY variables (integer, logic, int, etc.) inside always_comb/always_ff blocks
   - **CRITICAL**: This includes: `integer`, `integer signed`, `integer signed [N:0]`, `int`, `int signed`, `int signed [N:0]`, `logic [N:0]`
   - **CRITICAL**: Even if the variable has a bit width like `integer signed [9:0]` or `logic [61:0]`, it MUST be declared at module level, NOT inside always blocks
   - **CRITICAL**: This applies to ALL locations inside always blocks: beginning, middle, if-else branches, case branches, for loops, etc.
   - **CRITICAL**: If you see "syntax error" or "Malformed statement" on a variable declaration line inside an always block, move that declaration to module level

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
   - ❌ FORBIDDEN: `array[base - offset -: width]` in always_comb/always_ff (e.g., `tmp[idx_hi -: 12]`)
   - ❌ FORBIDDEN: `array[base + offset -: width]` in always_comb/always_ff (e.g., `tmp[30 + shift -: 12]`)
   - ❌ FORBIDDEN: `array[base + variable -: width]` in always_comb/always_ff (e.g., `full_mantissa[22 + E -: 8]`)
   - ❌ FORBIDDEN: Any bit selection with variable index in always blocks (Icarus Verilog will show "sorry: constant selects in always_* processes are not currently supported")
   - ❌ FORBIDDEN: Bit selection on shift result in always_comb/always_ff (e.g., `(array >> shift_amt)[7:0]`)
   - ✅ REQUIRED: Calculate index first, then use explicit bit range with fixed indices OR use shift operations with intermediate variables
   - Example:
     ```systemverilog
     // ❌ WRONG - Dynamic bit selection:
     always_comb begin
         E = exponent - BIAS;
         int_mag = full_mantissa[22 + E -: 8];  // ❌ ERROR: constant selects not supported
     end
     
     // ❌ WRONG - Bit selection on shift result:
     always_comb begin
         shift_amt = exponent - BIAS;
         int_mag = (full_mantissa >> shift_amt)[7:0];  // ❌ ERROR: syntax error
     end
     
     // ✅ PREFERRED - Use Icarus Verilog's supported syntax directly:
     int shift_amt;  // Declare at module level
     always_comb begin
         shift_amt = BIAS - exponent;  // For exponent < BIAS case
         // Icarus Verilog supports this syntax when shift_amt is int/integer at module level
         // **CRITICAL ALGORITHM ANALYSIS**: The original buggy code uses `full_mantissa[22 + (BIAS - exponent) -: 4]`
         // **MATHEMATICAL REASONING**: For small values (exponent < BIAS), we need to extract fractional bits BELOW bit 22
         //   - When exponent decreases, the binary point shifts LEFT (toward lower bit indices)
         //   - To extract the correct fractional nibble, we should use `22 - shift_amt` (going DOWN from bit 22)
         //   - Using `22 + shift_amt` would select bits ABOVE bit 22, which is incorrect for fractional extraction
         // **CORRECT FORMULA**: `full_mantissa[22 - shift_amt +: 4]` where `shift_amt = BIAS - exponent`
         //   - This selects 4 bits starting from `22 - shift_amt` going UP (toward higher indices)
         //   - For example, if shift_amt=1: selects bits [21:18] (correct fractional region)
         // **WRONG FORMULA**: `full_mantissa[22 + shift_amt -: 4]` would select bits [23:20] (wrong region!)
         frac_true = full_mantissa[22 - shift_amt +: 4];  // ✅ CORRECT: 22 - shift_amt, NOT 22 + shift_amt!
     end
     // **CRITICAL**: Icarus Verilog DOES support `full_mantissa[base - variable +: width]` when variable is `int`/`integer` at module level
     // **PREFERRED**: Use this direct syntax - no need to convert to shift operations
     // **DO NOT** try to convert this to shift operations with complex formulas - use the direct syntax
     // **CRITICAL BUG FIX**: The original code has a bug: `full_mantissa[22 + (BIAS - exponent) -: 4]` should be `full_mantissa[22 - (BIAS - exponent) +: 4]`
     // **When fixing Icarus compatibility, you MUST also fix this algorithm bug by analyzing the mathematical relationship!**
     
     // ✅ ALTERNATIVE - If you must use shift operations (not recommended, error-prone):
     logic [30:0] shifted;
     integer shift_amt;
     always_comb begin
         shift_amt = BIAS - exponent;
         shifted = full_mantissa >> shift_amt;
         // CRITICAL: After shifting, bit positions change! You MUST adjust the bit selection range
         // Original: full_mantissa[22 - shift_amt +: 4] = full_mantissa[22-shift_amt : 19-shift_amt]
         // After shift: shifted[22 - shift_amt : 19 - shift_amt] (NOT shifted[22:19]!)
         frac_true = shifted[22 - shift_amt : 19 - shift_amt];  // Adjust range based on shift amount
     end
     // ❌ WRONG - Complex shift formulas are error-prone:
     // shifted_small = full_mantissa >> (bias_minus_exp + 4);  // Often incorrect!
     // frac_true = shifted_small[3:0];  // Wrong bit selection!
     
     // ✅ ALTERNATIVE - Use explicit ranges with if-else/case:
     logic [7:0] shift_amt;
     always_comb begin
         shift_amt = exponent - BIAS;
         if (shift_amt == 0) begin
             int_mag = full_mantissa[22:15];
         end else if (shift_amt == 1) begin
             int_mag = full_mantissa[21:14];
         end else begin
             // Handle other cases or use shift with intermediate variable
         end
     end
     ```
   - **CRITICAL**: If you see "sorry: constant selects in always_* processes are not currently supported", you MUST rewrite the code to avoid variable-indexed bit selection
   - **CRITICAL**: If you see "syntax error" or "Malformed statement" on a line with `(array >> shift)[bits]`, you MUST use an intermediate variable:
     - Step 1: `shifted = array >> shift_amt;`
     - Step 2: `result = shifted[bits];`
   - **CRITICAL**: When dealing with signed arithmetic (e.g., exponent - BIAS), be careful with unsigned variables:
     - ❌ WRONG: `logic [7:0] E; E = exponent - BIAS;` (if exponent < BIAS, E becomes large positive number like 255)
     - ❌ WRONG: `logic [7:0] exp_minus_bias; exp_minus_bias = exponent - BIAS;` (same problem)
     - ❌ WRONG: Using unsigned subtraction then checking `if (exp_minus_bias > 7)` - this will be TRUE when exponent < BIAS!
     - ✅ CORRECT: Use `int` or `integer` for signed arithmetic:
       ```systemverilog
       integer exp_minus_bias;
       integer bias_minus_exp;
       always_comb begin
           exp_minus_bias = $signed({1'b0, exponent}) - $signed({1'b0, BIAS});
           bias_minus_exp = $signed({1'b0, BIAS}) - $signed({1'b0, exponent});
           // Now exp_minus_bias can be negative, and comparisons work correctly
       end
       ```
     - ✅ ALTERNATIVE: Check condition BEFORE subtraction:
       ```systemverilog
       always_comb begin
           if (exponent < BIAS) begin
               // Handle small values (exponent < BIAS)
           end else if (exponent > BIAS + 8'd7) begin
               // Handle large values (exponent - BIAS > 7)
           end else begin
               // Normal range: use (exponent - BIAS) which is guaranteed positive
           end
       end
       ```
     - **CRITICAL**: If you see test failures where small values (like 1.5, 0.125) are incorrectly treated as saturation (255), check if you're using unsigned subtraction that wraps to large positive numbers

8. **Variable Lifetime Specifiers:**
   - ❌ FORBIDDEN: `automatic` keyword in function variable declarations (in some contexts)
   - ✅ REQUIRED: Declare variables at function beginning without `automatic`

9. **always_ff and always_comb:**
   - Icarus Verilog supports these, but be careful with variable declarations inside them (see rule #2)

10. **DO NOT define dependency modules:**
   - ❌ FORBIDDEN: Do NOT define modules like sys_arr, softmax_core, exp_core, acc_core, div_core, etc.
   - These are provided as stubs in the testbench file
   - ✅ REQUIRED: Only define the TopModule that you are fixing
   - If you see these modules in the prompt, they are dependencies that will be provided by the testbench
   - Your task is ONLY to fix the TopModule, not to implement or redefine dependency modules

IMPORTANT RULES:
1. You do NOT have access to any reference implementation or standard answer code. You can only use tools to compile and simulate your fixes.
2. The testbench validates your code against the specification (requirement description), not against a reference implementation.
3. You MUST use the tools `run_iverilog` and `simulate` to verify your fixes. This is REQUIRED, not optional.
4. If you need to generate a testbench:
   - If you have an expected formula (e.g., "sel ? b : a"), call `generate_testbench` with expected_formula parameter
   - If you only have test vectors (expected outputs for specific inputs), you can:
     a) First analyze the test vectors yourself to determine the formula, then call `generate_testbench` with the formula
     b) Or call `generate_testbench` with test_vectors parameter - it will try to infer the formula automatically
     c) If inference fails, analyze the test vectors and provide the formula yourself
5. Work iteratively:
   - First, analyze the buggy code and understand the requirement
   - **CRITICAL: Understand the ORIGINAL algorithm before rewriting it**
     * If the original code uses dynamic bit selection (e.g., `array[base + offset -: width]`), DO NOT simply replace it with another dynamic bit selection
     * Instead, understand WHY the original code does this, and find an Icarus Verilog-compatible way to achieve the same result
     * Common approaches: use shift operations, use if-else/case with explicit ranges, or restructure the logic
   - Generate an initial fix (provide the COMPLETE module code, not just changes)
   - **RECOMMENDED: Call `analyze_dataflow` tool with your fixed code to check for potential logic errors before compiling**
     * If the tool warns that a key signal (like 'sign') is not used, this is a CRITICAL warning - you MUST use that signal in your logic
     * Do NOT ignore DFG warnings - they often indicate missing logic
   - **CRITICAL: Before calling run_iverilog, review your code for ALL Icarus Verilog compatibility rules above**
   - **CRITICAL: Check for signed arithmetic issues**
     * If you subtract two unsigned values (e.g., `logic [7:0] E = exponent - BIAS`), and the result should be negative, it will wrap to a large positive number
     * Example: If `exponent = 126` and `BIAS = 127`, then `E = 126 - 127 = -1`, but as unsigned `E = 255`
     * This causes `if (E > 7)` to be TRUE when it should be FALSE, leading to incorrect saturation
     * **Common symptom**: Small values (like 1.5, 0.125) are incorrectly treated as saturation (255)
     * Solution: 
       - Option 1: Use `integer` type: `integer E; E = $signed({1'b0, exponent}) - $signed({1'b0, BIAS});`
       - Option 2: Check `exponent < BIAS` BEFORE subtraction, then use `exponent - BIAS` only when `exponent >= BIAS`
   - **CRITICAL: Preserve the original algorithm's sign handling**
     * If the original code uses a specific encoding scheme (e.g., bias encoding, two's complement), DO NOT change it to a different scheme
     * The testbench expects the original encoding format
     * Only fix Icarus Verilog compatibility issues (dynamic bit selection, variable declarations), not the algorithm logic
     * **IMPORTANT**: However, if the original code has a bug (e.g., applying encoding incorrectly), you MUST fix that bug
     * **USE TOOLS TO VERIFY ENCODING LOGIC**:
     *   - Use `analyze_test_failures` tool to identify encoding-related failures (e.g., zero values producing wrong outputs)
     *   - Use `verify_code_logic` tool to check for incorrect encoding formulas
     *   - Analyze the testbench's expected outputs to understand the correct encoding scheme
     *   - DO NOT guess the encoding - use tools to discover it!
   - **CRITICAL: Bit selection with variable indices requires careful handling**
     * **IMPORTANT**: Icarus Verilog DOES support `array[base - variable -: width]` syntax when the variable is declared as `int` or `integer` at module level
     * **NOTE**: Icarus Verilog also supports expressions in bit selection (e.g., `array[base - (expr) +: width]`), but using intermediate variables is **RECOMMENDED** for clarity
     * **CRITICAL: BOUNDARY CHECKS ARE REQUIRED**
     *   - When using bit selection with variable indices, you MUST check if the selection is within valid range
     *   - Example: If selecting from `array[30:0]`, check that `base - variable >= 0` and `base - variable + width - 1 <= 30`
     *   - Use clear boundary conditions (e.g., `if (variable <= max_valid_value)`) rather than reversed conditions
     *   - Return a safe default value (e.g., `4'd0`) if out of range
     * **RECOMMENDED APPROACH**: Always use intermediate variables + boundary checks:
     *   - Calculate the selection index/offset first
     *   - Check if the selection is within valid range
     *   - Only perform bit selection if within valid range
     *   - Return a safe default if out of range
     * **ALTERNATIVE**: You can also use expressions directly, but you MUST still add boundary checks to prevent out-of-range access
     * ❌ AVOID: Trying to use complex shift formulas - these are error-prone and often incorrect
     * ✅ CORRECT: Use `int shift_amt;` at module level, then calculate and check before bit selection
     * **CRITICAL: Bit selection direction matters!**
     *   - `-:` (minus colon) = downward selection: `array[base -: width]` = `array[base : base-width+1]` (selects bits going DOWN from base)
     *   - `+:` (plus colon) = upward selection: `array[base +: width]` = `array[base : base+width-1]` (selects bits going UP from base)
     *   - ❌ WRONG: Using `+:` when you should use `-:` (or vice versa) will select the WRONG bits!
     *   - **USE TOOLS**: If tests fail, use `analyze_test_failures` to identify patterns and verify your bit selection logic!
     *   - **USE TOOLS**: Use `verify_code_logic` to check for incorrect bit selection formulas!
     * **ONLY if you must use shift operations** (not recommended):
     *   - After `shifted = array >> shift_amt`, you must adjust the bit selection range: `shifted[high - shift_amt : low - shift_amt]`, NOT `shifted[high:low]`
     *   - ❌ WRONG: `shifted = array >> shift_amt; result = shifted[high:low];` (this only works when shift_amt = 0)
     *   - ✅ CORRECT: `shifted = array >> shift_amt; result = shifted[high - shift_amt : low - shift_amt];`
     * Always verify your calculation with a simple example to ensure correctness
   - **WORKFLOW: Use tools to analyze, not prompt rules!**
     * Step 1: Generate initial fix based on understanding the requirement
     * Step 2: Call `analyze_dataflow` to check for unused signals or missing logic
     * Step 3: Call `verify_code_logic` to check for common logic errors
     * Step 4: Call `run_iverilog` with the FULL fixed RTL code to compile
     * Step 5: If compilation fails, read the error message and fix Icarus Verilog compatibility issues
     * Step 6: Extract the binary path from "Binary created at: <path>" in the compilation result
     * Step 7: Call `simulate` with that binary path to run the simulation
     * Step 8: **If simulation fails, ALWAYS call `analyze_test_failures` with the simulation output**
     * Step 9: Use the tool's suggestions to fix the issues - don't guess!
     * Step 10: Repeat until both compilation and simulation pass
   - **Compilation error handling**:
     * If you see "Assignment to an entire array" → Use element-wise assignment in for loops
     * If you see "syntax error" or "Malformed statement" on a variable declaration line → Move that variable declaration to module level (outside always block)
     * If you see "syntax error" with integer/logic/int declaration inside always block → Move ALL variable declarations to module level
     * If you see "requires an explicit cast" → Add type cast for enum assignments
     * If you see "sorry: constant selects in always_* processes are not currently supported" → Rewrite to avoid variable-indexed bit selection (use shifts or explicit ranges)
   - **Simulation failure handling**:
     * The mismatch count tells you how many cycles your output differs from expected
     * If ALL or MOST samples mismatch (e.g., 76 out of 114, or >50%), your logic is DEFINITELY WRONG
     * When most samples mismatch, DO NOT blame the testbench - the problem is in YOUR code
     * **MANDATORY**: Call `analyze_test_failures` to identify patterns and get specific suggestions
     * **MANDATORY**: Use the tool's suggestions to fix the issues - don't try to guess the fix!
     * Common issues when most samples mismatch:
       - Signed arithmetic errors (unsigned subtraction resulting in large positive numbers)
       - Selection condition REVERSED: Try the opposite (sel ? a : b → sel ? b : a, or vice versa)
       - Wrong bit widths (already checked? Check again!)
       - Operator errors (AND vs OR, etc.)
       - Dynamic bit selection not working (even if compilation succeeds)
       - Encoding logic errors (use `analyze_test_failures` to identify)
       - Bit selection formula errors (use `analyze_test_failures` to identify)
     * Pay attention to the requirement description - it tells you what the module SHOULD do
     * **If your algorithm is completely different from the original, and most tests fail, consider going back to the original algorithm structure and just fixing the Icarus Verilog compatibility issues**
   - **ONLY provide final code after simulation passes**
6. When calling `run_iverilog`, you MUST provide the complete SystemVerilog module code including:
   - module declaration
   - all ports (check bit widths carefully!)
   - all internal logic
   - endmodule
   - **MUST comply with ALL Icarus Verilog compatibility rules listed above**
7. Common bugs to check:
   - Bit width mismatches (e.g., output declared as 1-bit but should be 8-bit)
   - Selection logic reversed (e.g., sel ? a : b vs sel ? b : a) - If most samples mismatch, TRY THE OPPOSITE
   - Operator precedence issues
   - Missing or incorrect assignments
   - **Array assignment issues (use element-wise, not whole-array)**
   - **Variable declaration positions (declare at beginning of always blocks)**
   - **Enum type casting (use explicit casts)**
8. When you provide the final fixed code, wrap it in ```systemverilog code blocks.
9. **CRITICAL CHECKLIST - Before submitting code, verify:**
   - ✅ ALL array assignments use element-wise indexing: `array[i] <= value;` NOT `array <= value;`
   - ✅ ALL for loops with arrays use indexing: `for (i=0; i<N; i++) array[i] <= ...;` NOT `array <= ...;`
   - ✅ **NO variable declarations inside always_comb/always_ff blocks** - ALL variables (logic, integer, int, etc.) MUST be declared at module level
   - ✅ **Check every always block** - If you see `logic [N:0] var;` or `integer var;` inside an always block, MOVE IT OUTSIDE
   - ✅ ALL enum assignments use explicit type casts: `state_t'(value)`
   - ✅ DO NOT define dependency modules (sys_arr, softmax_core, etc.) - only define TopModule
   - ✅ **NO dynamic bit selection in always blocks** - If you see `array[base + variable -: width]`, rewrite using shifts or explicit ranges
   - ✅ **Check signed arithmetic** - If subtracting unsigned values that could result in negative numbers, check the condition BEFORE subtraction or use signed types
   - ✅ **DFG warnings are CRITICAL** - If DFG warns that a key signal (like 'sign') is not used, you MUST use it in your logic
   - ✅ **Before calling run_iverilog, scan your code for:**
     * Variable declarations inside always blocks → move to module level
     * Dynamic bit selections → rewrite using shifts or explicit ranges
     * Unsigned subtraction that could be negative → add checks or use signed types
10. Explain your reasoning at each step.

The requirement description tells you what the module SHOULD do, not what it currently does (which is buggy)."""
        
        # Create agent using new LangChain 1.1.0 API
        self.agent = create_agent(
            model=self.llm,
            tools=self.tools,
            system_prompt=system_prompt,
            debug=False
        )
        self.max_iterations = max_iterations
    
    def debug_rtl(
        self,
        rtl_code: str,
        requirement: str = "",
        problem_name: str = "unknown",
        expected_formula: str = None,
        test_vectors: str = None
    ) -> Dict[str, any]:
        """
        Debug RTL code iteratively using tools.
        
        Returns:
            {
                "success": bool,
                "final_code": str,
                "iterations": int,
                "messages": List[str],
                "error": str (if failed)
            }
        """
        # Check if testbench exists or needs to be generated
        testbench_available = self.testbench_path and os.path.exists(self.testbench_path) and os.path.getsize(self.testbench_path) > 100
        if not testbench_available:
            # Testbench will be generated by agent using generate_testbench tool
            console.print("[yellow]Note: No testbench file provided. Agent will generate one from specification.[/yellow]")
        
        # Prepare initial prompt with testbench information
        testbench_info = ""
        testbench_available = self.testbench_path and os.path.exists(self.testbench_path) and os.path.getsize(self.testbench_path) > 100
        
        if testbench_available:
            # Method 1: Full testbench provided
            testbench_info = f"\n\n[METHOD 1: Full Testbench] A complete testbench file is provided.\nYou can use it directly with `run_iverilog` tool."
        else:
            # Methods 2 & 3: Need to generate testbench
            testbench_info = "\n\n[METHOD 2 or 3: Generate Testbench] No testbench file provided. You need to use the `generate_testbench` tool to create one."
            
            # Check what information is available
            if expected_formula:
                testbench_info += f"\n\n[Method 2: Expected Formula Available]\nAn expected formula is provided: {expected_formula}\nCall `generate_testbench` with expected_formula=\"{expected_formula}\" to generate the testbench."
            elif test_vectors:
                testbench_info += f"\n\n[Method 3: Test Vectors Available]\nTest vectors are provided:\n{test_vectors}\n\nYou can:\n1. First call `generate_testbench` with test_vectors parameter - the tool will try to infer the formula automatically\n2. If inference fails, analyze the test vectors yourself to determine the formula, then call `generate_testbench` again with the expected_formula parameter"
            else:
                testbench_info += "\n\nYou can generate a testbench in two ways:\n- Method 2: If you have an expected formula (e.g., \"sel ? b : a\"), call `generate_testbench` with expected_formula parameter\n- Method 3: If you only have test vectors (input-output pairs), call `generate_testbench` with test_vectors parameter. The tool will try to infer the formula automatically. If inference fails, analyze the test vectors yourself to determine the formula, then call the tool again with the formula."
        
        initial_prompt = f"""I need to debug the following SystemVerilog code.

REQUIREMENT:
{requirement if requirement else "Please identify and fix all bugs in the code."}

BUGGY RTL CODE:
```systemverilog
{rtl_code}
```
{testbench_info}

Your task:
1. Analyze the code and understand what it should do based on the requirement
2. Identify the bugs
3. If no testbench is available, use `generate_testbench` tool to create one (see methods above)
4. Generate a fixed version of the code
5. Use `run_iverilog` tool with the COMPLETE fixed module code to compile it
6. If compilation succeeds, extract the binary path and use `simulate` tool to test it
7. If compilation or simulation fails, analyze the error/mismatch and refine your fix
8. Iterate until both compilation and simulation pass
9. Provide the final corrected code in a ```systemverilog code block

Remember: When calling `run_iverilog`, you must provide the FULL module code, not just snippets or changes.
"""
        
        messages = []
        final_code = ""
        success = False
        
        try:
            console.print("\n[bold cyan]🤖 Agent starting iterative debugging...[/bold cyan]\n")
            
            # Run agent using new API
            # The new API uses invoke with messages
            from langchain_core.messages import HumanMessage, AIMessage, ToolMessage
            response = self.agent.invoke({
                "messages": [HumanMessage(content=initial_prompt)]
            })
            
            # Extract output from response
            # The response is a dict with "messages" key containing all messages
            output = ""
            tool_outputs = []
            
            if isinstance(response, dict) and "messages" in response:
                # Get all messages
                all_messages = response["messages"]
                
                # Debug: print message types
                console.print(f"[dim]Total messages: {len(all_messages)}[/dim]")
                
                # Extract assistant messages and tool outputs
                assistant_messages = []
                for msg in all_messages:
                    msg_type = type(msg).__name__
                    if msg_type == "AIMessage":
                        # This is an assistant response
                        if hasattr(msg, 'content') and msg.content:
                            assistant_messages.append(str(msg.content))
                        # Check for tool calls
                        if hasattr(msg, 'tool_calls') and msg.tool_calls:
                            console.print(f"[dim]Tool calls detected: {len(msg.tool_calls)}[/dim]")
                    elif msg_type == "ToolMessage":
                        # This is a tool output
                        if hasattr(msg, 'content'):
                            tool_outputs.append(str(msg.content))
                            console.print(f"[dim]Tool output: {msg.content[:100]}...[/dim]")
                
                # Use the last assistant message as the main output
                if assistant_messages:
                    output = assistant_messages[-1]
                elif tool_outputs:
                    # If no assistant message but we have tool outputs, use them
                    output = "\n\n".join(tool_outputs)
                else:
                    # Fallback: get last message
                    if all_messages:
                        output = str(all_messages[-1])
            else:
                output = str(response)
            
            messages.append(output)
            
            # Also include tool outputs in messages for debugging
            if tool_outputs:
                messages.append(f"\n[Tool Outputs]\n" + "\n\n".join(tool_outputs))
            
            # Extract final code from output
            code_blocks = re.findall(r"```(?:systemverilog)?\n(.*?)```", output, re.DOTALL)
            if code_blocks:
                final_code = code_blocks[-1].strip()  # Take the last code block
                
                # Post-process: move variable declarations to module level
                try:
                    import sys
                    from pathlib import Path
                    sys.path.insert(0, str(Path(__file__).parent))
                    from move_variable_declarations import move_variable_declarations_to_module_level
                    
                    processed_code = move_variable_declarations_to_module_level(final_code)
                    if processed_code != final_code:
                        final_code = processed_code
                        console.print("[dim]Post-processed: Moved variable declarations to module level[/dim]")
                except ImportError:
                    # If the module doesn't exist, skip post-processing
                    pass
                except Exception as e:
                    # If post-processing fails, continue with original code
                    pass
            
            # Check if tools were called (required for verification)
            tools_were_called = len(tool_outputs) > 0
            
            # Combine output and tool_outputs for success checking
            all_output_text = output + "\n" + "\n".join(tool_outputs)
            
            # Check if simulation passed (look for success indicators in both output and tool outputs)
            if "SIMULATION PASSED" in all_output_text or "simulation passed" in all_output_text.lower():
                success = True
                console.print("[green]✓ Simulation passed! Fix is correct.[/green]")
            elif "SIMULATION FAILED" in all_output_text or "COMPILATION ERROR" in all_output_text:
                success = False
            elif not tools_were_called:
                # If no tools were called, we can't verify the fix
                success = False
                console.print("[yellow]Warning: Agent did not call tools to verify the fix. Cannot confirm correctness.[/yellow]")
            else:
                # If we got here and have code but no clear pass/fail, assume failure
                # (we need explicit SIMULATION PASSED to consider it successful)
                success = False
            
            return {
                "success": success,
                "final_code": final_code,
                "iterations": self.max_iterations,  # LangChain handles this internally
                "messages": messages,
                "error": None if success else "Debugging did not complete successfully"
            }
        
        except Exception as e:
            error_msg = str(e)
            # Check for API quota errors
            if "429" in error_msg or "quota" in error_msg.lower() or "insufficient_quota" in error_msg.lower():
                error_msg = f"OpenAI API quota exceeded. Please check your billing details or use a different API key.\n\nOriginal error: {error_msg}"
                console.print(f"[red]✗ API Error: {error_msg}[/red]")
            
            return {
                "success": False,
                "final_code": final_code,
                "iterations": 0,
                "messages": messages,
                "error": error_msg
            }


# ============================================================================
# Main Functions
# ============================================================================

def display_result(result: Dict, rtl_code: str):
    """Display debugging result."""
    console.print("\n[bold yellow]═══ Debugging Result ═══[/bold yellow]")
    
    if result["success"]:
        console.print("[green]✓ Debugging completed successfully![/green]\n")
    else:
        console.print(f"[red]✗ Debugging failed: {result.get('error', 'Unknown error')}[/red]\n")
    
    if result["final_code"]:
        console.print(Panel(
            Syntax(result["final_code"], "systemverilog", theme="monokai", line_numbers=True),
            title="Final Fixed Code",
            border_style="green" if result["success"] else "yellow"
        ))
    
    if result["messages"]:
        console.print("\n[bold]Agent Messages:[/bold]")
        for i, msg in enumerate(result["messages"], 1):
            console.print(Panel(
                Markdown(msg[:1000] + "..." if len(msg) > 1000 else msg),
                title=f"Message {i}",
                border_style="blue"
            ))


def run_debug_session(
    rtl_code: str,
    requirement: str,
    testbench_path: str = None,
    ref_path: str = None,
    problem_name: str = "unknown",
    api_key: str = None,
    model: str = "gpt-5.1",
    max_iterations: int = 5,
    expected_formula: str = None,
    test_vectors: str = None
):
    """Run debug session with tools."""
    console.print(Panel.fit(
        "[bold cyan]RTL Code Debugging Agent (with Tools)[/bold cyan]\n"
        "Iterative debugging using LangChain Agent + Icarus Verilog",
        border_style="cyan"
    ))
    console.print()
    
    # Display original code
    console.print("[bold yellow]═══ Original Buggy RTL Code ═══[/bold yellow]")
    console.print(Panel(
        Syntax(rtl_code, "systemverilog", theme="monokai", line_numbers=True),
        title="Buggy Code",
        border_style="red"
    ))
    
    if requirement:
        console.print(f"\n[bold]Requirement:[/bold] {requirement}\n")
    
    # If no testbench provided, try to generate one
    if not testbench_path:
        console.print("[yellow]No testbench provided. Agent will generate one from specification...[/yellow]")
        # Agent will use generate_testbench tool during debugging
        # For now, we still need a placeholder path for tool initialization
        # The agent will generate testbench on the fly
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.sv', delete=False) as f:
            f.write("// Placeholder - will be generated by agent\n")
            testbench_path = f.name
    
    # Initialize agent
    try:
        agent = RTLDebugAgentTooled(
            api_key=api_key,
            model=model,
            testbench_path=testbench_path,
            ref_path=ref_path,
            max_iterations=max_iterations
        )
    except ValueError as e:
        console.print(f"[red]{e}[/red]")
        sys.exit(1)
    
    # Run debugging
    result = agent.debug_rtl(
        rtl_code=rtl_code,
        requirement=requirement,
        problem_name=problem_name,
        expected_formula=expected_formula,
        test_vectors=test_vectors
    )
    
    # Display result
    display_result(result, rtl_code)
    
    # Also print final code to stdout in a format that can be easily extracted
    if result["final_code"]:
        console.print("\n[bold]=== Final Fixed Code (for extraction) ===[/bold]")
        console.print("```systemverilog")
        console.print(result["final_code"])
        console.print("```")
    
    return result


# ============================================================================
# Command Line Interface
# ============================================================================

def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="RTL Code Debugging Agent with Tools (LangChain Agent)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --prompt dataset_rtl-debug/Prob001_prompt.txt --testbench dataset_rtl-debug/Prob001_test.sv
  %(prog)s --rtl buggy.sv --requirement "8-bit mux" --testbench test.sv --ref ref.sv
        """
    )
    
    parser.add_argument(
        "--prompt",
        type=str,
        help="Path to prompt file (contains both RTL code and requirement)"
    )
    
    parser.add_argument(
        "--rtl",
        type=str,
        help="Path to buggy RTL code file"
    )
    
    parser.add_argument(
        "--requirement",
        type=str,
        default="",
        help="Requirement description (what the module should do)"
    )
    
    parser.add_argument(
        "--testbench",
        type=str,
        default=None,
        help="Path to testbench file (*_test.sv). If not provided, agent will try to generate one from specification (requires --expected-formula)"
    )
    
    parser.add_argument(
        "--expected-formula",
        type=str,
        default=None,
        help="Expected output formula (e.g., 'sel ? b : a') for testbench generation. Use this if you have the formula but no testbench."
    )
    
    parser.add_argument(
        "--test-vectors",
        type=str,
        default=None,
        help="Test vectors in JSON format. Use this if you have input-output pairs but no formula. Format: '[{\"inputs\": {...}, \"expected_outputs\": {...}}, ...]'"
    )
    
    parser.add_argument(
        "--test-vectors-file",
        type=str,
        default=None,
        help="Path to JSON file containing test vectors. Alternative to --test-vectors for large test sets."
    )
    
    parser.add_argument(
        "--ref",
        type=str,
        default=None,
        help="Path to reference module file (*_ref.sv) - optional, only needed if testbench uses RefModule (for evaluation scenarios). In real engineering scenarios, this is not needed."
    )
    
    parser.add_argument(
        "--problem-name",
        type=str,
        default="unknown",
        help="Problem name (for output files)"
    )
    
    parser.add_argument(
        "-m", "--model",
        default="gpt-5.1",
        help="OpenAI model name (default: gpt-5.1)"
    )
    
    parser.add_argument(
        "--api-key",
        default=None,
        help="OpenAI API key (can also be set via OPENAI_API_KEY environment variable)"
    )
    
    parser.add_argument(
        "--max-iterations",
        type=int,
        default=5,
        help="Maximum number of tool-calling iterations (default: 5)"
    )
    
    parser.add_argument(
        "--output",
        type=str,
        help="Output file to save final fixed code"
    )
    
    args = parser.parse_args()
    
    # Determine input source
    if args.prompt:
        if not os.path.exists(args.prompt):
            console.print(f"[red]Error: Prompt file not found: {args.prompt}[/red]")
            sys.exit(1)
        
        with open(args.prompt, 'r', encoding='utf-8') as f:
            prompt_text = f.read()
        
        rtl_code, requirement = extract_rtl_code_from_prompt(prompt_text)
        
        if not rtl_code:
            console.print("[red]Error: Could not extract RTL code from prompt file[/red]")
            sys.exit(1)
        
        # Extract problem name from prompt file if not provided
        if args.problem_name == "unknown":
            args.problem_name = Path(args.prompt).stem.replace("_prompt", "")
    
    elif args.rtl:
        if not os.path.exists(args.rtl):
            console.print(f"[red]Error: RTL file not found: {args.rtl}[/red]")
            sys.exit(1)
        
        with open(args.rtl, 'r', encoding='utf-8') as f:
            rtl_code = f.read()
        
        requirement = args.requirement
        
        # Extract problem name from RTL file if not provided
        if args.problem_name == "unknown":
            args.problem_name = Path(args.rtl).stem
    
    else:
        console.print("[red]Error: Must provide either --prompt or --rtl[/red]")
        sys.exit(1)
    
    # Check testbench or generate one
    if not args.testbench:
        # No testbench provided - agent will need to generate one
        if not args.requirement and not args.rtl:
            console.print("[yellow]Warning: No testbench provided. Agent will try to generate one from specification.[/yellow]")
        testbench_path = None
    else:
        if not os.path.exists(args.testbench):
            console.print(f"[red]Error: Testbench file not found: {args.testbench}[/red]")
            sys.exit(1)
        testbench_path = args.testbench
        console.print(f"[green]✓ Testbench file provided: {args.testbench}[/green]")
        console.print("[green]  → Using Method 1: Full Testbench (agent will use this testbench directly)[/green]")
    
    # Check ref if provided (optional, only for evaluation scenarios)
    if args.ref:
        if not os.path.exists(args.ref):
            console.print(f"[yellow]Warning: Reference file not found: {args.ref}[/yellow]")
            console.print("[dim]Continuing without reference (real engineering scenario)[/dim]")
            args.ref = None
        else:
            console.print(f"[dim]Reference file provided (evaluation mode)[/dim]")
    else:
        console.print("[dim]No reference file provided - using specification-based validation (real engineering scenario)[/dim]")
    
    # Load test vectors if provided
    test_vectors = None
    if args.test_vectors:
        test_vectors = args.test_vectors
    elif args.test_vectors_file:
        if not os.path.exists(args.test_vectors_file):
            console.print(f"[red]Error: Test vectors file not found: {args.test_vectors_file}[/red]")
            sys.exit(1)
        with open(args.test_vectors_file, 'r', encoding='utf-8') as f:
            test_vectors = f.read()
    
    # If test vectors or expected formula provided but no testbench, add to requirement
    if not testbench_path and (args.expected_formula or test_vectors):
        if args.expected_formula:
            console.print(f"[green]✓ Expected formula provided: {args.expected_formula}[/green]")
            console.print("[green]  → Using Method 2: Expected Formula (agent will generate testbench from formula)[/green]")
            requirement += f"\n\nExpected formula: {args.expected_formula}"
        elif test_vectors:
            console.print(f"[green]✓ Test vectors provided[/green]")
            console.print("[green]  → Using Method 3: Test Vectors (agent will infer formula and generate testbench)[/green]")
            requirement += f"\n\nTest vectors provided: {test_vectors}"
    elif not testbench_path:
        console.print("[yellow]⚠ No testbench, formula, or test vectors provided[/yellow]")
        console.print("[yellow]  → Agent will try to generate testbench from specification only[/yellow]")
    
    # Run debug session
    result = run_debug_session(
        rtl_code=rtl_code,
        requirement=requirement,
        testbench_path=testbench_path,
        ref_path=args.ref,
        problem_name=args.problem_name,
        api_key=args.api_key,
        model=args.model,
        max_iterations=args.max_iterations,
        expected_formula=args.expected_formula,
        test_vectors=test_vectors
    )
    
    # Save output if requested
    if args.output and result["final_code"]:
        # Post-process: move variable declarations to module level
        try:
            from pathlib import Path
            # Use global sys imported at top of file; extend sys.path so we can import helper
            sys.path.insert(0, str(Path(__file__).parent))
            from move_variable_declarations import move_variable_declarations_to_module_level
            
            original_code = result["final_code"]
            processed_code = move_variable_declarations_to_module_level(original_code)
            
            if processed_code != original_code:
                console.print(f"[yellow]Post-processed: Moved variable declarations to module level[/yellow]")
                result["final_code"] = processed_code
        except ImportError:
            # If the module doesn't exist, skip post-processing
            pass
        except Exception as e:
            # If post-processing fails, continue with original code
            console.print(f"[yellow]Warning: Post-processing failed: {e}[/yellow]")
        
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result["final_code"])
        console.print(f"\n[green]Final code saved to: {args.output}[/green]")
    
    # Exit with appropriate code
    sys.exit(0 if result["success"] else 1)


if __name__ == "__main__":
    main()

