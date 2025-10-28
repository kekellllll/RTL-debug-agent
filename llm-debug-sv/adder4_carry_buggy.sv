`default_nettype none
// Buggy 4-bit adder: drops carry-in from the sum
module adder4_carry_buggy (
  input  logic [3:0] A, B,
  input  logic       cin,
  output logic [3:0] sum,
  output logic       cout
);
  always_comb begin
    {cout, sum} = A + B; // BUG: ignores cin
  end
endmodule : adder4_carry_buggy
