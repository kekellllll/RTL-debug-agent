`default_nettype none
// 4-to-2 encoder for one-hot input: maps 1,2,4,8 -> 2-bit code; outputs X on invalid input
module encoder4to2_correct (
  input  logic [3:0] in,   // one-hot: 0001,0010,0100,1000
  output logic [1:0] code, // 00,01,10,11
  output logic       valid
);
  always_comb begin
    unique case (in)
      4'b0001: begin code = 2'b00; valid = 1; end
      4'b0010: begin code = 2'b01; valid = 1; end
      4'b0100: begin code = 2'b10; valid = 1; end
      4'b1000: begin code = 2'b11; valid = 1; end
      default: begin code = 2'bxx; valid = 0; end
    endcase
  end
endmodule : encoder4to2_correct
