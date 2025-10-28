`default_nettype none
// One-hot checker for 8-bit vector
module onehot8_check_correct (
  input  logic [7:0] v,
  output logic       is_onehot
);
  // Exactly one bit set -> popcount == 1
  always_comb begin
    automatic int count = v[0]+v[1]+v[2]+v[3]+v[4]+v[5]+v[6]+v[7];
    is_onehot = (count == 1);
  end
endmodule : onehot8_check_correct
