`default_nettype none
// parameterized binary-to-onehot decoder
module Decoder_correct
  #(parameter WIDTH=8)
  (input  logic [$clog2(WIDTH)-1:0] I,
   input  logic                     en,
   output logic [WIDTH-1:0]         D);

  always_comb begin
    D = '0;
    if (en)
      D[I] = 1'b1;
  end
endmodule : Decoder_correct
