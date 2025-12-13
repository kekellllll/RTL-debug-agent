module TopModule (
input        clk,
input        reset,    // synchronous, active-high reset
output [3:0] q
);
// Internal register to hold the counter value
reg [3:0] q_reg;
// Drive output from internal register
assign q = q_reg;
// 4-bit counter with synchronous active-high reset
always @(posedge clk) begin
if (reset)
q_reg <= 4'b0000;      // reset counter to 0 on rising clock when reset=1
else
q_reg <= q_reg + 1'b1; // increment counter
end
endmodule
