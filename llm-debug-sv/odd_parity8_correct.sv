`default_nettype none
// Odd parity bit for 8-bit data: p==1 when total ones (data + p) is odd
module odd_parity8_correct (
  input  logic [7:0] data,
  output logic       p
);
  always_comb begin
    // For odd parity, p = ~^data (reduction XNOR)
    p = ~^data;
  end
endmodule : odd_parity8_correct
