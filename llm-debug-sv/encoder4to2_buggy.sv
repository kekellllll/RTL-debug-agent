`default_nettype none
// Buggy 4-to-2 encoder: swapped codes for middle inputs (wiring/order mistake)
module encoder4to2_buggy (
  input  logic [3:0] in,
  output logic [1:0] code,
  output logic       valid
);
  always_comb begin
    unique case (in)
      4'b0001: begin code = 2'b00; valid = 1; end
      4'b0010: begin code = 2'b10; valid = 1; end // BUG: should be 01
      4'b0100: begin code = 2'b01; valid = 1; end // BUG: should be 10
      4'b1000: begin code = 2'b11; valid = 1; end
      default: begin code = 2'bxx; valid = 0; end
    endcase
  end
endmodule : encoder4to2_buggy
