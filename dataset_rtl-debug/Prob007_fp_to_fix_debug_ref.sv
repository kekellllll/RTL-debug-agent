`timescale 1ns/1ps
`default_nettype none

module RefModule (
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
    // Declare variables outside always_comb to avoid Icarus Verilog issues
    int shift_amt;
    always_comb begin
        if (exponent == 8'd0) begin
            // zero input
            integer_out = 8'd0;
            frac_true = 4'd0;
        end else if (exponent < BIAS) begin
            integer_out = 8'd0;
            // Icarus Verilog doesn't support constant selects with variable index
            // Use explicit bit selection instead
            shift_amt = BIAS - exponent;
            if (shift_amt <= 22) begin
                frac_true = full_mantissa[22 - shift_amt +: 4];
            end else begin
                frac_true = 4'd0;
            end
        end else if (exponent > BIAS + 8'd8) begin
            // integer_out = full_mantissa[30 - (8'd8) -: 8];
            integer_out = 8'd255; // saturation
            // Icarus Verilog doesn't support constant selects with variable index
            // Use explicit bit selection instead
            frac_true = full_mantissa[14:11]; // 22 - 8 = 14, 4 bits
        end else begin
            // Icarus Verilog doesn't support constant selects with variable index
            // Use explicit bit selection instead
            shift_amt = exponent - BIAS;
            if (shift_amt <= 30) begin
                integer_out = full_mantissa[30 - shift_amt -: 8];
            end else begin
                integer_out = 8'd255; // saturation
            end
            if (shift_amt <= 22) begin
                frac_true = full_mantissa[22 - shift_amt -: 4];
            end else begin
                frac_true = 4'd0;
            end
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

