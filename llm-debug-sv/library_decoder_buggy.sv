`default_nettype none
// Buggy decoder: off-by-one indexing writes D[I+1] instead of D[I]
module Decoder_buggy
  #(parameter WIDTH=8)
  (input  logic [$clog2(WIDTH)-1:0] I,
   input  logic                     en,
   output logic [WIDTH-1:0]         D);

  always_comb begin
    D = '0;
    if (en)
      D[I+1] = 1'b1; // BUG: I+1 can also overflow
  end
endmodule : Decoder_buggy
