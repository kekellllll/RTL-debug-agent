#!/usr/bin/env python3
"""
Simple DFG (Data Flow Graph) analyzer.
Used to detect logic issues such as missing signal usage.
"""

import re
from typing import Dict, List, Set, Tuple


def extract_signals(code: str) -> Set[str]:
    """Extract signal names declared in the code."""
    signals = set()
    
    # Match signal declarations: logic sign; logic [7:0] var; integer var;
    patterns = [
        r'(?:logic|reg|wire|integer|int)\s+(?:signed\s+)?(?:\[[^\]]+\]\s+)?(\w+)\s*;',
        r'(?:logic|reg|wire|integer|int)\s+(\w+)\s*;',
    ]
    
    for pattern in patterns:
        matches = re.finditer(pattern, code)
        for match in matches:
            signals.add(match.group(1))
    
    return signals


def extract_assignments(code: str) -> List[Tuple[str, str]]:
    """Extract assignment relations as (lhs, rhs_expression)."""
    assignments = []
    
    # Match assignments: variable = expression;
    # Includes both blocking and non-blocking assignments.
    pattern = r'(\w+)\s*(?:<=|=)\s*([^;]+);'
    matches = re.finditer(pattern, code)
    
    for match in matches:
        lhs = match.group(1)
        rhs = match.group(2).strip()
        assignments.append((lhs, rhs))
    
    return assignments


def extract_conditions(code: str) -> List[str]:
    """Extract conditional expressions (if, case, while, etc.)."""
    conditions = []
    
    # Match if conditions: if (condition) or if condition
    if_pattern = r'if\s*\(([^)]+)\)'
    for match in re.finditer(if_pattern, code):
        conditions.append(match.group(1))
    
    # Match case conditions: case (expression) or case expression
    case_pattern = r'case\s*\(?([^:)]+)\)?'
    for match in re.finditer(case_pattern, code):
        conditions.append(match.group(1))
    
    # Match while conditions: while (condition)
    while_pattern = r'while\s*\(([^)]+)\)'
    for match in re.finditer(while_pattern, code):
        conditions.append(match.group(1))
    
    return conditions


def build_dfg(signals: Set[str], assignments: List[Tuple[str, str]], code: str = "") -> Dict[str, Set[str]]:
    """Build data flow graph: {signal: {used_signals}}."""
    dfg = {signal: set() for signal in signals}
    
    # Extract dependencies from assignments
    for lhs, rhs in assignments:
        if lhs in dfg:
            # Check which signals are used in rhs
            for signal in signals:
                # Use word boundaries to avoid partial matches
                pattern = r'\b' + re.escape(signal) + r'\b'
                if re.search(pattern, rhs):
                    dfg[lhs].add(signal)
    
    # Extract dependencies from condition expressions
    # (important for detecting signals only used in conditions).
    if code:
        conditions = extract_conditions(code)
        for condition in conditions:
            # Check which signals are used in the condition
            for signal in signals:
                pattern = r'\b' + re.escape(signal) + r'\b'
                if re.search(pattern, condition):
                    # If a signal appears in a condition, treat it as affecting outputs.
                    # Here, we conservatively mark all outputs as depending on it.
                    for output_sig in dfg.keys():
                        # Only mark outputs, since conditions influence outputs.
                        if output_sig in ['integer_out', 'frac_out'] or 'out' in output_sig.lower():
                            dfg[output_sig].add(signal)
    
    return dfg


def analyze_data_flow(code: str) -> Dict[str, any]:
    """Analyze data flow in the given RTL code."""
    # Priority 1: use pyverilog (most accurate, full syntax support)
    try:
        from pyverilog_dfg_analyzer import analyze_data_flow_pyverilog
        result = analyze_data_flow_pyverilog(code)
        return result
    except Exception:
        # If pyverilog parsing fails, fall back to simpler analyzers
        pass
    
    # Priority 2: use custom AST-based analyzer
    try:
        from ast_based_dfg_analyzer import analyze_data_flow_ast
        result = analyze_data_flow_ast(code)
        # Remove AST node from result (not needed by callers)
        if 'ast' in result:
            del result['ast']
        return result
    except Exception:
        # If AST-based parsing fails, fall back to regex-based method
        pass
    
    # Regex-based fallback
    signals = extract_signals(code)
    assignments = extract_assignments(code)
    dfg = build_dfg(signals, assignments, code)  # pass code to detect conditions
    
    # Find output signals
    output_signals = set()
    output_pattern = r'output\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
    for match in re.finditer(output_pattern, code):
        output_signals.add(match.group(1))
    
    # Find input signals
    input_signals = set()
    input_pattern = r'input\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
    for match in re.finditer(input_pattern, code):
        input_signals.add(match.group(1))
    
    # Analyze usage of key control signals
    warnings = []
    
    # Check whether key signals (e.g., sign) are used in output computations
    key_signals = {'sign', 'reset', 'enable', 'valid', 'ready'}
    for key_signal in key_signals:
        if key_signal in signals:
            # Check whether the key signal is used in output computations
            # (including assignments and conditions).
            used_in_output = False
            
            # Method 1: check whether it appears in dependencies of output signals
            for output_sig in output_signals:
                if output_sig in dfg and key_signal in dfg[output_sig]:
                    used_in_output = True
                    break
            
            # Method 2: check for use in condition expressions that may affect outputs
            if not used_in_output:
                # Look for conditions of the form if (key_signal ...) or if (... key_signal ...)
                # inside always_comb blocks (since always_comb drives outputs).
                condition_pattern = r'if\s*\([^)]*\b' + re.escape(key_signal) + r'\b[^)]*\)'
                if re.search(condition_pattern, code):
                    # Check whether this condition is inside an always_comb block.
                    # If the condition is in always_comb and that block assigns outputs,
                    # then we treat the key signal as used.
                    always_blocks = re.finditer(r'always_comb\s+begin(.*?)end', code, re.DOTALL)
                    for always_match in always_blocks:
                        always_content = always_match.group(1)
                        # Check whether the condition appears inside this always block
                        if re.search(condition_pattern, always_content):
                            # Check whether this always block has assignments to outputs
                            for output_sig in output_signals:
                                if re.search(r'\b' + re.escape(output_sig) + r'\s*(?:<=|=)', always_content):
                                    used_in_output = True
                                    break
                        if used_in_output:
                            break
            
            if not used_in_output:
                warnings.append({
                    'type': 'unused_key_signal',
                    'signal': key_signal,
                    'message': f'Key signal {key_signal} exists but is not used in output computations; this may indicate a logic bug.'
                })
    
    # Check for unused signals
    used_signals = set()
    for deps in dfg.values():
        used_signals.update(deps)
    
    unused_signals = signals - used_signals - output_signals
    if unused_signals:
        warnings.append({
            'type': 'unused_signals',
            'signals': unused_signals,
            'message': f'Unused signals: {unused_signals}'
        })
    
    return {
        'signals': signals,
        'input_signals': input_signals,
        'output_signals': output_signals,
        'dfg': dfg,
        'warnings': warnings
    }


def analyze_code_for_agent(code: str) -> str:
    """Generate a human-readable analysis report for the agent."""
    analysis = analyze_data_flow(code)
    
    report = []
    report.append("=== DATA FLOW ANALYSIS REPORT ===\n")
    
    if analysis['warnings']:
        report.append("⚠️  WARNINGS:\n")
        for warning in analysis['warnings']:
            report.append(f"  - {warning['message']}\n")
        report.append("\n")
    
    report.append("Signal dependencies:\n")
    for signal, deps in analysis['dfg'].items():
        if deps:
            report.append(f"  {signal} depends on: {', '.join(deps)}\n")
    
    return ''.join(report)


if __name__ == '__main__':
    # Example for manual testing
    test_code = """
module TopModule (
    input logic [31:0] fp32_in,
    output logic [7:0] integer_out
);
    logic sign;
    logic [7:0] int_mag;
    
    always_comb begin
        int_mag = 8'd100;
        integer_out = int_mag;  // ❌ sign is not used
    end
endmodule
"""
    
    print(analyze_code_for_agent(test_code))

