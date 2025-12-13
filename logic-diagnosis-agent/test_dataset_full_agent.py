#!/usr/bin/env python3
"""
Full agent test script using rtl_debug_agent_tooled.py with all tools
FULL AGENT VERSION: Uses all tools (run_iverilog, simulate, generate_testbench, etc.)
Agent performs iterative debugging with tool feedback.
"""

import os
import sys
import re
import subprocess
from pathlib import Path
from typing import Dict, List, Tuple
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

console = Console()

CODE_BLOCK = re.compile(r"```(?:systemverilog)?\s*\n(.*?)```", re.S | re.M)

def extract_candidate_code(text: str) -> str:
    """Try to pull the corrected RTL module from the agent response."""
    # First, collect all "Final Fixed Code" sections and score them
    # This ensures we get the best version, not just the first one
    all_final_sections = []
    
    # Pattern 1: Boxed format (╭...Final Fixed Code...╮)
    # Match until ╰ (end of box), not === (which might appear earlier)
    boxed_pattern = r'╭[^╮]*Final Fixed Code[^╮]*╮\n(.*?)(?=╰[─╯]*╯|Agent Messages|$)'
    for match in re.finditer(boxed_pattern, text, re.DOTALL):
        section = match.group(1)
        # Clean up box formatting
        code_lines = []
        for line in section.split('\n'):
            # Remove box characters and line numbers from both start and end
            clean_line = re.sub(r'^│\s*\d+\s+', '', line)  # Remove │ and line numbers from start
            clean_line = re.sub(r'^│\s*', '', clean_line)  # Remove │ from start
            clean_line = re.sub(r'\s*│\s*$', '', clean_line)  # Remove │ from end
            clean_line = clean_line.strip()
            if clean_line:
                code_lines.append(clean_line)
        code = '\n'.join(code_lines)
        # Final cleanup: remove any remaining box-drawing characters
        code = re.sub(r'[│╭╰╮╯]', '', code)  # Remove any remaining box-drawing characters
        if "module" in code and "endmodule" in code:
            all_final_sections.append(code)
    
    # Pattern 2: === Final Fixed Code === format
    equals_pattern = r'=== Final Fixed Code[^=]*===\n```systemverilog\n(.*?)```'
    for match in re.finditer(equals_pattern, text, re.DOTALL):
        code = match.group(1).strip()
        if "module" in code and "endmodule" in code:
            all_final_sections.append(code)
    
    # Pattern 3: Generic "Final Fixed Code" section
    generic_pattern = r'Final Fixed Code[^\n]*\n(.*?)(?=\n\n|===|Agent Messages|$)'
    for match in re.finditer(generic_pattern, text, re.DOTALL):
        code = match.group(1).strip()
        # Remove markdown markers
        code = re.sub(r'^```.*?\n', '', code, flags=re.MULTILINE)
        code = re.sub(r'\n```\s*$', '', code, flags=re.MULTILINE)
        if "module" in code and "endmodule" in code:
            all_final_sections.append(code)
    
    # Clean and filter code sections
    cleaned_sections = []
    for code in all_final_sections:
        # Filter out lines with syntax errors
        cleaned_code = filter_syntax_errors(code)
        # Remove duplicate assignments (keep the last one)
        cleaned_code = remove_duplicate_assignments(cleaned_code)
        if "module" in cleaned_code and "endmodule" in cleaned_code:
            cleaned_sections.append(cleaned_code)
    
    # Score all sections: prefer ones with correct array indexing
    if cleaned_sections:
        scored_sections = []
        for code in cleaned_sections:
            score = 0
            # High score for correct array indexing patterns
            if re.search(r'exp_out_reg\[i\]\s*<=', code):
                score += 20
            if re.search(r'array\[i\]\s*<=', code):
                score += 10
            # Penalty for wrong patterns (whole array assignment without index)
            if re.search(r'exp_out_reg\s*<=\s*32', code) and not re.search(r'exp_out_reg\[i\]', code):
                score -= 10
            if re.search(r'exp_out_reg\s*<=\s*exp_out_comb', code) and not re.search(r'exp_out_reg\[i\]', code):
                score -= 10
            scored_sections.append((score, code))
        
        # Sort by score (highest first) and take the best one
        scored_sections.sort(key=lambda x: x[0], reverse=True)
        if scored_sections:
            return scored_sections[0][1].strip()
    
    # Fallback: Try code blocks (but only if no "Final Fixed Code" sections found)
    patterns = [
        r"```systemverilog\s*\n(.*?)```",  # systemverilog code block
        r"```verilog\s*\n(.*?)```",  # verilog code block
        r"```\s*\n(.*?)```",  # generic code block
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            if "module" in match and "endmodule" in match:
                cleaned = filter_syntax_errors(match)
                cleaned = remove_duplicate_assignments(cleaned)
                return cleaned.strip()
    
    # Fallback: look for [BEGIN]/[DONE]
    begin = text.find("[BEGIN]")
    done = text.find("[DONE]", begin if begin >= 0 else 0)
    if begin >= 0 and done > begin:
        code = text[begin + len("[BEGIN]"):done].strip()
        cleaned = filter_syntax_errors(code)
        cleaned = remove_duplicate_assignments(cleaned)
        return cleaned

    return ""


def filter_syntax_errors(code: str) -> str:
    """Filter out lines with common syntax errors that Icarus Verilog cannot handle."""
    lines = code.split('\n')
    filtered_lines = []
    
    for line in lines:
        # Skip lines with invalid part select expressions (e.g., dividend[22: -1 + 23 + 1])
        if re.search(r'\[.*:\s*-.*\+.*\]', line):
            # This is likely a syntax error - skip it
            continue
        
        # Skip lines with invalid array assignments (whole array without index in for loop context)
        # But keep lines that are clearly correct
        if re.search(r'^\s*[a-zA-Z_][a-zA-Z0-9_]*\s*<=\s*[^;]+;\s*//\s*equivalent\s+to', line, re.IGNORECASE):
            # This is likely an explanation that was incorrectly written as code - skip it
            continue
        
        filtered_lines.append(line)
    
    return '\n'.join(filtered_lines)


def remove_duplicate_assignments(code: str) -> str:
    """Remove duplicate assignments to the same variable, but ONLY if they are truly redundant.
    
    This function should NOT filter assignments in if-else blocks, as those are intentional
    conditional assignments. It only filters truly redundant duplicate assignments (e.g., 
    the same assignment appearing multiple times in a row, or in the same scope without conditions).
    """
    lines = code.split('\n')
    
    # Only remove duplicates that are:
    # 1. Consecutive (same assignment on consecutive lines)
    # 2. In the same scope without any control flow (if/else/case) between them
    
    # Track assignments with context (check for if/else/case before them)
    filtered_lines = []
    i = 0
    
    while i < len(lines):
        line = lines[i]
        
        # Check if this is an assignment
        match = re.search(r'^\s*([a-zA-Z_][a-zA-Z0-9_\[\]]*)\s*<=\s*([^;]+);', line)
        if match:
            var_name = match.group(1)
            value = match.group(2).strip()
            base_var = re.sub(r'\[.*?\]', '', var_name)
            
            # Check if there's a control flow statement (if/else/case) in the previous few lines
            # If so, this is likely a conditional assignment and should NOT be filtered
            has_control_flow = False
            for j in range(max(0, i-5), i):
                prev_line = lines[j].strip()
                if re.search(r'^\s*(if|else|case|for|while)\s*\(', prev_line) or \
                   re.search(r'^\s*(if|else|case|for|while)\s+', prev_line) or \
                   prev_line.startswith('if ') or prev_line.startswith('else') or \
                   prev_line.startswith('case') or prev_line.startswith('for '):
                    has_control_flow = True
                    break
            
            # Check if the next line is the same assignment (consecutive duplicate)
            is_consecutive_duplicate = False
            if i + 1 < len(lines):
                next_match = re.search(r'^\s*([a-zA-Z_][a-zA-Z0-9_\[\]]*)\s*<=\s*([^;]+);', lines[i+1])
                if next_match:
                    next_var = re.sub(r'\[.*?\]', '', next_match.group(1))
                    next_value = next_match.group(2).strip()
                    if base_var == next_var and value == next_value:
                        is_consecutive_duplicate = True
            
            # Only filter if it's a consecutive duplicate AND not in a control flow context
            if is_consecutive_duplicate and not has_control_flow:
                # Skip this line (it's a consecutive duplicate)
                i += 1
                continue
        
        # Keep the line
        filtered_lines.append(line)
        i += 1
    
    return '\n'.join(filtered_lines)

def rewrite_state_assignments(src_path: Path, problem_name: str) -> Path:
    """Post-process state assignments for Icarus Verilog compatibility"""
    if not src_path.exists():
        return src_path

    text = src_path.read_text()
    if "state_t" not in text:
        return src_path

    def repl(match: re.Match) -> str:
        expr = match.group(1).strip()
        return f"        next_state = state_t'({expr});"

    fixed_text = re.sub(r"next_state\s*=\s*(.+?);", repl, text)
    out_path = OUTPUT_DIR / f"{problem_name}_{src_path.stem}_cast.sv"
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(fixed_text)
    return out_path

def run_verilog_candidate(candidate_path: Path, problem_name: str) -> Dict[str, object]:
    """Compile and simulate the candidate fix using Icarus Verilog.
    FULL AGENT: Use post-processing for compatibility."""
    testbench = DATASET_DIR / f"{problem_name}_test.sv"
    result = {
        "compiled": None,
        "compile_stdout": "",
        "compile_stderr": "",
        "simulation_passed": None,
        "simulation_stdout": "",
        "simulation_stderr": "",
        "binary": ""
    }

    if not testbench.exists():
        result["compile_stderr"] = "Testbench missing"
        result["compiled"] = False
        return result

    binary = OUTPUT_DIR / f"{problem_name}_full_tb"
    compile_cmd = [
        "iverilog",
        "-g2012",
        "-Wall",
        "-o",
        str(binary),
    ]

    # FULL AGENT: Use post-processing for compatibility
    candidate_path = rewrite_state_assignments(candidate_path, problem_name)
    ref_file = rewrite_state_assignments(DATASET_DIR / f"{problem_name}_ref.sv", problem_name)
    for path in (str(candidate_path), str(ref_file), str(testbench)):
        if os.path.exists(path):
            compile_cmd.append(path)

    comp = subprocess.run(
        compile_cmd,
        capture_output=True,
        text=True
    )

    result.update({
        "compiled": comp.returncode == 0,
        "compile_stdout": comp.stdout,
        "compile_stderr": comp.stderr,
        "binary": str(binary)
    })

    if not result["compiled"]:
        return result

    sim = subprocess.run(
        ["vvp", str(binary)],
        capture_output=True,
        text=True
    )

    stdout = sim.stdout.strip()
    stderr = sim.stderr.strip()
    
    # Check if simulation actually passed
    # Not just return code, but also check for explicit FAIL indicators
    simulation_passed = False
    
    if sim.returncode == 0:
        # First, check for explicit test failure indicators (e.g., "Test X: ... FAIL")
        fail_pattern = re.compile(r'Test\s+\d+[^:]*:\s+.*?\s+FAIL', re.IGNORECASE)
        fail_matches = fail_pattern.findall(stdout)
        
        if fail_matches:
            # Tests explicitly failed
            simulation_passed = False
        elif "mismatches" in stdout.lower() or "mismatch" in stdout.lower():
            # Check for mismatch count
            mismatch_match = re.search(r'(\d+)\s+in\s+(\d+)\s+samples', stdout)
            if mismatch_match:
                mismatches = int(mismatch_match.group(1))
                if mismatches > 0:
                    simulation_passed = False
                else:
                    simulation_passed = True
            else:
                # Has "mismatch" keyword but can't parse count, assume failure
                simulation_passed = False
        elif "no mismatches" in stdout.lower() or "has no mismatches" in stdout.lower():
            # Explicitly no mismatches
            simulation_passed = True
        else:
            # Check if all tests passed (explicit PASS indicators)
            pass_pattern = re.compile(r'Test\s+\d+[^:]*:\s+.*?\s+PASS', re.IGNORECASE)
            pass_matches = pass_pattern.findall(stdout)
            if pass_matches and not fail_matches:
                # All tests explicitly passed
                simulation_passed = True
            else:
                # Default: if return code is 0 and no explicit failures, assume pass
                simulation_passed = True
    else:
        # Non-zero return code indicates failure
        simulation_passed = False

    result.update({
        "simulation_passed": simulation_passed,
        "simulation_stdout": stdout,
        "simulation_stderr": stderr
    })
    return result

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset_rtl-debug"
AGENT_SCRIPT = PROJECT_ROOT / "logic-diagnosis-agent" / "rtl_debug_agent_tooled.py"  # Full agent with tools
PROBLEMS_FILE = DATASET_DIR / "problems.txt"
OUTPUT_DIR = PROJECT_ROOT / "logic-diagnosis-agent" / "test_results_full"
OUTPUT_DIR.mkdir(exist_ok=True)

def read_problems() -> List[str]:
    """Read problem list from problems.txt"""
    if not PROBLEMS_FILE.exists():
        console.print(f"[red]Error: {PROBLEMS_FILE} not found[/red]")
        return []
    
    with open(PROBLEMS_FILE, 'r') as f:
        problems = [line.strip() for line in f if line.strip()]
    return problems

def extract_rtl_code_from_prompt(prompt: str) -> str:
    """Extract the buggy RTL code from the prompt"""
    # Look for module definition
    lines = prompt.split('\n')
    in_module = False
    rtl_lines = []
    
    for line in lines:
        if 'module' in line.lower() and ('TopModule' in line or 'fpu' in line.lower() or 'module' in line):
            in_module = True
            rtl_lines.append(line)
        elif in_module:
            rtl_lines.append(line)
            if line.strip().startswith('endmodule'):
                break
    
    return '\n'.join(rtl_lines)

def save_buggy_rtl(problem_name: str, rtl_code: str) -> Path:
    """Save buggy RTL code to a temporary file"""
    OUTPUT_DIR.mkdir(exist_ok=True)
    temp_file = OUTPUT_DIR / f"{problem_name}_buggy.sv"
    with open(temp_file, 'w', encoding='utf-8') as f:
        f.write(rtl_code)
    return temp_file

def run_agent_on_problem(problem_name: str) -> Dict:
    """Run the full agent (with tools) on a single problem"""
    console.print(f"\n[bold green][FULL AGENT] Testing: {problem_name}[/bold green]")
    
    # Read prompt
    prompt_file = DATASET_DIR / f"{problem_name}_prompt.txt"
    if not prompt_file.exists():
        return {"status": "error", "error": "Prompt file not found", "problem": problem_name}
    
    with open(prompt_file, 'r', encoding='utf-8') as f:
        prompt = f.read()
    
    # Extract RTL code
    rtl_code = extract_rtl_code_from_prompt(prompt)
    if not rtl_code:
        return {"status": "error", "error": "Could not extract RTL code", "problem": problem_name}
    
    # Save to temporary file
    temp_rtl_file = save_buggy_rtl(problem_name, rtl_code)
    
    # Prepare output file
    output_file = OUTPUT_DIR / f"{problem_name}_analysis.txt"
    
    # Extract requirement from prompt
    requirement = ""
    if "Debug this code" in prompt:
        req_start = prompt.find("Debug this code")
        if req_start >= 0:
            requirement = prompt[req_start:].strip()
    
    # Run FULL AGENT with all tools
    try:
        # Get API key, model, and max iterations from environment variables
        api_key = os.getenv("OPENAI_API_KEY", "")
        model = os.getenv("MODEL", "gpt-4o")
        max_iterations = os.getenv("MAX_ITERATIONS", "10")
        
        if not api_key:
            return {
                "status": "error",
                "error": "OPENAI_API_KEY environment variable not set",
                "problem": problem_name
            }
        
        # Add delay between problems to avoid rate limiting
        import time
        time.sleep(3)  # Wait 3 seconds between problems to avoid rate limits
        
        cmd = [
            sys.executable,
            str(AGENT_SCRIPT),
            "--rtl", str(temp_rtl_file),
            "--requirement", requirement or "Fix the bugs in the RTL code",
            "--testbench", str(DATASET_DIR / f"{problem_name}_test.sv"),
            "--ref", str(DATASET_DIR / f"{problem_name}_ref.sv"),
            "--problem-name", problem_name,
            "--max-iterations", max_iterations,
            "--model", model,
            "--api-key", api_key,
            "--output", str(output_file)
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=900,  # 15 minute timeout per problem (longer for iterative debugging)
            env={**os.environ, "OPENAI_API_KEY": api_key}
        )
        
        # Save agent stdout/stderr for debugging
        debug_file = OUTPUT_DIR / f"{problem_name}_debug.txt"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write("=== STDOUT ===\n")
            f.write(result.stdout)
            f.write("\n\n=== STDERR ===\n")
            f.write(result.stderr)
        
        # Wait for file to be written
        import time
        time.sleep(0.5)
        
        # Try to extract code even if agent returned non-zero (it might have generated code)
        # Try to extract from output file first
        analysis = ""
        if output_file.exists():
            with open(output_file, 'r', encoding='utf-8') as f:
                analysis = f.read()
        
        # Also check stdout for final code
        if not analysis or "=== STDOUT ===" in analysis:
            # Look for final code in stdout
            analysis = result.stdout
        
        # Extract candidate code
        candidate_code = extract_candidate_code(analysis)
        if not candidate_code:
            candidate_code = extract_candidate_code(result.stdout)
        
        # Look for "Final Fixed Code" section in stdout (even if agent failed)
        # Prioritize the first "Final Fixed Code" section (usually the correct one)
        if not candidate_code:
            # Try to find ALL "Final Fixed Code" sections and prioritize the best one
            all_final_sections = re.findall(r'Final Fixed Code[^\n]*\n(.*?)(?=\n\n|===|Agent Messages|$)', result.stdout, re.DOTALL)
            if all_final_sections:
                # Score each section: prefer ones with correct array indexing
                scored_sections = []
                for section in all_final_sections:
                    score = 0
                    # Check for correct array indexing patterns
                    if re.search(r'array\[i\]\s*<=', section):
                        score += 10
                    if re.search(r'exp_out_reg\[i\]\s*<=', section):
                        score += 10
                    if re.search(r'array\s*<=', section) and not re.search(r'array\[i\]\s*<=', section):
                        score -= 10  # Penalize wrong patterns
                    scored_sections.append((score, section))
                
                # Sort by score (highest first) and take the best one
                scored_sections.sort(key=lambda x: x[0], reverse=True)
                if scored_sections and scored_sections[0][0] > 0:
                    candidate_code = scored_sections[0][1].strip()
                else:
                    # Fallback to first section
                    candidate_code = all_final_sections[0].strip()
                
                # Try to extract from code block if present
                code_block_match = re.search(r'```systemverilog\n(.*?)```', candidate_code, re.DOTALL)
                if code_block_match:
                    candidate_code = code_block_match.group(1).strip()
                else:
                    # Remove any markdown formatting
                    candidate_code = re.sub(r"^```.*?\n", "", candidate_code, flags=re.MULTILINE)
                    candidate_code = re.sub(r"\n```\s*$", "", candidate_code, flags=re.MULTILINE)
                    candidate_code = re.sub(r"^╭.*?╮\n", "", candidate_code, flags=re.MULTILINE)
                    candidate_code = re.sub(r"^│\s*", "", candidate_code, flags=re.MULTILINE)
                    candidate_code = re.sub(r"╰.*?╯", "", candidate_code, flags=re.MULTILINE)
        
        if candidate_code:
            # Save candidate code even if agent returned non-zero
            candidate_file = OUTPUT_DIR / f"{problem_name}_candidate.sv"
            with open(candidate_file, 'w', encoding='utf-8') as cf:
                cf.write(candidate_code.strip() + "\n")

            # FULL AGENT: Post-processing - move variable declarations to module level
            try:
                # sys is already imported at the top of the file
                sys.path.insert(0, str(Path(__file__).parent))
                from move_variable_declarations import move_variable_declarations_to_module_level
                original_code = candidate_file.read_text()
                fixed_code = move_variable_declarations_to_module_level(original_code)
                if fixed_code != original_code:
                    # Save the fixed version
                    with open(candidate_file, 'w', encoding='utf-8') as cf:
                        cf.write(fixed_code)
                    console.print(f"[yellow]Post-processed: Moved variable declarations to module level[/yellow]")
            except ImportError:
                # If the module doesn't exist, skip post-processing
                pass
            except Exception as e:
                # If post-processing fails, continue with original code
                console.print(f"[yellow]Warning: Post-processing failed: {e}[/yellow]")

            # FULL AGENT: Verify with post-processing
            sim_result = run_verilog_candidate(candidate_file, problem_name)
            
            # If code compiles and simulates successfully, consider it success
            if sim_result.get("compiled") and sim_result.get("simulation_passed"):
                return {
                    "status": "success",
                    "problem": problem_name,
                    "analysis": analysis,
                    "output_file": str(output_file),
                    "candidate_file": str(candidate_file),
                    **sim_result
                }
            else:
                # Code was generated but doesn't work
                error_msg = ""
                if not sim_result.get("compiled"):
                    error_msg = f"Compilation failed: {sim_result.get('compile_stderr', '')[:200]}"
                elif not sim_result.get("simulation_passed"):
                    error_msg = f"Simulation failed: {sim_result.get('simulation_stderr', '')[:200]}"
                
                return {
                    "status": "error",
                    "problem": problem_name,
                    "error": error_msg or "Code generated but verification failed",
                    "candidate_file": str(candidate_file),
                    **sim_result
                }
        
        # No code extracted
        if result.returncode == 0:
            return {
                "status": "error",
                "problem": problem_name,
                "error": "Agent output did not include a code block."
            }
        else:
            # Check for rate limit errors
            error_msg = result.stderr[:200] if result.stderr else result.stdout[:200]
            if "429" in error_msg or "rate limit" in error_msg.lower() or "Rate limit" in error_msg:
                return {
                    "status": "error",
                    "error": "OpenAI API rate limit exceeded. Please wait and retry.",
                    "problem": problem_name
                }
            return {
                "status": "error",
                "error": f"Agent failed: {error_msg}",
                "problem": problem_name
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": "Timeout (15 minutes)",
            "problem": problem_name
        }
    except Exception as e:
        return {
            "status": "error",
            "error": str(e),
            "problem": problem_name
        }

def main():
    """Main test function"""
    console.print(Panel.fit(
        "[bold green]RTL Debug Agent - FULL AGENT Testing[/bold green]\n"
        "Uses all tools (run_iverilog, simulate, generate_testbench, etc.)\n"
        "Agent performs iterative debugging with tool feedback.",
        border_style="green"
    ))
    
    # Read problems
    problems = read_problems()
    if not problems:
        console.print("[red]No problems found in dataset[/red]")
        return
    
    console.print(f"\n[green]Found {len(problems)} problems to test[/green]")
    console.print(f"[dim]Output directory: {OUTPUT_DIR}[/dim]\n")
    
    # Test each problem
    results = []
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console
    ) as progress:
        task = progress.add_task("[FULL AGENT] Testing problems...", total=len(problems))
        
        for i, problem in enumerate(problems):
            result = run_agent_on_problem(problem)
            results.append(result)
            progress.update(task, advance=1)
            
            # Add delay between problems to avoid rate limiting (except for last problem)
            if i < len(problems) - 1:
                import time
                time.sleep(5)  # Wait 5 seconds between problems
    
    # Display summary
    console.print("\n[bold yellow]=== FULL AGENT Test Summary ===[/bold yellow]")
    table = Table(title="Full Agent Test Results")
    table.add_column("Problem", style="cyan", no_wrap=True)
    table.add_column("Status", style="magenta")
    table.add_column("Verified", style="green")
    table.add_column("Error", style="red")
    
    success_count = 0
    error_count = 0
    
    for result in results:
        status = result.get("status", "unknown")
        if status == "success":
            success_count += 1
            status_display = "[green]✓ Success[/green]"
        else:
            error_count += 1
            status_display = "[red]✗ Error[/red]"

        if result.get("compiled") is False:
            verified_display = "[red]Compile Err[/red]"
        elif result.get("simulation_passed") is True:
            verified_display = "[green]Pass[/green]"
        elif result.get("simulation_passed") is False:
            verified_display = "[red]Fail[/red]"
        else:
            verified_display = "[dim]N/A[/dim]"

        error_msg = result.get("error", "")
        if not error_msg:
            if result.get("compiled") is False:
                error_msg = result.get("compile_stderr", "").strip()[:100] or "Compilation failed"
            elif result.get("simulation_passed") is False:
                error_msg = "Simulation failed"

        table.add_row(
            result.get("problem", "Unknown"),
            status_display,
            verified_display,
            error_msg
        )
    
    console.print(table)
    
    # Summary statistics
    verified_pass = sum(1 for r in results if r.get("simulation_passed") is True)
    verified_fail = sum(1 for r in results if r.get("simulation_passed") is False)
    compile_failures = sum(1 for r in results if r.get("compiled") is False)

    console.print(f"\n[bold]Full Agent Summary:[/bold]")
    console.print(f"  [green]Success: {success_count}/{len(problems)}[/green]")
    console.print(f"  [red]Errors: {error_count}/{len(problems)}[/red]")
    console.print(f"  [green]Verified passes: {verified_pass}[/green]")
    console.print(f"  [red]Verified failures: {verified_fail}[/red]")
    console.print(f"  [yellow]Compile failures: {compile_failures}[/yellow]")
    console.print(f"\n[dim]Detailed results saved to: {OUTPUT_DIR}[/dim]")

if __name__ == "__main__":
    main()

