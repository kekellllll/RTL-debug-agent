#!/usr/bin/env python3
"""
Tool to generate testbench from specification - can be used by agent or user
"""

import os
import sys
import re
from pathlib import Path
from typing import Dict, Optional

def generate_testbench_from_spec_simple(
    module_name: str,
    specification: str,
    expected_formula: Optional[str] = None,
    output_file: str = None
) -> str:
    """
    Generate a simple testbench from specification.
    
    Args:
        module_name: Name of the module (e.g., "TopModule")
        specification: Natural language specification
        expected_formula: Optional formula for expected output (e.g., "sel ? b : a")
        output_file: Path to save testbench
    
    Returns:
        Generated testbench code
    """
    
    # Try to extract expected formula from specification if not provided
    if not expected_formula:
        # Simple heuristics
        if "mux" in specification.lower() or "multiplexer" in specification.lower():
            # Try to find sel, a, b signals
            if "sel" in specification.lower():
                if "sel=0" in specification.lower() or "sel=1" in specification.lower():
                    # Try to parse: "sel=0 -> a, sel=1 -> b" or similar
                    if "-> a" in specification or "should be a" in specification.lower():
                        if "-> b" in specification or "should be b" in specification.lower():
                            expected_formula = "sel ? b : a"
        # Add more heuristics for other common patterns
    
    # Default formula if still not found
    if not expected_formula:
        expected_formula = "sel ? b : a"  # Placeholder - user should customize
    
    testbench = f"""`timescale 1 ps/1 ps

// ============================================================================
// Auto-generated Testbench from Specification
// Specification: {specification}
// Expected Behavior Formula: {expected_formula}
// ============================================================================

module stimulus_gen (
    input clk,
    output logic sel,
    output logic [7:0] a,
    output logic [7:0] b
);

    initial begin
        repeat(100) @(posedge clk, negedge clk) begin
            sel <= $random;
            a <= $random;
            b <= $random;
        end
        $finish;
    end
    
endmodule

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
    initial forever
        #5 clk = ~clk;

    logic sel;
    logic [7:0] a;
    logic [7:0] b;
    logic [7:0] out_dut;

    // Stimulus generator
    stimulus_gen stim1 (
        .clk,
        .sel,
        .a,
        .b
    );
    
    // Device under test
    {module_name} dut (
        .sel,
        .a,
        .b,
        .out(out_dut)
    );

    // ============================================================================
    // Specification-based Checker
    // Expected behavior: {expected_formula}
    // ============================================================================
    
    logic [7:0] expected_out;
    always @(*) begin
        // Calculate expected output based on specification
        expected_out = {expected_formula};
    end
    
    wire tb_match;
    wire tb_mismatch = ~tb_match;
    
    // Compare DUT output with expected output (based on spec)
    assign tb_match = (out_dut === expected_out);
    
    // Statistics collection
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

    final begin
        if (stats1.errors_out) 
            $display("Hint: Output 'out' has %0d mismatches. First mismatch occurred at time %0d.", 
                    stats1.errors_out, stats1.errortime_out);
        else 
            $display("Hint: Output 'out' has no mismatches.");

        $display("Hint: Total mismatched samples is %1d out of %1d samples\\n", 
                stats1.errors, stats1.clocks);
        $display("Simulation finished at %0d ps", $time);
        $display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
    end
    
    // Timeout
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


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate testbench from specification")
    parser.add_argument("--module", default="TopModule", help="Module name")
    parser.add_argument("--spec", required=True, help="Specification")
    parser.add_argument("--expected", help="Expected formula (e.g., 'sel ? b : a')")
    parser.add_argument("--output", default="generated_tb.sv", help="Output file")
    
    args = parser.parse_args()
    
    generate_testbench_from_spec_simple(
        module_name=args.module,
        specification=args.spec,
        expected_formula=args.expected,
        output_file=args.output
    )

