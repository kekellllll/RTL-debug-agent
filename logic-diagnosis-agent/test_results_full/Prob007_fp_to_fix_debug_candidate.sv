`timescale 1ns/1ps
`default_nettype none
// NOTE: fp_split is provided by the testbench / environment.
// We only implement TopModule here.
module TopModule (
input  logic [31:0] fp32_in,
output logic [7:0]  integer_out,
output logic [4:0]  frac_out
);
// Split FP32 fields
logic        sign;
logic [7:0]  exponent;
logic [22:0] mantissa;
// 1.xxx... mantissa aligned into 31 bits
logic [30:0] full_mantissa;
// Magnitude (unsigned) of integer part before sign/bias encoding
logic [7:0] int_mag;
// Fractional nibble (0..15) before sign/bias encoding
logic [3:0] frac_true;
// Signed intermediates for exponent arithmetic
integer exp_minus_bias;
integer bias_minus_exp;
localparam logic [7:0] BIAS = 8'd127;
// fp_split is defined in the testbench/ref file
fp_split split (
.in      (fp32_in),
.sign    (sign),
.exponent(exponent),
.mantissa(mantissa)
);
// Normalised mantissa: bit 23 is the integer bit when exponent == BIAS
// (we pad with 7 zeros above so that bit indices 30..0 are used)
assign full_mantissa = {7'b0, 1'b1, mantissa};
always_comb begin
// Signed exponent differences
exp_minus_bias = $signed({1'b0, exponent}) - $signed({1'b0, BIAS});
bias_minus_exp = $signed({1'b0, BIAS})     - $signed({1'b0, exponent});
// Default magnitude
int_mag   = 8'd0;
frac_true = 4'd0;
// 1) Handle zero / denormals: magnitude = 0.0
if (exponent == 8'd0) begin
int_mag   = 8'd0;
frac_true = 4'd0;
// 2) exponent < BIAS: |value| < 1. Integer part = 0, fractional from mantissa.
end else if (exponent < BIAS) begin
int_mag = 8'd0;
// For exponent < BIAS, the binary point is left of the integer bit
// by (BIAS - exponent). The original code had:
//   full_mantissa[22 + (BIAS - exponent) -: 4]   (BUG)
// Correct is:
//   full_mantissa[22 - (BIAS - exponent) +: 4]
// Ensure index stays within 0..22
if (bias_minus_exp <= 22) begin
// 22 - bias_minus_exp is in [0..22], then +:4 selects
// [22 - bias_minus_exp : 25 - bias_minus_exp]
frac_true = full_mantissa[22 - bias_minus_exp +: 4];
end else begin
frac_true = 4'd0;
end
// 3) exponent - BIAS > 8 : magnitude too large for 8-bit integer → saturate
end else if (exp_minus_bias > 8) begin
int_mag = 8'd255;  // saturation before encoding
// Use the same fractional region as for the largest non-saturated case
// (exp_minus_bias == 8). For that case, integer LSB uses
//   full_mantissa[30-8 -: 8] → LSB at bit (30-8-7) = 15
// and fractional bits are:
//   full_mantissa[22-8 -: 4] = bits [14:11].
frac_true = full_mantissa[22 - 8 -: 4];
// 4) Normal range: 0 <= exponent - BIAS <= 8
end else begin
// exp_minus_bias is in [0..8] here.
// Integer magnitude: 8 bits starting from (30 - exp_minus_bias) downward.
// This matches the original algorithm:
//   full_mantissa[30 - (exponent - BIAS) -: 8]
int_mag = full_mantissa[30 - exp_minus_bias -: 8];
// Fractional nibble just below LSB of integer region:
// original:
//   full_mantissa[22 - (exponent - BIAS) -: 4]
frac_true = full_mantissa[22 - exp_minus_bias -: 4];
end
// 5) Apply sign and bias encoding, with correct zero handling.
// The testbench expects:
//   - +nonzero: integer_out = int_mag + BIAS
//   - -nonzero: integer_out = BIAS - int_mag - 1, frac_true two's-complemented
//   - ±0: integer_out = 0, frac_out index 0.
if (sign == 1'b1) begin
if ((int_mag != 8'd0) || (frac_true != 4'd0)) begin
integer_out = BIAS - int_mag - 8'd1;
frac_true   = ~frac_true + 4'd1;
end else begin
// -0.0 → zero
integer_out = 8'd0;
frac_true   = 4'd0;
end
end else begin
if ((int_mag != 8'd0) || (frac_true != 4'd0)) begin
integer_out = int_mag + BIAS;
end else begin
// +0.0 → zero
integer_out = 8'd0;
frac_true   = 4'd0;
end
end
end
// frac_out is a 5-bit index: MSB is always 0, low 4 bits are the nibble.
assign frac_out = {1'b0, frac_true};
endmodule
