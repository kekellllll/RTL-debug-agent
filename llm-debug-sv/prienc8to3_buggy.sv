`default_nettype none
// Buggy 8-to-3 priority encoder: reversed priority (LSB highest)
module prienc8to3_buggy (
  input  logic [7:0] in,
  output logic [2:0] code,
  output logic       valid
);
  always_comb begin
    valid = |in;
    unique casex (in)
      8'b???????1: code = 3'd0; // BUG: LSB wins
      8'b??????10: code = 3'd1;
      8'b?????100: code = 3'd2;
      8'b????1000: code = 3'd3;
      8'b???10000: code = 3'd4;
      8'b??100000: code = 3'd5;
      8'b?1000000: code = 3'd6;
      8'b10000000: code = 3'd7;
      default    : code = 3'bxxx;
    endcase
  end
endmodule : prienc8to3_buggy
