`timescale 1ns/1ps
`default_nettype none

module RefModule (
    input        clk,
    input        reset,
    input        in,
    output logic out
);

    typedef enum logic [1:0] {
        S0 = 2'b00,
        S1 = 2'b01,
        S2 = 2'b10
    } state_t;

    state_t state, next_state;

    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else
            state <= next_state;
    end

    always @(*) begin
                next_state = state_t'(S0); // Default assignment to avoid latches
        case (state)
            S0:         next_state = state_t'(state_t'(in ? S1 : S0));
            S1:         next_state = state_t'(state_t'(in ? S2 : S0));
            S2:         next_state = state_t'(state_t'(in ? S2 : S0));
        endcase
    end

    always @(*) begin
        out = (state == S2);
    end

endmodule


