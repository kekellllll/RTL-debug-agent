`timescale 1ns/1ps
`default_nettype none

module TopModule #(
    parameter int NUM_SIZE = 3
) (
    input  logic [31:0] fp32_in[NUM_SIZE-1:0],
    input  logic        valid,
    input  logic        clk,
    input  logic        rst_b,
    output logic [31:0] fp32_logits[NUM_SIZE-1:0],
    output logic        valid_out
);

    // ----------------------------------------------------------------
    // Stage 1: exponentiation (combinational core, registered outputs)
    // ----------------------------------------------------------------

    logic [31:0] exp_out_comb [NUM_SIZE-1:0];

    // Exponentiation core (provided by testbench)
    exp_core #(.NUM_SIZE(NUM_SIZE)) exp_inst (
        .fp32_in (fp32_in),
        .fp32_out(exp_out_comb)
    );

    logic [31:0] exp_out_reg [NUM_SIZE-1:0];
    logic        valid_stage1;

    // Loop index for array assignments (must be declared at module level)
    int i_stage1;
    int i_stage2;

    always_ff @(posedge clk or negedge rst_b) begin
        if (!rst_b) begin
            valid_stage1 <= 1'b0;
            for (i_stage1 = 0; i_stage1 < NUM_SIZE; i_stage1 = i_stage1 + 1) begin
                exp_out_reg[i_stage1] <= 32'd0;  // fixed width: 32 bits
            end
        end else begin
            valid_stage1 <= valid;
            if (valid) begin
                // Element-wise copy from combinational exp outputs to registers
                for (i_stage1 = 0; i_stage1 < NUM_SIZE; i_stage1 = i_stage1 + 1) begin
                    exp_out_reg[i_stage1] <= exp_out_comb[i_stage1];
                end
            end
        end
    end

    // ----------------------------------------------------------------
    // Stage 2: accumulation (combinational core, registered outputs)
    // ----------------------------------------------------------------

    logic [31:0] acc_out_comb;

    // Accumulation core (provided by testbench)
    acc_core #(.NUM_SIZE(NUM_SIZE)) acc_inst (
        .fp32_in      (exp_out_reg),
        .fp32_sum_out (acc_out_comb)
    );

    logic [31:0] acc_out_reg;
    logic [31:0] exp_out_stage2 [NUM_SIZE-1:0];
    logic        valid_stage2;

    always_ff @(posedge clk or negedge rst_b) begin
        if (!rst_b) begin
            valid_stage2 <= 1'b0;
            acc_out_reg  <= 32'd0;
            for (i_stage2 = 0; i_stage2 < NUM_SIZE; i_stage2 = i_stage2 + 1) begin
                exp_out_stage2[i_stage2] <= 32'd0;
            end
        end else begin
            valid_stage2 <= valid_stage1;
            if (valid_stage1) begin
                acc_out_reg <= acc_out_comb;
                // Element-wise copy of exponentials into stage2 buffer
                for (i_stage2 = 0; i_stage2 < NUM_SIZE; i_stage2 = i_stage2 + 1) begin
                    exp_out_stage2[i_stage2] <= exp_out_reg[i_stage2];
                end
            end
        end
    end

    // ----------------------------------------------------------------
    // Stage 3: division core
    // ----------------------------------------------------------------

    // Division core (may be combinational or sequential; provided by testbench)
    div_core #(.NUM_SIZE(NUM_SIZE)) div_inst (
        .clk        (clk),
        .rst_b      (rst_b),
        .valid_in   (valid_stage2),   // start when acc is ready
        .numerators (exp_out_stage2),
        .denominator(acc_out_reg),

        .fp32_out   (fp32_logits),
        .valid_out  (valid_out)       // tb will wait on this done signal
    );

endmodule
