`timescale 1ps/1ps
`default_nettype none

module RefModule #(
    parameter int NUM_SIZE = 3
) (
    input  logic [31:0] fp32_in[NUM_SIZE-1:0],
    input  logic        valid,
    input  logic        clk,
    input  logic        rst_b,
    output logic [31:0] fp32_logits[NUM_SIZE-1:0],
    output logic        valid_out
);

    logic [31:0] exp_out_comb [NUM_SIZE-1:0];

    // stage 1: exponentiation module - combinational
    
    exp_core #(.NUM_SIZE(NUM_SIZE)) exp_inst (
        .fp32_in(fp32_in),
        .fp32_out(exp_out_comb)
    );

    logic [31:0] exp_out_reg [NUM_SIZE-1:0];
    logic        valid_stage1;
    
    always_ff @(posedge clk or negedge rst_b) begin
        if (!rst_b) begin
            valid_stage1 <= 1'b0;
            for (int i = 0; i < NUM_SIZE; i++)
                exp_out_reg[i] <= 31'd0;
        end else begin
            valid_stage1 <= valid;
            if (valid) begin
                // Icarus Verilog doesn't support assignment to entire array
                // Use element-wise assignment instead
                for (int i = 0; i < NUM_SIZE; i++) begin
                    exp_out_reg[i] <= exp_out_comb[i];
                end
            end
        end
    end


    // stage 2: accumulation module - combinational

    logic [31:0] acc_out_comb;
    
    acc_core #(.NUM_SIZE(NUM_SIZE)) acc_inst (
        .fp32_in(exp_out_reg),
        .fp32_sum_out(acc_out_comb)
    );

    logic [31:0] acc_out_reg;
    logic [31:0] exp_out_stage2 [NUM_SIZE-1:0];
    logic        valid_stage2;
    
    always_ff @(posedge clk or negedge rst_b) begin
        if (!rst_b) begin
            valid_stage2 <= 1'b0;
            acc_out_reg <= '0;
            for (int i = 0; i < NUM_SIZE; i++)
                exp_out_stage2[i] <= 32'd0;
        end else begin
            valid_stage2 <= valid_stage1;
            if (valid_stage1) begin
                acc_out_reg <= acc_out_comb;
                // Icarus Verilog doesn't support assignment to entire array
                // Use element-wise assignment instead
                for (int i = 0; i < NUM_SIZE; i++) begin
                    exp_out_stage2[i] <= exp_out_reg[i];
                end
            end
        end
    end


    // Stage 3: division module - can be combninational, sequential FSM or pipelined
 
    div_core #(.NUM_SIZE(NUM_SIZE)) div_inst (
        .clk(clk),
        .rst_b(rst_b),
        .valid_in(valid_stage2), // start when acc is ready
        .numerators(exp_out_stage2),
        .denominator(acc_out_reg),
        
        .fp32_out(fp32_logits), 
        .valid_out(valid_out)  // tb will wait on this done signal
    );


endmodule

