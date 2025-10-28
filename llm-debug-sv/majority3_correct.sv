`default_nettype none
// Majority of 3 inputs: y=1 when at least 2 inputs are 1
module majority3_correct (
  input  logic a, b, c,
  output logic y
);
  always_comb begin
    // Sum bits and compare >=2
    automatic int sum = a + b + c;
    y = (sum >= 2);
  end
endmodule : majority3_correct
