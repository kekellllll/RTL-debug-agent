`timescale 1ns/1ps
`default_nettype none

// Corrected FSM: detects two consecutive '1's on input `in`.
// Output `out` is asserted when the FSM is in state S2.
module TopModule (
    input        clk,
    input        reset,
    input        in,
    output logic out
);

    // State encoding
    typedef enum logic [1:0] {
        S0 = 2'b00,  // No prior '1' seen (or last input was 0)
        S1 = 2'b01,  // One '1' seen in previous cycle
        S2 = 2'b10   // Two consecutive '1's detected
    } state_t;

    state_t state, next_state;

    // State register with synchronous reset
    always @(posedge clk) begin
        if (reset)
            state <= S0;
        else
            state <= next_state;
    end

    // Next-state logic
    always @(*) begin
        // Default assignment to avoid inferred latches
        next_state = state;
        case (state)
            S0: begin
                // If we see a '1', move to S1 (one '1' seen)
                // If we see a '0', stay in S0
                if (in)
                    next_state = S1;
                else
                    next_state = S0;
            end

            S1: begin
                // If we see another '1', move to S2 (two consecutive '1's)
                // If we see a '0', go back to S0
                if (in)
                    next_state = S2;
                else
                    next_state = S0;
            end

            S2: begin
                // We have detected "11" and are in S2.
                // For a *non-overlapping* detector, any new input restarts:
                //  - If next input is '1', treat it as first '1' of a new sequence -> S1
                //  - If next input is '0', no '1' pending -> S0
                if (in)
                    next_state = S1;
                else
                    next_state = S0;
            end

            default: begin
                next_state = S0;
            end
        endcase
    end

    // Output logic: assert when in S2
    always @(*) begin
        out = (state == S2);
    end

endmodule
