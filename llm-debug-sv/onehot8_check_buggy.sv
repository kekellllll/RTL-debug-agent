`default_nettype none
// Buggy one-hot: uses >=1 instead of ==1, allowing multi-hot values
module onehot8_check_buggy (
  input  logic [7:0] v,
  output logic       is_onehot
);
  always_comb begin
    automatic int count = v[0]+v[1]+v[2]+v[3]+v[4]+v[5]+v[6]+v[7];
    is_onehot = (count >= 1); // BUG
  end
endmodule : onehot8_check_buggy
