`timescale 1ps/1ps
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
// -----------------------------
// Stage 1: exponentiation (combinational core, registered outputs)
// -----------------------------
logic [31:0] exp_out_comb [NUM_SIZE-1:0];
exp_core #(.NUM_SIZE(NUM_SIZE)) exp_inst (
.fp32_in (fp32_in),
.fp32_out(exp_out_comb)
);
logic   [31:0] exp_out_reg [NUM_SIZE-1:0];
logic          valid_stage1;
integer        j;  // loop index for stage 1
always_ff @(posedge clk or negedge rst_b) begin
if (!rst_b) begin
valid_stage1 <= 1'b0;
for (j = 0; j < NUM_SIZE; j = j + 1) begin
exp_out_reg[j] <= 32'd0;
end
end else begin
valid_stage1 <= valid;
if (valid) begin
// Element-wise assignment for unpacked array
for (j = 0; j < NUM_SIZE; j = j + 1) begin
exp_out_reg[j] <= exp_out_comb[j];
end
end
end
end
// -----------------------------
// Stage 2: accumulation (combinational core, registered outputs)
// -----------------------------
logic [31:0] acc_out_comb;
acc_core #(.NUM_SIZE(NUM_SIZE)) acc_inst (
.fp32_in      (exp_out_reg),
.fp32_sum_out (acc_out_comb)
);
logic   [31:0] acc_out_reg;
logic   [31:0] exp_out_stage2 [NUM_SIZE-1:0];
logic          valid_stage2;
integer        k;  // loop index for stage 2
always_ff @(posedge clk or negedge rst_b) begin
if (!rst_b) begin
valid_stage2 <= 1'b0;
acc_out_reg  <= '0;
for (k = 0; k < NUM_SIZE; k = k + 1) begin
exp_out_stage2[k] <= 32'd0;
end
end else begin
valid_stage2 <= valid_stage1;
if (valid_stage1) begin
acc_out_reg <= acc_out_comb;
// Element-wise assignment for unpacked array
for (k = 0; k < NUM_SIZE; k = k + 1) begin
exp_out_stage2[k] <= exp_out_reg[k];
end
end
end
end
// -----------------------------
// Stage 3: division / normalization
// -----------------------------
div_core #(.NUM_SIZE(NUM_SIZE)) div_inst (
.clk        (clk),
.rst_b      (rst_b),
.valid_in   (valid_stage2),   // start when acc is ready
.numerators (exp_out_stage2),
.denominator(acc_out_reg),
.fp32_out   (fp32_logits),
.valid_out  (valid_out)       // tb waits on this done signal
);
endmodule
