#!/usr/bin/env python3
"""
Test failure analysis utility: analyze failing simulation test cases and extract failure patterns.
"""

import re
from typing import Dict, List, Optional, Tuple
from collections import defaultdict


def parse_simulation_output(simulation_output: str) -> Dict:
    """Parse simulation output and extract failing test cases."""
    failures = []
    passes = []
    
    # Parse failure lines and try to extract test input values.
    # Format: Test N (value): got k=X idx=Y, exp k=A idx=B
    # or:     Test N: got k=X idx=Y, exp k=A idx=B
    failure_pattern = r'Test\s+(\d+)(?:\s+\(([^)]+)\))?\s*:\s+got\s+k=(\d+)\s+idx=(\d+),\s+exp\s+k=(\d+)\s+idx=(\d+)'
    for match in re.finditer(failure_pattern, simulation_output):
        test_value_str = match.group(2) if match.group(2) else None
        test_value = None
        if test_value_str:
            try:
                # Try to parse as a floating-point number
                test_value = float(test_value_str)
            except:
                # If it is not numeric (e.g. "random"), keep the raw string
                test_value = test_value_str
        
        failures.append({
            'test_num': int(match.group(1)),
            'test_value': test_value,
            'got_k': int(match.group(3)),
            'got_idx': int(match.group(4)),
            'exp_k': int(match.group(5)),
            'exp_idx': int(match.group(6))
        })
    
    # Parse PASS information
    pass_pattern = r'PASS\s+Test\s+(\d+)'
    for match in re.finditer(pass_pattern, simulation_output):
        passes.append(int(match.group(1)))
    
    return {
        'failures': failures,
        'passes': passes,
        'total_failures': len(failures),
        'total_passes': len(passes)
    }


def analyze_failure_patterns(failures: List[Dict]) -> Dict:
    """Analyze failure patterns."""
    patterns = {
        'zero_value_failures': [],      # Cases where value is exactly 0 (exponent == 0)
        'small_value_failures': [],     # Small values (0 < value < 1, exponent < BIAS)
        'normal_value_failures': [],    # Normal values (1 <= value < 256)
        'large_value_failures': [],     # Large values (exponent > BIAS + 8)
        'k_mismatch_only': [],          # Only k mismatches
        'idx_mismatch_only': [],        # Only idx mismatches
        'both_mismatch': [],            # Both k and idx mismatch
        'got_k_equals_bias': [],        # got_k == 127 (BIAS)
        'got_k_equals_zero': [],        # got_k == 0
        'got_k_equals_255': [],         # got_k == 255 (saturation)
        'got_k_near_bias': [],          # got_k is near BIAS (126 or 127)
        'exp_k_equals_zero': [],        # Expected k == 0 cases
        'small_value_wrong_k': []       # Small values (< 1.0) where got_k is not 0
    }
    
    for failure in failures:
        got_k = failure['got_k']
        exp_k = failure['exp_k']
        got_idx = failure['got_idx']
        exp_idx = failure['exp_idx']
        test_value = failure.get('test_value')
        
        # Classify according to test_value
        if test_value is not None and isinstance(test_value, (int, float)):
            abs_value = abs(test_value)
            if abs_value == 0:
                patterns['zero_value_failures'].append(failure)
            elif abs_value < 1.0:
                patterns['small_value_failures'].append(failure)
                # For small values, check if k is incorrectly non-zero
                if got_k != 0 and exp_k == 0:
                    patterns['small_value_wrong_k'].append(failure)
            elif abs_value < 256:
                patterns['normal_value_failures'].append(failure)
            else:
                patterns['large_value_failures'].append(failure)
        
        # Check whether k equals or is near BIAS (127)
        if got_k == 127:
            patterns['got_k_equals_bias'].append(failure)
        elif got_k == 126:
            patterns['got_k_near_bias'].append(failure)
        
        # Check whether got_k is 0 while expected is not
        if got_k == 0 and exp_k != 0:
            patterns['got_k_equals_zero'].append(failure)
        
        # Check whether expected k is 0
        if exp_k == 0:
            patterns['exp_k_equals_zero'].append(failure)
        
        # Check whether got_k is 255 (saturation)
        if got_k == 255 and exp_k != 255:
            patterns['got_k_equals_255'].append(failure)
        
        # Check if only k mismatches
        if got_k != exp_k and got_idx == exp_idx:
            patterns['k_mismatch_only'].append(failure)
        
        # Check if only idx mismatches
        if got_k == exp_k and got_idx != exp_idx:
            patterns['idx_mismatch_only'].append(failure)
        
        # Check if both k and idx mismatch
        if got_k != exp_k and got_idx != exp_idx:
            patterns['both_mismatch'].append(failure)
    
    return patterns


def generate_failure_analysis(simulation_output: str) -> str:
    """
    Analyze simulation failures and generate a human-readable report.
    
    Args:
        simulation_output: Output from the simulate tool.
    
    Returns:
        Failure analysis report as a string.
    """
    parsed = parse_simulation_output(simulation_output)
    patterns = analyze_failure_patterns(parsed['failures'])
    
    report = "=== TEST FAILURE ANALYSIS ===\n\n"
    report += f"Total failures: {parsed['total_failures']}\n"
    report += f"Total passes: {parsed['total_passes']}\n\n"
    
    # Analyze failure patterns
    report += "【Failure Patterns】\n"
    
    # Most critical pattern: incorrect integer_out for small values
    if patterns['small_value_wrong_k']:
        count = len(patterns['small_value_wrong_k'])
        report += f"🔴 CRITICAL: {count} test(s) with small values (< 1.0) where got_k != 0 but exp_k == 0\n"
        # Show a few examples
        for i, failure in enumerate(patterns['small_value_wrong_k'][:3]):
            test_val = failure.get('test_value', 'N/A')
            report += f"   Example {i+1}: Test {failure['test_num']} (value={test_val}): got k={failure['got_k']}, exp k=0\n"
        report += "   → ISSUE: For values < 1.0, integer_out should be 0 and NOT be encoded\n"
        report += "   → LIKELY CAUSE: Bias/sign encoding is being applied to integer_out=0 when it shouldn't be\n"
        report += "   → SOLUTION: Check the condition for applying bias/sign encoding\n"
        report += "   → The encoding should ONLY be applied when there's an actual integer part (integer_out != 0)\n"
        report += "   → OR only apply encoding when exponent >= BIAS (value >= 1.0)\n\n"
    
    if patterns['got_k_near_bias']:
        count = len(patterns['got_k_near_bias'])
        report += f"⚠️  {count} test(s) where got_k == 126 (near BIAS=127)\n"
        # Check whether this is correlated with small values
        small_val_with_126 = [f for f in patterns['got_k_near_bias'] 
                              if f.get('test_value') is not None and isinstance(f.get('test_value'), (int, float)) 
                              and abs(f.get('test_value')) < 1.0]
        if small_val_with_126:
            report += f"   → {len(small_val_with_126)} of these are small values (< 1.0)\n"
            report += "   → This confirms that encoding is incorrectly applied to integer_out=0\n"
        report += "\n"
    
    if patterns['got_k_equals_bias']:
        count = len(patterns['got_k_equals_bias'])
        report += f"⚠️  {count} test(s) where got_k == 127 (BIAS) but expected different value\n"
        report += "   → This might indicate encoding applied to zero or incorrect values\n\n"
    
    if patterns['got_k_equals_zero'] and patterns['exp_k_equals_zero']:
        # Filter to the actually problematic cases where expected is not 0
        actually_wrong = [f for f in patterns['got_k_equals_zero'] if f not in patterns['exp_k_equals_zero']]
        if actually_wrong:
            count = len(actually_wrong)
            report += f"⚠️  {count} test(s) where got_k == 0 but expected saturation (255)\n"
            report += "   → This suggests large values are not being saturated correctly\n"
            report += "   → Check the saturation condition (exponent > BIAS + 8)\n\n"
    
    if patterns['got_k_equals_255']:
        count = len(patterns['got_k_equals_255'])
        report += f"⚠️  {count} test(s) where got_k == 255 (saturation) but expected different value\n"
        report += "   → This suggests values are incorrectly saturated\n\n"
    
    if patterns['k_mismatch_only'] and not patterns['small_value_wrong_k']:
        count = len(patterns['k_mismatch_only'])
        report += f"⚠️  {count} test(s) where only k (integer_out) mismatches\n"
        report += "   → This suggests integer part calculation is incorrect\n"
        report += "   → Check shift calculations and bit selections\n\n"
    
    if patterns['idx_mismatch_only']:
        count = len(patterns['idx_mismatch_only'])
        report += f"⚠️  {count} test(s) where only idx (frac_out) mismatches\n"
        report += "   → This suggests fractional part calculation is incorrect\n"
        report += "   → Check fractional bit selection and shift operations\n\n"
    
    if patterns['both_mismatch'] and not patterns['small_value_wrong_k']:
        count = len(patterns['both_mismatch'])
        report += f"⚠️  {count} test(s) where both k and idx mismatch\n"
        report += "   → This suggests fundamental logic error\n"
        report += "   → Review the algorithm implementation\n\n"
    
    # Provide suggested fixes
    report += "【Suggested Fixes】\n"
    
    if patterns['small_value_wrong_k']:
        report += "1. 🔴 CRITICAL FIX - Encoding applied incorrectly to small values (< 1.0):\n"
        report += "   \n"
        report += "   ISSUE: For small values like 1.5 or 0.125:\n"
        report += "     - exponent < BIAS, so integer part = 0 (correct)\n"
        report += "     - BUT encoding still executes: integer_out = 0 + BIAS = 127 (WRONG!)\n"
        report += "   \n"
        report += "   COMMON MISTAKE: Only checking for complete zero:\n"
        report += "     if ((integer_part == 0) && (fractional_part == 0)) {\n"
        report += "         // skip encoding\n"
        report += "     } else {\n"
        report += "         integer_out = integer_part + BIAS;  // ❌ WRONG for small values!\n"
        report += "     }\n"
        report += "   \n"
        report += "   This fails because small values have integer_part=0 but fractional_part != 0\n"
        report += "   \n"
        report += "   CORRECT FIX - Check integer_part separately:\n"
        report += "     if (integer_part == 0) begin\n"
        report += "         // For small values (< 1.0), integer part is 0, don't encode it\n"
        report += "         integer_out = 0;\n"
        report += "         // Handle fractional encoding separately if needed\n"
        report += "         if (sign) begin\n"
        report += "             fractional_part = ~fractional_part + 1;  // Only encode frac if negative\n"
        report += "         end\n"
        report += "     end else if (sign) begin\n"
        report += "         // Negative non-zero: encode both integer and fractional\n"
        report += "         integer_out = BIAS - integer_part - 1;\n"
        report += "         fractional_part = ~fractional_part + 1;\n"
        report += "     end else begin\n"
        report += "         // Positive non-zero: encode integer\n"
        report += "         integer_out = integer_part + BIAS;\n"
        report += "     end\n"
        report += "   \n"
        report += "   KEY POINT: Check integer_part == 0 FIRST, not just (integer_part == 0 && fractional_part == 0)!\n"
        report += "   Small values have integer_part=0 and should output integer_out=0 WITHOUT encoding.\n\n"
    
    if patterns['got_k_equals_bias'] and not patterns['small_value_wrong_k']:
        report += "2. 🔴 CRITICAL - Check BOTH positive and negative encoding paths:\n"
        report += "   The issue: zero values are being encoded to BIAS (127)\n"
        report += "   \n"
        report += "   This happens when:\n"
        report += "     - exponent == 0 or small values set int_mag = 0\n"
        report += "     - BUT the encoding step still executes: integer_out = int_mag + BIAS = 0 + 127 = 127\n"
        report += "   \n"
        report += "   FIX - Add zero-check in BOTH sign branches:\n"
        report += "     if (sign == 1'b1) {\n"
        report += "         if ((int_mag != 0) || (frac_true != 0)) {\n"
        report += "             integer_out = BIAS - int_mag - 1;  // negative non-zero\n"
        report += "         } else {\n"
        report += "             integer_out = 0;  // -0 -> 0\n"
        report += "         }\n"
        report += "     } else {\n"
        report += "         if ((int_mag != 0) || (frac_true != 0)) {\n"
        report += "             integer_out = int_mag + BIAS;  // positive non-zero\n"
        report += "         } else {\n"
        report += "             integer_out = 0;  // +0 -> 0\n"
        report += "         }\n"
        report += "     }\n"
        report += "   \n"
        report += "   CRITICAL: The positive branch ALSO needs the zero check!\n\n"
    
    if patterns['got_k_equals_255']:
        report += "3. Check signed arithmetic:\n"
        report += "   - Use integer type for exponent - BIAS calculation\n"
        report += "   - Or check exponent < BIAS before subtraction\n\n"
    
    if patterns['idx_mismatch_only']:
        report += "4. Check fractional part calculation:\n"
        report += "   - Verify shift_amt calculation (should be BIAS - exponent for exponent < BIAS)\n"
        report += "   - Verify bit selection after shift\n\n"
    
    return report


if __name__ == '__main__':
    # 测试
    simulation_output = """
    PASS Test 1 (zero)
    FAIL Test 2 (1.5): got k=255 idx=0, exp k=0 idx=15
    PASS Test 3 (-2.25)
    FAIL Test 4 (0.125): got k=255 idx=0, exp k=0 idx=15
    """
    
    report = generate_failure_analysis(simulation_output)
    print(report)

