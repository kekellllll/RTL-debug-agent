`timescale 1ns/1ps
`default_nettype none

module TopModule (
    input  logic [31:0] fp32_in,
    output logic [7:0]  integer_out,
    output logic [4:0]  frac_out
);
    // Decomposed FP fields
    logic        sign;
    logic [7:0]  exponent;
    logic [22:0] mantissa;

    // Full mantissa with hidden 1 and padding
    logic [30:0] full_mantissa;

    // Internal integer and fractional magnitudes (before bias/sign encoding)
    logic [7:0] int_mag;
    logic [3:0] frac_true;

    // Shift amount for exponent-based indexing
    integer shift_amt;

    localparam logic [7:0] BIAS = 8'd127;

    // Split FP32 input
    fp_split split (
        .in      (fp32_in),
        .sign    (sign),
        .exponent(exponent),
        .mantissa(mantissa)
    );

    // Construct full mantissa: [30:24]=0, [23]=1 (hidden), [22:0]=mantissa
    assign full_mantissa = {7'b0, 1'b1, mantissa};

    // Main conversion logic
    always @(*) begin
        // Default values
        int_mag   = 8'd0;
        frac_true = 4'd0;
        shift_amt = 0;

        // 1) Handle exponent == 0: treat as zero (including subnormals)
        if (exponent == 8'd0) begin
            int_mag   = 8'd0;
            frac_true = 4'd0;

        // 2) exponent < BIAS: magnitude < 1.0, integer part = 0
        end else if (exponent < BIAS) begin
            // shift_amt = BIAS - exponent > 0
            shift_amt = BIAS - exponent;

            // Integer magnitude is zero in this range
            int_mag = 8'd0;

            // Fractional bits lie below bit 22.
            // We want 4 bits immediately below the (virtual) integer LSB.
            // Use bounds check to avoid negative indices.
            if (shift_amt <= 22) begin
                // Select 4 bits starting at (22 - shift_amt) going upward
                // This corresponds to full_mantissa[22 - shift_amt +: 4]
                frac_true = full_mantissa[22 - shift_amt +: 4];
            end else begin
                // Too small: all fractional bits are effectively zero at 1/16 resolution
                frac_true = 4'd0;
            end

        // 3) Normal range: BIAS <= exponent <= BIAS + 8
        end else if (exponent <= BIAS + 8'd8) begin
            // shift_amt = exponent - BIAS >= 0
            shift_amt = exponent - BIAS;

            // Extract up to 8 integer bits: full_mantissa[30 - shift_amt -: 8]
            // Ensure indices stay within [0,30]
            if (shift_amt <= 30) begin
                int_mag = full_mantissa[30 - shift_amt -: 8];
            end else begin
                // Should not happen with the exponent bound above, but guard anyway
                int_mag = 8'd0;
            end

            // Extract 4 fractional bits just below the integer LSB:
            // full_mantissa[22 - shift_amt -: 4]
            if (shift_amt <= 22) begin
                frac_true = full_mantissa[22 - shift_amt -: 4];
            end else begin
                // No fractional precision left
                frac_true = 4'd0;
            end

        // 4) exponent > BIAS + 8: overflow, saturate integer magnitude
        end else begin
            int_mag   = 8'd255; // saturation magnitude
            frac_true = 4'd0;   // no fractional part when saturated
        end

        // Apply sign/bias encoding to integer_out only
        if (sign == 1'b1) begin
            // Negative: encoded as BIAS - int_mag - 1
            integer_out = BIAS - int_mag - 8'd1;
        end else begin
            // Positive: encoded as int_mag + BIAS
            integer_out = int_mag + BIAS;
        end
    end

    // Fractional output: magnitude in 1/16 steps, MSB fixed to 0
    assign frac_out = {1'b0, frac_true};

endmodule
