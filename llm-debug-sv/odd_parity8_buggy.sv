`default_nettype none
// Buggy odd parity: mistakenly uses XOR, which is even parity
module odd_parity8_buggy (
  input  logic [7:0] data,
  output logic       p
);
  always_comb begin
    p = ^data; // BUG: this is even parity
  end
endmodule : odd_parity8_buggy
