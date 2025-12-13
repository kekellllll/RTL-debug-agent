`timescale 1ns/1ps
`default_nettype none

module TopModule (
    input  logic [31:0] a,
    input  logic [31:0] b,
    input  logic        sel,
    output logic [31:0] y
);

    // Results from submodules
    logic [31:0] sum;
    logic [31:0] product;

    // External modules are provided by the testbench
    fp_adder adder (
        .a   (a),
        .b   (b),
        .sum (sum)
    );

    fp_multiplier multiplier (
        .a       (a),
        .b       (b),
        .product (product)
    );

    always @(*) begin
        // Default
        y = 32'd0;

        // 1) NaN detection: exponent == 0xFF and mantissa != 0 (all 23 bits)
        if ( (a[30:23] == 8'hFF && a[22:0] != 23'b0) ||
             (b[30:23] == 8'hFF && b[22:0] != 23'b0) ) begin
            // Output a NaN pattern
            y = 32'hFFFFFFFF;
        end
        // 2) Infinity + (-Infinity) or (-Infinity) + Infinity => NaN (only for addition)
        else if (sel == 1'b0 &&
                 (a == 32'h7F800000 || a == 32'hFF800000) &&
                 (b == 32'h7F800000 || b == 32'hFF800000) &&
                 (a[31] != b[31])) begin
            y = 32'hFFFFFFFF;
        end
        // 3) If one operand is infinity, propagate it (higher priority than zero)
        else if (a == 32'h7F800000 || a == 32'hFF800000) begin
            y = a;
        end
        else if (b == 32'h7F800000 || b == 32'hFF800000) begin
            y = b;
        end
        // 4) Zero handling
        else if (a[30:23] == 8'b0 || b[30:23] == 8'b0) begin
            // At least one operand has exponent 0 (could be zero or subnormal)
            if (sel == 1'b0) begin
                // Addition
                // If a is exactly zero, return b
                if (a[30:23] == 8'b0 && a[22:0] == 23'b0) begin
                    y = b;
                end
                // If b is exactly zero, return a
                else if (b[30:23] == 8'b0 && b[22:0] == 23'b0) begin
                    y = a;
                end
                // If both are subnormal or other corner cases, fall back to adder result
                else begin
                    y = sum;
                end
            end
            else begin
                // Multiplication: if either operand is zero (or exponent==0 case),
                // the required behavior is to output zero.
                y = 32'd0;
            end
        end
        // 5) Normal operation: select between sum and product
        else begin
            case (sel)
                1'b0: begin
                    // Floating-point addition
                    y = sum;
                end
                1'b1: begin
                    // Floating-point multiplication
                    y = product;
                end
                default: begin
                    // Should not occur for 1-bit sel; use NaN pattern as safe default
                    y = 32'hFFFFFFFF;
                end
            endcase
        end
    end

endmodule : TopModule
