module TopModule (
input        clk,
input        reset,
input        in,
output logic out
);
// State encoding for FSM
typedef enum logic [1:0] {
S0 = 2'b00,  // No prior '1' seen
S1 = 2'b01,  // One '1' seen
S2 = 2'b10   // Two consecutive '1's detected
} state_t;
state_t state, next_state;
// Sequential state register
always_ff @(posedge clk or posedge reset) begin
if (reset)
state <= S0;
else
state <= next_state;
end
// Next-state logic
always_comb begin
case (state)
S0: next_state = in ? S1 : S0;  // First '1' moves to S1
S1: next_state = in ? S2 : S0;  // Second consecutive '1' moves to S2
S2: next_state = in ? S2 : S0;  // Stay in S2 while '1' continues, reset on '0'
default: next_state = S0;
endcase
end
// Output logic: assert when in S2
always_comb begin
out = (state == S2);
end
endmodule
