`timescale 1ns/1ps
`default_nettype none

module RefModule #(
    parameter int NumFeatures = 4,
    parameter int NumClasses = 3
) (
    input  logic clk,
    input  logic rst_b,

    input  logic [31:0] feature_vector_in [NumFeatures-1:0],
    input  logic        feature_vector_valid,
    input  logic [31:0] weights[NumClasses * NumFeatures],

    output logic [31:0] probabilities_out [NumClasses-1:0],
    output logic        probabilities_valid
);

    logic [31:0] logits_out [NumClasses-1:0];
    logic        logits_valid;

    sys_arr #(
        .ArrRows(NumClasses),
        .ArrCols(NumFeatures)
    ) inst_sys_arr (
        .clk(clk),
        .rst_b(rst_b),
        .a_in(feature_vector_in),
        .a_en(feature_vector_valid),
        .y_out(logits_out),
        .y_en(logits_valid),
        .weights(weights) 
    );


    softmax_core #(.NUM_SIZE(NumClasses)) inst_softmax( 
        .clk(clk),
        .rst_b(rst_b),
        .fp32_in(logits_out),
        .valid(logits_valid),
        .fp32_logits(probabilities_out),
        .valid_out(probabilities_valid)
    );

endmodule