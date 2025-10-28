`default_nettype none
// Buggy falling-edge detector: wrong reset initializes history to 0, masking first fall
module edge_detect_fall_buggy (
  input  logic clock,
  input  logic reset,
  input  logic b,
  output logic pulse
);
  logic b_q;
  always_ff @(posedge clock or posedge reset) begin
    if (reset) b_q <= 1'b0; // BUG: should be 1 so a first fall can be seen
    else       b_q <= b;
  end
  assign pulse = (~b & b_q);
endmodule : edge_detect_fall_buggy
