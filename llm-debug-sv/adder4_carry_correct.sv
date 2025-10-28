`default_nettype none
// 4-bit adder with carry in/out
module adder4_carry_correct (
  input  logic [3:0] A, B,
  input  logic       cin,
  output logic [3:0] sum,
  output logic       cout
);
  always_comb begin
    {cout, sum} = A + B + cin;
  end
endmodule : adder4_carry_correct
