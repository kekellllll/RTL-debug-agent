`default_nettype none
// Falling-edge detector: pulses high for 1 cycle when b falls 1->0
module edge_detect_fall_correct (
  input  logic clock,
  input  logic reset,
  input  logic b,
  output logic pulse
);
  logic b_q;
  always_ff @(posedge clock or posedge reset) begin
    if (reset) b_q <= 1'b1;
    else       b_q <= b;
  end
  assign pulse = (~b & b_q);
endmodule : edge_detect_fall_correct
