#!/usr/bin/env python3
"""
Test script for rtl_debug_agent.py using dataset_rtl-debug
Runs the agent on all problems in the dataset and evaluates results
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
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL)
        for match in matches:
            if "module" in match and "endmodule" in match:
                return match.strip()
    
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

def rewrite_state_assignments(src_path: Path, problem_name: str) -> Path:
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
    """Compile and simulate the candidate fix using Icarus Verilog."""
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

    binary = OUTPUT_DIR / f"{problem_name}_tb"
    compile_cmd = [
        "iverilog",
        "-g2012",
        "-Wall",
        "-o",
        str(binary),
    ]

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

    result.update({
        "simulation_passed": sim.returncode == 0,
        "simulation_stdout": sim.stdout,
        "simulation_stderr": sim.stderr
    })
    return result

# Paths
PROJECT_ROOT = Path(__file__).parent.parent
DATASET_DIR = PROJECT_ROOT / "dataset_rtl-debug"
AGENT_SCRIPT = PROJECT_ROOT / "logic-diagnosis-agent" / "rtl_debug_agent.py"  # Use simple agent (no tools)
PROBLEMS_FILE = DATASET_DIR / "problems.txt"
OUTPUT_DIR = PROJECT_ROOT / "logic-diagnosis-agent" / "test_results"

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
    """Run the agent on a single problem"""
    console.print(f"\n[bold cyan]Testing: {problem_name}[/bold cyan]")
    
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
    
    # Run agent with tooled version
    try:
        # Build command for rtl_debug_agent.py (simple agent, no tools)
        # The agent will just generate code, then we compile and simulate it
        cmd = [
            sys.executable,
            str(AGENT_SCRIPT),
            str(temp_rtl_file),
            "--batch",
            "--output",
            str(output_file),
            "--model", "gpt-4o"
        ]
        
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=600  # 10 minute timeout per problem
        )
        
        # Save agent stdout/stderr for debugging
        debug_file = OUTPUT_DIR / f"{problem_name}_debug.txt"
        with open(debug_file, 'w', encoding='utf-8') as f:
            f.write("=== STDOUT ===\n")
            f.write(result.stdout)
            f.write("\n\n=== STDERR ===\n")
            f.write(result.stderr)
        
        if result.returncode == 0:
            # Agent saves analysis to output_file (specified by --output)
            # This file contains the LLM's response with the fixed code
            # IMPORTANT: Don't overwrite this file! Agent already saved the analysis there.
            # Wait a bit to ensure file is written (agent might still be writing)
            import time
            time.sleep(0.5)
            
            analysis = ""
            if output_file.exists():
                with open(output_file, 'r', encoding='utf-8') as f:
                    analysis = f.read()
            
            # Check if file contains actual analysis (not just stdout/stderr)
            # If it starts with "=== STDOUT ===", it was overwritten somehow
            if analysis.startswith("=== STDOUT ==="):
                # This shouldn't happen, but if it does, try to extract from stdout
                console.print(f"[yellow]Warning: Analysis file was overwritten. Trying to extract from stdout...[/yellow]")
                analysis = result.stdout
            
            # If analysis file is empty or doesn't exist, agent may have failed
            if not analysis or len(analysis.strip()) == 0:
                return {
                    "status": "error",
                    "error": "Analysis file is empty or not created. Check if agent saved the analysis.",
                    "problem": problem_name,
                    "stdout": result.stdout[:500] if result.stdout else "",
                    "stderr": result.stderr[:500] if result.stderr else ""
                }
            
            # Extract candidate code from analysis file (this is where agent saves the LLM response)
            candidate_code = extract_candidate_code(analysis)
            
            # If not found, try extracting from stdout as fallback
            if not candidate_code:
                candidate_code = extract_candidate_code(result.stdout)
            
            # Try to extract from all messages in stdout (agent may output code in different format)
            if not candidate_code:
                # Look for "Final Fixed Code" section
                final_code_match = re.search(r"Final Fixed Code[^\n]*\n(.*?)(?=\n\n|\Z)", result.stdout, re.DOTALL)
                if final_code_match:
                    candidate_code = final_code_match.group(1).strip()
                    # Remove markdown code block markers if present
                    candidate_code = re.sub(r"^```(?:systemverilog)?\s*\n", "", candidate_code, flags=re.MULTILINE)
                    candidate_code = re.sub(r"\n```\s*$", "", candidate_code, flags=re.MULTILINE)
            
            # Try to find code in any code block format
            if not candidate_code:
                # More flexible pattern matching
                patterns = [
                    r"```systemverilog\s*\n(.*?)```",
                    r"```verilog\s*\n(.*?)```",
                    r"```\s*\n(.*?)```",
                    r"module\s+\w+[^`]*?endmodule",
                ]
                for pattern in patterns:
                    matches = re.findall(pattern, result.stdout, re.DOTALL)
                    for match in matches:
                        if "module" in match and "endmodule" in match:
                            candidate_code = match.strip()
                            break
                    if candidate_code:
                        break
            
            if not candidate_code:
                # No code extracted, return error
                return {
                    "status": "success",
                    "problem": problem_name,
                    "analysis": result.stdout[:500] if result.stdout else "No output",
                    "output_file": str(output_file),
                    "error": "Agent output did not include a code block. Check output file for details."
                }
            
            # Code extracted successfully, save and verify
            candidate_file = OUTPUT_DIR / f"{problem_name}_candidate.sv"
            with open(candidate_file, 'w', encoding='utf-8') as cf:
                cf.write(candidate_code.strip() + "\n")

            sim_result = run_verilog_candidate(candidate_file, problem_name)
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
                "error": f"Agent failed: {result.stderr}",
                "problem": problem_name
            }
    except subprocess.TimeoutExpired:
        return {
            "status": "error",
            "error": "Timeout (5 minutes)",
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
        "[bold cyan]RTL Debug Agent - Dataset Testing[/bold cyan]\n"
        "Testing agent on dataset_rtl-debug problems",
        border_style="cyan"
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
        task = progress.add_task("Testing problems...", total=len(problems))
        
        for problem in problems:
            result = run_agent_on_problem(problem)
            results.append(result)
            progress.update(task, advance=1)
    
    # Display summary
    console.print("\n[bold yellow]=== Test Summary ===[/bold yellow]")
    table = Table(title="Test Results")
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
                error_msg = result.get("compile_stderr", "").strip() or "Compilation failed"
            elif result.get("simulation_passed") is False:
                error_msg = (result.get("simulation_stdout", "") + result.get("simulation_stderr", "")).strip() or "Simulation failed"

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

    console.print(f"\n[bold]Summary:[/bold]")
    console.print(f"  [green]Success: {success_count}/{len(problems)}[/green]")
    console.print(f"  [red]Errors: {error_count}/{len(problems)}[/red]")
    console.print(f"  [green]Verified passes: {verified_pass}[/green]")
    console.print(f"  [red]Verified failures: {verified_fail}[/red]")
    console.print(f"  [yellow]Compile failures: {compile_failures}[/yellow]")
    console.print(f"\n[dim]Detailed results saved to: {OUTPUT_DIR}[/dim]")

if __name__ == "__main__":
    main()
