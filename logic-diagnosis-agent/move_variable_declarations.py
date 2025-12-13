#!/usr/bin/env python3
"""
Post-processing function to move variable declarations from always blocks to module level.
This helps fix a common Icarus Verilog compatibility issue.
"""

import re
from typing import Tuple, List


def move_variable_declarations_to_module_level(code: str) -> str:
    """
    Move all variable declarations from inside always_comb/always_ff blocks to module level.
    
    This function:
    1. Finds all variable declarations inside always blocks
    2. Moves them to module level (after port declarations, before always blocks)
    3. Removes the declarations from inside always blocks
    
    Returns the modified code.
    """
    lines = code.split('\n')
    
    # Pattern to match variable declarations
    # Matches: logic [N:0] var; integer var; int signed [N:0] var; etc.
    var_decl_pattern = re.compile(
        r'^\s*(logic\s+(?:signed\s+)?(?:\[[^\]]+\]\s+)?\w+|'
        r'integer\s+(?:signed\s+)?(?:\[[^\]]+\]\s+)?\w+|'
        r'int\s+(?:signed\s+)?(?:\[[^\]]+\]\s+)?\w+)\s*;'
    )
    
    # Find module declaration line
    module_start = -1
    module_end = -1
    first_always = -1
    
    for i, line in enumerate(lines):
        if re.match(r'^\s*module\s+\w+', line):
            module_start = i
        elif re.match(r'^\s*endmodule', line):
            module_end = i
            break
        elif first_always == -1 and re.match(r'^\s*always_(?:comb|ff|@)', line):
            first_always = i
    
    if module_start == -1 or module_end == -1:
        return code  # Not a valid module, return as-is
    
    # Find all always blocks and collect variable declarations
    always_blocks = []
    var_declarations = []
    
    i = module_start + 1
    while i < module_end:
        line = lines[i]
        
        # Check if we're entering an always block
        if re.match(r'^\s*always_(?:comb|ff|@)', line):
            always_start = i
            indent_level = len(line) - len(line.lstrip())
            i += 1
            
            # Find the end of this always block
            begin_count = 0
            always_end = i
            in_always = True
            
            while i < module_end and in_always:
                current_line = lines[i]
                current_indent = len(current_line) - len(current_line.lstrip())
                
                # Check for variable declarations inside always block
                if var_decl_pattern.match(current_line.strip()):
                    # Extract the declaration
                    var_decl = current_line.strip()
                    var_declarations.append(var_decl)
                    # Mark this line for removal
                    lines[i] = ''  # Remove the declaration line
                
                # Track begin/end to find block boundaries
                if 'begin' in current_line:
                    begin_count += 1
                elif 'end' in current_line:
                    begin_count -= 1
                    if begin_count == 0 and current_indent <= indent_level:
                        always_end = i + 1
                        in_always = False
                
                i += 1
            
            always_blocks.append((always_start, always_end))
        else:
            i += 1
    
    # If we found variable declarations, move them to module level
    if var_declarations:
        # Find insertion point (after port declarations, before first always block)
        insertion_point = first_always if first_always > 0 else module_end
        
        # Remove empty lines and deduplicate declarations
        unique_decls = []
        seen = set()
        for decl in var_declarations:
            # Extract variable name
            var_name_match = re.search(r'(\w+)\s*;', decl)
            if var_name_match:
                var_name = var_name_match.group(1)
                if var_name not in seen:
                    seen.add(var_name)
                    unique_decls.append(decl)
        
        # Insert declarations at module level
        indent = '    '  # Standard 4-space indent
        decl_lines = [f'{indent}{decl}' for decl in unique_decls]
        
        # Insert before first always block
        lines = lines[:insertion_point] + [''] + decl_lines + [''] + lines[insertion_point:]
        
        # Remove empty lines
        lines = [line for line in lines if line.strip() != '' or line == '']
    
    return '\n'.join(lines)


def test_move_variable_declarations():
    """Test function for move_variable_declarations_to_module_level"""
    test_code = """
module TopModule (
    input logic [31:0] fp32_in,
    output logic [7:0] integer_out
);
    logic sign;
    logic [7:0] exponent;
    
    always_comb begin
        logic [31:0] tmp;  // Should be moved
        integer sh_l;      // Should be moved
        tmp = {1'b0, exponent};
        if (condition) begin
            integer sh_r;  // Should be moved
            sh_r = 5;
        end
    end
endmodule
"""
    
    result = move_variable_declarations_to_module_level(test_code)
    print("Original:")
    print(test_code)
    print("\nResult:")
    print(result)
    
    # Check that declarations were moved
    assert 'logic [31:0] tmp;' in result
    assert 'integer sh_l;' in result
    assert 'integer sh_r;' in result
    # Check that they're not in always block
    assert 'always_comb' not in result or 'logic [31:0] tmp;' not in result.split('always_comb')[1]


if __name__ == '__main__':
    test_move_variable_declarations()

