#!/usr/bin/env python3
"""
Logic verification utility: verify whether logic computations in RTL code are correct.
"""

import re
from typing import Dict, List, Optional, Tuple


def verify_shift_calculation(code: str, expected_pattern: str = "BIAS - exponent") -> Dict:
    """Verify whether shift calculations are correct."""
    # Find all assignments related to shift calculations
    shift_patterns = [
        r'(\w+)\s*=\s*([^;]+);',  # 变量赋值
    ]
    
    issues = []
    warnings = []
    
    # Look for assignments to shift_amt or similar variables
    for pattern in shift_patterns:
        matches = re.finditer(pattern, code)
        for match in matches:
            var_name = match.group(1)
            assignment = match.group(2)
            
            # Check if this is a shift-related calculation
            if 'shift' in var_name.lower() and ('BIAS' in assignment or 'exponent' in assignment):
                # Check whether an incorrect formula is used
                if '19 - e_unbiased' in assignment or '19 - e' in assignment:
                    issues.append({
                        'type': 'wrong_shift_formula',
                        'variable': var_name,
                        'assignment': assignment,
                        'expected': expected_pattern,
                        'message': f"Shift calculation uses wrong formula: {assignment}. Should use {expected_pattern}"
                    })
                elif expected_pattern in assignment:
                    warnings.append({
                        'type': 'correct_shift_formula',
                        'variable': var_name,
                        'assignment': assignment,
                        'message': f"Shift calculation looks correct: {assignment}"
                    })
    
    return {
        'issues': issues,
        'warnings': warnings,
        'has_issues': len(issues) > 0
    }


def verify_exponent_zero_handling(code: str) -> Dict:
    """Verify handling of the case exponent == 0."""
    issues = []
    
    # Look for handling of the condition exponent == 0
    exp_zero_pattern = r'if\s*\(\s*exponent\s*==\s*(?:8\'d0|0)\s*\)'
    matches = list(re.finditer(exp_zero_pattern, code, re.IGNORECASE))
    
    if not matches:
        issues.append({
            'type': 'missing_exp_zero_check',
            'message': "No explicit check for exponent == 0 found"
        })
    else:
        # Check whether sign encoding is applied after the exponent == 0 block
        for match in matches:
            start_pos = match.end()
            # 找到对应的 end
            end_pos = find_block_end(code, start_pos)
            block_content = code[start_pos:end_pos]
            
            # Check whether there is sign encoding after this block
            after_block = code[end_pos:end_pos+500]
            if 'sign' in after_block and 'BIAS' in after_block:
                # Check whether there is a condition to skip sign encoding
                if 'exponent' not in after_block[:200] or 'exponent == 0' not in after_block[:200]:
                    issues.append({
                        'type': 'sign_encoding_after_zero',
                        'message': "Sign encoding is applied after exponent == 0 block, which may be incorrect",
                        'suggestion': "Add condition to skip sign encoding when exponent == 0"
                    })
    
    return {
        'issues': issues,
        'has_issues': len(issues) > 0
    }


def verify_signed_arithmetic(code: str) -> Dict:
    """Verify the use of signed arithmetic."""
    issues = []
    
    # Look for potential signed-arithmetic issues.
    # Find variables of type logic [N:0] that participate in subtraction.
    var_decl_pattern = r'logic\s+\[(\d+):0\]\s+(\w+);'
    var_decls = {}
    for match in re.finditer(var_decl_pattern, code):
        var_name = match.group(2)
        var_decls[var_name] = match.group(1)
    
    # Find subtraction operations involving these variables
    for var_name, width in var_decls.items():
        if 'exp' in var_name.lower() or 'bias' in var_name.lower():
            # 查找这个变量的赋值
            assignment_pattern = rf'{var_name}\s*=\s*([^;]+);'
            for match in re.finditer(assignment_pattern, code):
                assignment = match.group(1)
                if 'BIAS' in assignment or 'exponent' in assignment:
                    if '-' in assignment:
                        # Check whether an integer type is used
                        var_decl_line = code[:code.find(f'logic')]
                        if 'integer' not in code[:code.find(var_name)]:
                            issues.append({
                                'type': 'unsigned_subtraction',
                                'variable': var_name,
                                'assignment': assignment,
                                'message': f"Variable {var_name} is declared as logic (unsigned) but used in subtraction that may be negative",
                                'suggestion': f"Use integer type: integer {var_name};"
                            })
    
    return {
        'issues': issues,
        'has_issues': len(issues) > 0
    }


def find_block_end(code: str, start_pos: int) -> int:
    """Find the end position of a Verilog/SystemVerilog block."""
    pos = start_pos
    depth = 0
    in_string = False
    string_char = None
    
    while pos < len(code):
        char = code[pos]
        
        # Handle string literals
        if char in ['"', "'"] and (pos == 0 or code[pos-1] != '\\'):
            if not in_string:
                in_string = True
                string_char = char
            elif char == string_char:
                in_string = False
                string_char = None
        
        if not in_string:
            if code[pos:pos+3] == 'end':
                if depth == 0:
                    return pos + 3
                depth -= 1
            elif code[pos:pos+5] == 'begin':
                depth += 1
        
        pos += 1
    
    return len(code)


def verify_logic(rtl_code: str) -> str:
    """
    Verify RTL logic and generate a verification report.
    
    Args:
        rtl_code: RTL code to be verified.
    
    Returns:
        Verification report string.
    """
    shift_verification = verify_shift_calculation(rtl_code)
    exp_zero_verification = verify_exponent_zero_handling(rtl_code)
    signed_verification = verify_signed_arithmetic(rtl_code)
    
    report = "=== LOGIC VERIFICATION REPORT ===\n\n"
    
    # Shift calculation verification
    report += "【Shift Calculation Verification】\n"
    if shift_verification['has_issues']:
        for issue in shift_verification['issues']:
            report += f"❌ {issue['message']}\n"
            report += f"   Variable: {issue['variable']}\n"
            report += f"   Assignment: {issue['assignment']}\n"
            report += f"   Expected: {issue['expected']}\n\n"
    else:
        report += "✅ No obvious shift calculation issues found\n\n"
    
    # exponent == 0 handling verification
    report += "【Exponent Zero Handling Verification】\n"
    if exp_zero_verification['has_issues']:
        for issue in exp_zero_verification['issues']:
            report += f"❌ {issue['message']}\n"
            if 'suggestion' in issue:
                report += f"   Suggestion: {issue['suggestion']}\n"
            report += "\n"
    else:
        report += "✅ Exponent zero handling looks correct\n\n"
    
    # Signed arithmetic verification
    report += "【Signed Arithmetic Verification】\n"
    if signed_verification['has_issues']:
        for issue in signed_verification['issues']:
            report += f"❌ {issue['message']}\n"
            if 'suggestion' in issue:
                report += f"   Suggestion: {issue['suggestion']}\n"
            report += "\n"
    else:
        report += "✅ Signed arithmetic looks correct\n\n"
    
    return report


if __name__ == '__main__':
    # Simple self-test
    test_code = """
    always_comb begin
        shift_amt = 19 - e_unbiased;
        shifted = full_mantissa >> shift_amt;
    end
    """
    
    report = verify_logic(test_code)
    print(report)

