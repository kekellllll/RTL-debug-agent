`timescale 1ns/1ps
`default_nettype none
module TopModule #(
parameter int NumFeatures = 4,
parameter int NumClasses  = 3
) (
input  logic clk,
input  logic rst_b,
// NumFeatures feature values, each 32‑bit FP
input  logic [31:0] feature_vector_in [NumFeatures-1:0],
input  logic        feature_vector_valid,
// Weight matrix flattened: NumClasses * NumFeatures FP32 values
// BUG FIX: original code missed the upper bound "-1:0"
input  logic [31:0] weights [NumClasses*NumFeatures-1:0],
// Softmax probabilities for each class
output logic [31:0] probabilities_out [NumClasses-1:0],
output logic        probabilities_valid
);
// Internal connections between systolic array and softmax
logic [31:0] logits_out    [NumClasses-1:0];
logic        logits_valid;
// ------------------------------------------------------------------------
// Systolic array: performs matrix‑vector multiply
//   logits_out = Weights (NumClasses x NumFeatures) * feature_vector_in
// ------------------------------------------------------------------------
sys_arr #(
.ArrRows(NumClasses),
.ArrCols(NumFeatures)
) inst_sys_arr (
.clk    (clk),
.rst_b  (rst_b),
.a_in   (feature_vector_in),
.a_en   (feature_vector_valid),
.y_out  (logits_out),
.y_en   (logits_valid),
.weights(weights)
);
// ------------------------------------------------------------------------
// Softmax core: converts logits to probabilities
// BUG FIX: make sure parameter name and port names match testbench/core
// ------------------------------------------------------------------------
softmax_core #(
.NUM_SIZE(NumClasses)
) inst_softmax (
.clk       (clk),
.rst_b     (rst_b),
.fp32_in   (logits_out),
.valid     (logits_valid),
.fp32_logits(probabilities_out),
.valid_out (probabilities_valid)
);
endmodule
