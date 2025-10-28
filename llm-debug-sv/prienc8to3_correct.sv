`default_nettype none
// 8-to-3 priority encoder: MSB has highest priority
module prienc8to3_correct (
  input  logic [7:0] in,
  output logic [2:0] code,
  output logic       valid
);
  always_comb begin
    valid = |in;
    unique casex (in)
      8'b1???????: code = 3'd7;
      8'b01??????: code = 3'd6;
      8'b001?????: code = 3'd5;
      8'b0001????: code = 3'd4;
      8'b00001???: code = 3'd3;
      8'b000001??: code = 3'd2;
      8'b0000001?: code = 3'd1;
      8'b00000001: code = 3'd0;
      default    : code = 3'bxxx;
    endcase
  end
endmodule : prienc8to3_correct
