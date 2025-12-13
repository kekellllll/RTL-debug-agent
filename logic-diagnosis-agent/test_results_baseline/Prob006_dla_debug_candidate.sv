`timescale 1ns/1ps
`default_nettype none

module TopModule #(
    parameter int NumFeatures = 4,
    parameter int NumClasses  = 3
) (
    input  logic clk,
    input  logic rst_b,

    // Feature vector: NumFeatures elements, each 32-bit
    input  logic [31:0] feature_vector_in [NumFeatures-1:0],
    input  logic        feature_vector_valid,

    // Weights: flattened array of NumClasses * NumFeatures 32-bit elements
    input  logic [31:0] weights [NumClasses*NumFeatures-1:0],

    // Output probabilities: NumClasses elements, each 32-bit
    output logic [31:0] probabilities_out [NumClasses-1:0],
    output logic        probabilities_valid
);

    // Internal signals for logits from systolic array
    logic [31:0] logits_out   [NumClasses-1:0];
    logic        logits_valid;

    // Systolic array: computes logits = W * feature_vector_in
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

    // Softmax core: converts logits to probabilities
    softmax_core #(
        .NUM_SIZE(NumClasses)
    ) inst_softmax (
        .clk        (clk),
        .rst_b      (rst_b),
        .fp32_in    (logits_out),
        .valid      (logits_valid),
        .fp32_logits(probabilities_out),
        .valid_out  (probabilities_valid)
    );

endmodule
