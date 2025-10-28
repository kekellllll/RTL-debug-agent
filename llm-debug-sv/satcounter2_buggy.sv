`default_nettype none
// Buggy 2-bit counter: wraps around instead of saturating
module satcounter2_buggy (
  input  logic clock,
  input  logic reset,
  input  logic inc,
  output logic [1:0] count
);
  always_ff @(posedge clock or posedge reset) begin
    if (reset) begin
      count <= 2'd0;
    end else if (inc) begin
      count <= count + 2'd1; // BUG: no saturation, wraps 3->0
    end
  end
endmodule : satcounter2_buggy
