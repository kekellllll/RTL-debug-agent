#!/usr/bin/env python3
"""
DFG (Data Flow Graph) analyzer based on pyverilog.
Uses the pyverilog library to parse SystemVerilog code and generate a DFG.
"""

import re
from typing import Dict, List, Set, Tuple, Optional, Any

try:
    from pyverilog.vparser.parser import parse
    from pyverilog.vparser.ast import *
    PYVERILOG_AVAILABLE = True
except ImportError:
    PYVERILOG_AVAILABLE = False


def extract_signals_from_ast(ast: Node, code: str = "") -> Set[str]:
    """Extract signal declarations from the pyverilog AST and from raw code."""
    signals = set()
    
    # Method 1: extract from AST (port and declared signals)
    def traverse_ast(node):
        if isinstance(node, Variable):
            # Direct variable node (Input, Output, Reg, Wire, etc.)
            signals.add(node.name)
        elif isinstance(node, Decl):
            # Handle declarations: logic, reg, wire, integer, etc.
            # In pyverilog, Decl node children are Variable nodes
            for child in node.children():
                if isinstance(child, Variable):
                    signals.add(child.name)
                else:
                    # Recurse into other children
                    traverse_ast(child)
        else:
            # Recurse into children
            for child in node.children():
                traverse_ast(child)
    
    traverse_ast(ast)
    
    # Method 2: supplement with regex on raw code (pyverilog may not fully parse all SystemVerilog)
    if code:
        # Extract logic, reg, wire, integer declarations.
        # Note: need to exclude 'signed' and 'unsigned' keywords.
        signal_patterns = [
            r'\b(?:logic|reg|wire|integer|int)\s+(?:signed\s+)?(?:unsigned\s+)?(?:\[[^\]]+\]\s+)?(\w+)',
        ]
        for pattern in signal_patterns:
            for match in re.finditer(pattern, code):
                signal_name = match.group(1)
                # Exclude keywords and type names
                if signal_name not in ['signed', 'unsigned', 'logic', 'reg', 'wire', 'integer', 'int']:
                    signals.add(signal_name)
    
    return signals


def extract_assignments_from_ast(ast: Node) -> List[Tuple[str, str]]:
    """Extract assignments from the pyverilog AST as (lhs, rhs_string)."""
    assignments = []
    
    def get_identifier_name(expr) -> Optional[str]:
        """Extract identifier name (for signal matching)."""
        if isinstance(expr, Identifier):
            return expr.name
        elif isinstance(expr, Partselect):
            return get_identifier_name(expr.var)
        elif isinstance(expr, Pointer):
            return get_identifier_name(expr.var)
        return None
    
    def get_expression_string(expr) -> str:
        """Convert an expression node to a string."""
        if expr is None:
            return ""
        if isinstance(expr, str):
            return expr
        elif isinstance(expr, IntConst):
            return str(expr.value)
        elif isinstance(expr, Identifier):
            return expr.name
        elif isinstance(expr, Partselect):
            base = get_expression_string(expr.var)
            msb = get_expression_string(expr.msb)
            lsb = get_expression_string(expr.lsb)
            return f"{base}[{msb}:{lsb}]"
        elif isinstance(expr, Pointer):
            base = get_expression_string(expr.var)
            ptr = get_expression_string(expr.ptr)
            return f"{base}[{ptr}]"
        elif isinstance(expr, Concat):
            items = [get_expression_string(item) for item in expr.list]
            return "{" + ", ".join(items) + "}"
        elif isinstance(expr, Cond):
            cond = get_expression_string(expr.cond)
            true_expr = get_expression_string(expr.true_value)
            false_expr = get_expression_string(expr.false_value)
            return f"({cond} ? {true_expr} : {false_expr})"
        elif isinstance(expr, Rvalue):
            # Rvalue node wraps the right-hand-side expression
            if hasattr(expr, 'var'):
                return get_expression_string(expr.var)
            else:
                return str(expr)
        else:
            # For other node types (including operators), rely on __str__
            # which pyverilog AST nodes implement
            try:
                return str(expr)
            except:
                return repr(expr)
    
    def get_lvalue_string(lvalue) -> str:
        """Get a string for the left-hand side expression."""
        # pyverilog wraps lvalues in Lvalue nodes
        if isinstance(lvalue, Lvalue):
            # Extract the underlying variable
            if hasattr(lvalue, 'var'):
                var = lvalue.var
                if isinstance(var, Identifier):
                    return var.name
                else:
                    # Recurse into nested structure
                    return get_lvalue_string(var)
            else:
                # Fallback: stringify and then try to extract the signal name
                lvalue_str = str(lvalue)
                match = re.match(r'(\w+)', lvalue_str)
                if match:
                    return match.group(1)
                return lvalue_str
        elif isinstance(lvalue, Identifier):
            return lvalue.name
        elif isinstance(lvalue, Partselect):
            base = get_expression_string(lvalue.var)
            msb = get_expression_string(lvalue.msb)
            lsb = get_expression_string(lvalue.lsb)
            return f"{base}[{msb}:{lsb}]"
        elif isinstance(lvalue, Pointer):
            base = get_expression_string(lvalue.var)
            ptr = get_expression_string(lvalue.ptr)
            return f"{base}[{ptr}]"
        else:
            # Fallback: attempt to extract the signal name
            lvalue_str = str(lvalue)
            match = re.match(r'(\w+)', lvalue_str)
            if match:
                return match.group(1)
            return lvalue_str
    
    def traverse(node):
        if isinstance(node, BlockingSubstitution):
            # Blocking assignment (used in always_comb)
            lhs = get_lvalue_string(node.left)
            # pyverilog wraps the RHS in an Rvalue
            if isinstance(node.right, Rvalue):
                rhs = get_expression_string(node.right.var)
            else:
                rhs = get_expression_string(node.right)
            assignments.append((lhs, rhs))
        elif isinstance(node, NonblockingSubstitution):
            # Non-blocking assignment (used in always_ff)
            lhs = get_lvalue_string(node.left)
            if isinstance(node.right, Rvalue):
                rhs = get_expression_string(node.right.var)
            else:
                rhs = get_expression_string(node.right)
            assignments.append((lhs, rhs))
        elif isinstance(node, Assign):
            # Continuous assignment (assign statement)
            lhs = get_lvalue_string(node.left)
            rhs = get_expression_string(node.right)
            assignments.append((lhs, rhs))
        
        # Recurse into children
        for child in node.children():
            traverse(child)
    
    traverse(ast)
    return assignments


def extract_conditions_from_ast(ast: Node) -> List[str]:
    """Extract conditional expressions from the pyverilog AST."""
    conditions = []
    
    def get_expression_string(expr) -> str:
        """Convert an expression node to a string."""
        if isinstance(expr, str):
            return expr
        elif isinstance(expr, Identifier):
            return expr.name
        elif isinstance(expr, IntConst):
            return str(expr.value)
        else:
            # For other node types (including operators), rely on __str__
            try:
                return str(expr)
            except:
                return repr(expr)
    
    def traverse(node):
        if isinstance(node, IfStatement):
            # Condition of an if statement
            cond = get_expression_string(node.cond)
            conditions.append(cond)
        elif isinstance(node, CaseStatement):
            # Condition of a case statement
            comp = get_expression_string(node.comp)
            conditions.append(comp)
        elif isinstance(node, ForStatement):
            # Condition of a for-loop
            if hasattr(node, 'cond') and node.cond:
                cond = get_expression_string(node.cond)
                conditions.append(cond)
        
        # Recurse into children
        for child in node.children():
            traverse(child)
    
    traverse(ast)
    return conditions


def find_output_assignments_in_always(always_node: Node, output_signals: Set[str]) -> List[str]:
    """Find assignments to output signals inside an always block."""
    output_assignments = []
    
    def get_lvalue_string(lvalue) -> str:
        """Get lvalue as a simple signal name (simplified)."""
        # pyverilog wraps lvalues in Lvalue nodes
        if isinstance(lvalue, Lvalue):
            if hasattr(lvalue, 'var'):
                var = lvalue.var
                if isinstance(var, Identifier):
                    return var.name
                else:
                    # 递归处理
                    return get_lvalue_string(var)
        elif isinstance(lvalue, Identifier):
            return lvalue.name
        elif isinstance(lvalue, Partselect):
            if isinstance(lvalue.var, Identifier):
                return lvalue.var.name
        elif isinstance(lvalue, Pointer):
            if isinstance(lvalue.var, Identifier):
                return lvalue.var.name
        return None
    
    def traverse(node):
        if isinstance(node, BlockingSubstitution):
            lhs_name = get_lvalue_string(node.left)
            if lhs_name and lhs_name in output_signals:
                output_assignments.append(lhs_name)
        elif isinstance(node, NonblockingSubstitution):
            lhs_name = get_lvalue_string(node.left)
            if lhs_name and lhs_name in output_signals:
                output_assignments.append(lhs_name)
        elif isinstance(node, Assign):
            lhs_name = get_lvalue_string(node.left)
            if lhs_name and lhs_name in output_signals:
                output_assignments.append(lhs_name)
        
        # Recurse into children
        for child in node.children():
            traverse(child)
    
    traverse(always_node)
    return output_assignments


def build_dfg_from_pyverilog_ast(ast: Node, signals: Set[str], code: str = "") -> Dict[str, Set[str]]:
    """Build a DFG from the pyverilog AST."""
    # Extract output signals (used to associate conditions with outputs)
    output_signals = set()
    output_pattern = r'output\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
    for match in re.finditer(output_pattern, code):
        output_signals.add(match.group(1))
    
    # Ensure all signals (including outputs) are present in the DFG
    all_signals = signals | output_signals
    dfg = {signal: set() for signal in all_signals}
    
    # Extract dependencies from assignments
    assignments = extract_assignments_from_ast(ast)
    for lhs, rhs in assignments:
        # Extract the base signal name on the LHS (strip indices)
        lhs_signal = re.match(r'(\w+)', lhs)
        if lhs_signal:
            lhs_name = lhs_signal.group(1)
            if lhs_name in dfg:
                # Check which signals are used in the RHS
                for signal in signals:
                    pattern = r'\b' + re.escape(signal) + r'\b'
                    if re.search(pattern, rhs):
                        dfg[lhs_name].add(signal)
    
    # Extract dependencies from conditional expressions (key improvement)
    def traverse_always(node):
        if isinstance(node, (Always, AlwaysComb, AlwaysFF)):
            # Find output assignments inside this always block
            always_outputs = find_output_assignments_in_always(node, output_signals)
            
            # Find conditional expressions inside this always block
            conditions = []
            def find_conditions(n):
                if isinstance(n, IfStatement):
                    # Extract condition expression as string
                    cond_str = str(n.cond)
                    conditions.append(cond_str)
                elif isinstance(n, CaseStatement):
                    # Condition of a case statement
                    if hasattr(n, 'comp'):
                        cond_str = str(n.comp)
                        conditions.append(cond_str)
                for child in n.children():
                    find_conditions(child)
            
            find_conditions(node)
            
            # If there are output assignments and conditions, add dependencies
            if always_outputs and conditions:
                # Deduplicate output signals
                always_outputs = list(set(always_outputs))
                for condition in conditions:
                    for signal in signals:
                        pattern = r'\b' + re.escape(signal) + r'\b'
                        if re.search(pattern, condition):
                            # Signals appearing in the conditions influence outputs
                            for output_sig in always_outputs:
                                if output_sig in dfg:
                                    dfg[output_sig].add(signal)
        
        # Recurse into children
        for child in node.children():
            traverse_always(child)
    
    traverse_always(ast)
    
    return dfg


def analyze_data_flow_pyverilog(code: str) -> Dict[str, Any]:
    """Analyze data flow using pyverilog."""
    if not PYVERILOG_AVAILABLE:
        raise ImportError("pyverilog is not available. Please install it: pip install pyverilog")
    
    try:
        # Parse the code
        ast, directives = parse([code])
        
        signals = extract_signals_from_ast(ast, code)  # pass code to supplement signal extraction
        assignments = extract_assignments_from_ast(ast)
        dfg = build_dfg_from_pyverilog_ast(ast, signals, code)
        
        # Extract input and output signals
        output_signals = set()
        output_pattern = r'output\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
        for match in re.finditer(output_pattern, code):
            output_signals.add(match.group(1))
        
        input_signals = set()
        input_pattern = r'input\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
        for match in re.finditer(input_pattern, code):
            input_signals.add(match.group(1))
        
        # Analyze key control signals
        warnings = []
        key_signals = {'sign', 'reset', 'enable', 'valid', 'ready'}
        for key_signal in key_signals:
            if key_signal in signals:
                used_in_output = False
                for output_sig in output_signals:
                    if output_sig in dfg and key_signal in dfg[output_sig]:
                        used_in_output = True
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
    
    except Exception as e:
        # If pyverilog parsing fails, propagate an explicit exception
        raise Exception(f"pyverilog parsing failed: {str(e)}")


if __name__ == '__main__':
    # 测试
    test_code = """
module TopModule (
    input logic [31:0] fp32_in,
    output logic [7:0] integer_out
);
    logic sign;
    logic [7:0] integer_raw;
    localparam BIAS = 8'd127;
    
    always_comb begin
        if (sign == 1'b1) begin
            integer_out = BIAS - integer_raw - 8'd1;
        end else begin
            integer_out = integer_raw + BIAS;
        end
    end
endmodule
"""
    
    try:
        result = analyze_data_flow_pyverilog(test_code)
        print("Signals:", result['signals'])
        print("DFG:", result['dfg'])
        print("Warnings:", result['warnings'])
    except Exception as e:
        print(f"Error: {e}")

