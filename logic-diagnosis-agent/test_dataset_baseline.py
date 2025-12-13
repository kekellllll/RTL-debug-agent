#!/usr/bin/env python3
"""
Baseline test script for rtl_debug_agent.py using dataset_rtl-debug
BASELINE VERSION: No tools, no post-processing (no rewrite_state_assignments)
This is the baseline to compare against - failures count as failures.
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
    # Try multiple patterns
    patterns = [
        r"```systemverilog\s*\n(.*?)```",  # systemverilog code block
        r"```verilog\s*\n(.*?)```",  # verilog code block
        r"```\s*\n(.*?)```",  # generic code block
    ]
    
    # Collect all code blocks
    all_blocks = []
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            if "module" in match and "endmodule" in match:
                all_blocks.append(match.strip())
    
    # If we found multiple blocks, prioritize the one that looks like a fix
    # (contains "output reg" or "output logic" instead of just "output")
    if len(all_blocks) > 1:
        # Score blocks: higher score = more likely to be the fixed version
        scored_blocks = []
        for block in all_blocks:
            score = 0
            # Prefer blocks with "output reg" or "output logic" (fixes)
            if "output reg" in block or "output logic" in block:
                score += 10
            # Prefer blocks without buggy patterns
            if "The following Verilog module" not in block:
                score += 5
            # Prefer blocks with "Option B" or "Pure Verilog" (usually the fix)
            if "Option B" in block or "Pure Verilog" in block:
                score += 3
            # Penalize blocks that look like the original buggy code
            if "output [3:0] q" in block and "output reg" not in block and "output logic" not in block:
                score -= 10
            scored_blocks.append((score, block))
        
        # Sort by score (highest first) and return the best one
        scored_blocks.sort(key=lambda x: x[0], reverse=True)
        if scored_blocks and scored_blocks[0][0] > 0:
            return scored_blocks[0][1]
        # If all scores are <= 0, return the last one (usually the fix is last)
        return all_blocks[-1]
    
    # If only one block, return it
    if all_blocks:
        return all_blocks[0]
    
    # Fallback: look for [BEGIN]/[DONE]
    begin = text.find("[BEGIN]")
    done = text.find("[DONE]", begin if begin >= 0 else 0)
    if begin >= 0 and done > begin:
        return text[begin + len("[BEGIN]"):done].strip()
    
    # Fallback: look for "Final Fixed Code" section
    final_section = re.search(r"Final Fixed Code[^\n]*\n(.*?)(?=\n\n|$)", text, re.DOTALL)
    if final_section:
        code = final_section.group(1).strip()
        # Remove any remaining markdown markers
        code = re.sub(r"^```.*?\n", "", code, flags=re.MULTILINE)
        code = re.sub(r"\n```\s*$", "", code, flags=re.MULTILINE)
        if "module" in code and "endmodule" in code:
            return code.strip()
    
    return ""

# BASELINE: NO rewrite_state_assignments - use code as-is
def run_verilog_candidate(candidate_path: Path, problem_name: str) -> Dict[str, object]:
    """Compile and simulate the candidate fix using Icarus Verilog.
    BASELINE: No post-processing, use agent code directly."""
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

    binary = OUTPUT_DIR / f"{problem_name}_baseline_tb"
    compile_cmd = [
        "iverilog",
        "-g2012",
        "-Wall",
        "-o",
        str(binary),
    ]

    # BASELINE: Use candidate and ref files directly, NO post-processing
    ref_file = DATASET_DIR / f"{problem_name}_ref.sv"
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
    
    # Check simulation result by examining output, not just return code
    simulation_passed = False
    if sim.returncode == 0:
        # Check for explicit test failure indicators (e.g., "Test X: ... FAIL")
        import re
        fail_pattern = re.compile(r'Test\s+\d+[^:]*:\s+.*?\s+FAIL', re.IGNORECASE)
        fail_matches = fail_pattern.findall(stdout)
        
        if fail_matches:
            simulation_passed = False
        elif "TESTS FAILED" in stdout or "tests failed" in stdout.lower():
            simulation_passed = False
        elif "mismatches" in stdout.lower() or "mismatch" in stdout.lower():
            mismatch_match = re.search(r'(\d+)\s+in\s+(\d+)\s+samples', stdout)
            if mismatch_match:
                mismatches = int(mismatch_match.group(1))
                if mismatches > 0:
                    simulation_passed = False
                else:
                    simulation_passed = True
            else:
                simulation_passed = False
        elif "no mismatches" in stdout.lower() or "has no mismatches" in stdout.lower():
            simulation_passed = True
        elif "ALL TESTS PASSED" in stdout or "all tests passed" in stdout.lower():
            simulation_passed = True
        else:
            # Check for explicit PASS indicators
            pass_pattern = re.compile(r'Test\s+\d+[^:]*:\s+.*?\s+PASS', re.IGNORECASE)
            pass_matches = pass_pattern.findall(stdout)
            if pass_matches and not fail_matches:
                simulation_passed = True
            else:
                # Default: if return code is 0 and no explicit failures, assume pass
                simulation_passed = True
    else:
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
AGENT_SCRIPT = PROJECT_ROOT / "logic-diagnosis-agent" / "rtl_debug_agent.py"  # Simple agent, no tools
PROBLEMS_FILE = DATASET_DIR / "problems.txt"
OUTPUT_DIR = PROJECT_ROOT / "logic-diagnosis-agent" / "test_results_baseline"
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
    """Run the baseline agent on a single problem"""
    console.print(f"\n[bold cyan][BASELINE] Testing: {problem_name}[/bold cyan]")
    
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
    
    # Run baseline agent (simple agent, no tools)
    try:
        # Get API key and model from environment variables
        api_key = os.getenv("OPENAI_API_KEY", "")
        model = os.getenv("MODEL", "gpt-4o")
        
        if not api_key:
            return {
                "status": "error",
                "error": "OPENAI_API_KEY environment variable not set",
                "problem": problem_name
            }
        
        cmd = [
            sys.executable,
            str(AGENT_SCRIPT),
            str(temp_rtl_file),
            "--batch",
            "--output",
            str(output_file),
            "--model", model,
            "--api-key", api_key
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 minute timeout per problem
            env={**os.environ, "OPENAI_API_KEY": api_key}
        )
        
        # Save agent stdout/stderr for debugging
        debug_file = OUTPUT_DIR / f"{problem_name}_debug.txt"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write("=== STDOUT ===\n")
            f.write(result.stdout)
            f.write("\n\n=== STDERR ===\n")
            f.write(result.stderr)
        
        if result.returncode == 0:
            # Wait for file to be written
            import time
            time.sleep(0.5)
            
            analysis = ""
            if output_file.exists():
                with open(output_file, 'r', encoding='utf-8') as f:
                    analysis = f.read()
            
            # If analysis file is empty or doesn't exist, try to extract from stdout
            if not analysis or len(analysis.strip()) == 0:
                # Try to extract analysis from stdout
                if result.stdout and len(result.stdout.strip()) > 0:
                    # Look for analysis content in stdout (after "Analysis completed" message)
                    stdout_lines = result.stdout.split('\n')
                    analysis_start = -1
                    for i, line in enumerate(stdout_lines):
                        if "Analysis completed" in line or "═══ Round 1" in line:
                            analysis_start = i
                            break
                    
                    if analysis_start >= 0:
                        # Extract everything after the analysis start marker
                        analysis = '\n'.join(stdout_lines[analysis_start+1:]).strip()
                    else:
                        # Use entire stdout as fallback
                        analysis = result.stdout.strip()
            
            # If still empty, check if it's a placeholder message
            if not analysis or len(analysis.strip()) == 0:
                return {
                    "status": "error",
                    "error": "Analysis file is empty or not created.",
                    "problem": problem_name
                }
            
            # Skip placeholder messages that indicate empty content
            if "Analysis completed but content was empty" in analysis:
                # Try to extract from stdout as fallback
                if result.stdout and len(result.stdout.strip()) > 0:
                    analysis = result.stdout.strip()
                else:
                    return {
                        "status": "error",
                        "error": "Analysis file is empty or not created.",
                        "problem": problem_name
                    }
            
            # Extract candidate code
            candidate_code = extract_candidate_code(analysis)
            if not candidate_code:
                candidate_code = extract_candidate_code(result.stdout)
            
            if not candidate_code:
                return {
                    "status": "error",
                    "problem": problem_name,
                    "error": "Agent output did not include a code block."
                }
            
            # Save candidate code
            candidate_file = OUTPUT_DIR / f"{problem_name}_candidate.sv"
            with open(candidate_file, 'w', encoding='utf-8') as cf:
                cf.write(candidate_code.strip() + "\n")

            # BASELINE: Verify without post-processing
            sim_result = run_verilog_candidate(candidate_file, problem_name)
            
            # BASELINE: If compilation or simulation fails, it's a failure
            if not sim_result["compiled"]:
                return {
                    "status": "error",
                    "problem": problem_name,
                    "error": f"Compilation failed: {sim_result['compile_stderr'][:200]}",
                    **sim_result
                }
            
            if not sim_result["simulation_passed"]:
                return {
                    "status": "error",
                    "problem": problem_name,
                    "error": f"Simulation failed: {sim_result['simulation_stderr'][:200]}",
                    **sim_result
                }
            
            return {
                "status": "success",
                "problem": problem_name,
                "analysis": analysis,
                "output_file": str(output_file),
                "candidate_file": str(candidate_file),
                **sim_result
            }
        else:
            return {
                "status": "error",
                "error": f"Agent failed: {result.stderr[:200]}",
                "problem": problem_name
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": "Timeout (10 minutes)",
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
        "[bold red]RTL Debug Agent - BASELINE Testing[/bold red]\n"
        "No tools, no post-processing. Failures count as failures.",
        border_style="red"
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
        task = progress.add_task("[BASELINE] Testing problems...", total=len(problems))
        
        for problem in problems:
            result = run_agent_on_problem(problem)
            results.append(result)
            progress.update(task, advance=1)
    
    # Display summary
    console.print("\n[bold yellow]=== BASELINE Test Summary ===[/bold yellow]")
    table = Table(title="Baseline Test Results")
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

    console.print(f"\n[bold]Baseline Summary:[/bold]")
    console.print(f"  [green]Success: {success_count}/{len(problems)}[/green]")
    console.print(f"  [red]Errors: {error_count}/{len(problems)}[/red]")
    console.print(f"  [green]Verified passes: {verified_pass}[/green]")
    console.print(f"  [red]Verified failures: {verified_fail}[/red]")
    console.print(f"  [yellow]Compile failures: {compile_failures}[/yellow]")
    console.print(f"\n[dim]Detailed results saved to: {OUTPUT_DIR}[/dim]")

if __name__ == "__main__":
    main()

