The following Verilog module has one or more bugs. Please identify and fix all bugs:

module TopModule (
    input logic [31:0] a,
    input logic [31:0] b,
    input logic sel,
    output logic [31:0] y
);

    logic [31:0] sum;
    logic [31:0] product;

    fp_adder adder (
        .a(a),
        .b(b),
        .sum(sum)
    );

    fp_multiplier multiplier (
        .a(a),
        .b(b),
        .product(product)
    );

    always_comb begin
        // Good Luck
        // Handle special cases of NaN and infinity
        y = 32'd0;
        
        // BUG 1: NaN detection condition is wrong - should check mantissa != 0, but checks wrong bits
        // Original: a[22:0] != 23'b0
        // Bug: checks a[21:0] instead, missing the MSB of mantissa
        if ((a[30:23] == 8'hFF && a[21:0] != 22'b0) || (b[30:23] == 8'hFF && b[21:0] != 22'b0)) begin
            y = 32'hFFFFFFFF;
        end 
        else if (sel == 1'b0 && (a == 32'h7F800000 || a == 32'hFF800000) && (b == 32'h7F800000 || b == 32'hFF800000) && (a[31] != b[31])) begin
            // infinity + -infinity = NaN
            y = 32'hFFFFFFFF;
        end
        else if (a == 32'h7F800000 || a == 32'hFF800000) begin
            y = a;
        end
        else if (b == 32'h7F800000 || b == 32'hFF800000) begin
            y = b;
        end
        else if (a[30:23] == 8'b0 || b[30:23] == 8'b0) begin
            // one of the numbers is zero
            if (sel == 1'b0) begin
                if (a[30:23] == 8'b0 && a[22:0] == 23'b0) begin
                    y = b;
                end else if (b[30:23] == 8'b0 && b[22:0] == 23'b0) begin
                    y = a;
                end else begin
                    y = sum;
                end
            end else if (sel == 1'b1) begin
                // BUG 2: Multiplication by zero should return zero, but returns wrong value
                // Bug: returns sum instead of 0
                y = sum; // BUG: should be 32'd0 for multiplication by zero
            end
        end
        else begin
            case (sel)
                1'b0: begin
                    // BUG 3: Selection logic is reversed - when sel=0 (FP_ADD), it uses product instead of sum
                    // Implement floating-point addition
                    y = product; // BUG: should be sum
                end
                1'b1: begin
                    // Implement floating-point multiplication
                    y = sum; // BUG: should be product
                end
                default: begin
                    y = 32'hFFFFFFFF;
                end
            endcase
        end

    end

endmodule : TopModule

Debug this code and provide a corrected implementation. The module should implement a Floating Point Unit (FPU) that supports addition and multiplication. When sel=0 (FP_ADD), it should perform floating-point addition (output = sum from fp_adder). When sel=1 (FP_MULTIPLY), it should perform floating-point multiplication (output = product from fp_multiplier). The module must handle special cases: NaN (when exponent=0xFF and mantissa!=0, checking all 23 bits of mantissa [22:0]), Infinity (0x7F800000 for +Inf, 0xFF800000 for -Inf), and Zero (exponent=0 and mantissa=0). For addition with zero, output should be the non-zero input. For multiplication with zero, output should be zero (32'd0).

