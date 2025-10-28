`default_nettype none
// Buggy variant: subtle transition error prevents stable detection and causes missed/false events
module found3zeros_buggy (
    input  logic b,
    input  logic clock,
    input  logic reset,
    output logic found3zeros_N
);
    enum logic [2:0] {
        NONE    = 3'b000,
        SAW00   = 3'b001,
        SAW01   = 3'b010,
        SAW011  = 3'b011,
        SAW001  = 3'b100,
        SAW0011 = 3'b101,
        SAW000  = 3'b110,
        SAW0    = 3'b111
    } currState, nextState;

    // Next-state logic (BUG: from SAW00 on b==0 should go to SAW000, but goes to SAW0)
    always_comb begin
        unique case (currState)
            NONE:    nextState = b ? NONE    : SAW0;
            SAW0:    nextState = b ? SAW01   : SAW00;
            SAW01:   nextState = b ? SAW011  : SAW00;
            SAW00:   nextState = b ? SAW001  : SAW0;     // BUG here
            SAW011:  nextState = b ? NONE    : SAW00;
            SAW001:  nextState = b ? SAW0011 : SAW000;
            SAW0011: nextState = b ? NONE    : SAW000;
            SAW000:  nextState = b ? SAW001  : SAW000;
        endcase
    end

    // Output: active-low when in SAW000 (kept same to isolate transition bug)
    assign found3zeros_N = (currState == SAW000) ? 1'b0 : 1'b1;

    // State register with async reset
    always_ff @(posedge clock or posedge reset) begin
        if (reset) begin
            currState <= NONE;
        end else begin
            currState <= nextState;
        end
    end
endmodule : found3zeros_buggy
