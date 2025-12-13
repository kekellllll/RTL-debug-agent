`timescale 1ns/1ps
`default_nettype none

module TopModule (
    input        clk,
    input        reset,
    output [3:0] q
);

    // q is driven by sequential logic, so declare a reg and connect it to the port
    reg [3:0] q_reg;
    assign q = q_reg;

    always @(posedge clk) begin
        if (reset) begin
            q_reg <= 4'b0000;
        end else begin
            q_reg <= q_reg + 4'b0001;
        end
    end

endmodule
