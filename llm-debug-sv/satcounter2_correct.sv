`default_nettype none
// 2-bit up counter with saturation at 3
module satcounter2_correct (
  input  logic clock,
  input  logic reset,
  input  logic inc,
  output logic [1:0] count
);
  always_ff @(posedge clock or posedge reset) begin
    if (reset) begin
      count <= 2'd0;
    end else if (inc) begin
      if (count != 2'd3) count <= count + 2'd1; // saturate at 3
      else               count <= 2'd3;
    end
  end
endmodule : satcounter2_correct
