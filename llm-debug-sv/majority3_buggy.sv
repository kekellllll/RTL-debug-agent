`default_nettype none
// Buggy majority: wrong threshold (>=1) turns it into OR-of-3
module majority3_buggy (
  input  logic a, b, c,
  output logic y
);
  always_comb begin
    automatic int sum = a + b + c;
    y = (sum >= 1); // BUG: should be >=2
  end
endmodule : majority3_buggy
