`default_nettype none
// Buggy rising-edge detector: wrong reset initializes history to 1, missing first pulse and causing false negatives
module edge_detect_rise_buggy (
  input  logic clock,
  input  logic reset,
  input  logic b,
  output logic pulse
);
  logic b_q;
  always_ff @(posedge clock or posedge reset) begin
    if (reset) b_q <= 1'b1; // BUG: should be 0
    else       b_q <= b;
  end
  assign pulse = (b & ~b_q);
endmodule : edge_detect_rise_buggy
