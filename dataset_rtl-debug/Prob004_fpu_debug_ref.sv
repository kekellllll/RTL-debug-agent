`define FP_ADD 1'b0
`define FP_MULTIPLY 1'b1

`define NAN (32'hFFFFFFFF)
`define NAN_EXPONENT (8'hFF)
`define INFINITY_POS (32'h7F800000)
`define INFINITY_NEG (32'hFF800000)


module RefModule (
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
        // Handle special cases of NaN and infinity
        y = 32'd0;
        if ((a[30:23] == `NAN_EXPONENT && a[22:0] != 23'b0) || (b[30:23] == `NAN_EXPONENT && b[22:0] != 23'b0)) begin
            y = `NAN;
        end 
        else if (sel == `FP_ADD && (a == `INFINITY_POS || a == `INFINITY_NEG) && (b == `INFINITY_POS || b == `INFINITY_NEG) && (a[31] != b[31])) begin
            // infinity + -infinity = NaN
            y = `NAN;
        end
        else if (a == `INFINITY_POS || a == `INFINITY_NEG) begin
            y = a;
        end
        else if (b == `INFINITY_POS || b == `INFINITY_NEG) begin
            y = b;
        end
        else if (a[30:23] == 8'b0 || b[30:23] == 8'b0) begin
            // one of the numbers is zero or subnormal
            if (sel == `FP_ADD) begin
                if (a[30:23] == 8'b0 && a[22:0] == 23'b0) begin
                    y = b;
                end else if (b[30:23] == 8'b0 && b[22:0] == 23'b0) begin
                    y = a;
                end else begin
                    y = sum;
                end
            end else if (sel == `FP_MULTIPLY) begin
                // Only return 0 if at least one operand is exactly zero (exp=0 && mantissa=0)
                // Subnormal numbers (exp=0 && mantissa != 0) should use normal multiplication
                if ((a[30:23] == 8'b0 && a[22:0] == 23'b0) ||
                    (b[30:23] == 8'b0 && b[22:0] == 23'b0)) begin
                    y = 32'd0; // multiplication by zero
                end else begin
                    // Subnormal numbers: use normal multiplication
                    y = product;
                end
            end
        end
        else begin
            case (sel)
                `FP_ADD: begin
                    // Implement floating-point addition
                    y = sum;
                end
                `FP_MULTIPLY: begin
                    // Implement floating-point multiplication
                    y = product; 
                end
                default: begin
                    y = `NAN;
                end
            endcase
        end

    end

endmodule : RefModule

