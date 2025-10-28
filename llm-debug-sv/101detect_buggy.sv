`default_nettype none
// Buggy 101 detector: output mis-specified (misses 101 because it checks wrong bit)
module hw5prob1_buggy
    (input logic a, clock, reset_N,
    output logic found_it);

    enum logic [2:0] {NONE=3'b001, SAW1=3'b010, SAW10=3'b100} currState,
     nextState;
    
    always_comb begin
        nextState[0]=currState[0]&~a|currState[2];
        nextState[1]=(currState[0]|currState[1])&a;
        nextState[2]=currState[1]&~a;
    end
        
    // BUG: should be currState[2] & a; using currState[1] incorrectly fires on 11
    assign found_it=currState[1]&a; // BUG

    always_ff@(posedge clock, negedge reset_N) begin
        if (~reset_N)
            currState<=NONE;
        else
            currState<=nextState;
    end
endmodule:hw5prob1_buggy
