The following Verilog module has one or more bugs. Please identify and fix all bugs:

`timescale 1ns/1ps
`default_nettype none

module TopModule (
    input logic [31:0] fp32_in,
    output logic [7:0] integer_out,
    output logic [4:0] frac_out
);
    logic sign;
    logic [3:0] frac_true;
    logic [7:0] exponent;
    logic [22:0] mantissa;
    logic [30:0] full_mantissa;

    fp_split split (
        .in(fp32_in),
        .sign(sign),
        .exponent(exponent),
        .mantissa(mantissa)
    );
    assign full_mantissa = {7'b0, 1'b1, mantissa};
    localparam BIAS = 8'd127;
    always_comb begin
        if (exponent == 8'd0) begin
            // zero input
            integer_out = 8'd0;
            frac_true = 4'd0;
        end else if (exponent < BIAS) begin
            integer_out = 8'd0;
            frac_true = full_mantissa[22 + (BIAS - exponent) -: 4];
        end else if (exponent > BIAS + 8'd8) begin
            // integer_out = full_mantissa[30 - (8'd8) -: 4];
            integer_out = 8'd255; // saturation
            frac_true = full_mantissa[22 - (8'd8) -: 4];
        end else begin
            integer_out = full_mantissa[30 - (exponent - BIAS) -: 8];
            frac_true = full_mantissa[22 - (exponent - BIAS) -: 4];
        end
        if (sign == 1'b1) begin
            integer_out = BIAS - integer_out - 8'd1;
            frac_true = ~frac_true + 1;
        end
        else begin
            integer_out = integer_out + BIAS;
        end
    end
    assign frac_out = {1'b0, frac_true};

endmodule

Debug this code and provide a corrected implementation. The module converts a 32-bit floating-point number to fixed-point representation, extracting the integer part and fractional part (in 1/16 increments).

