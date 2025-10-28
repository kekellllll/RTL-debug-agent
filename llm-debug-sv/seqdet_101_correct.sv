`default_nettype none
// 101 sequence detector (asserts when 1-0-1 just seen)
module seqdet_101_correct
    (input logic a, clock, reset_N,
    output logic found_it);

    enum logic [2:0] {NONE=3'b001, SAW1=3'b010, SAW10=3'b100} currState,
     nextState;
    
    // Next state (bit-encoded)
    always_comb begin
        nextState[0]=currState[0]&~a|currState[2];
        nextState[1]=(currState[0]|currState[1])&a;
        nextState[2]=currState[1]&~a;
    end
        
    // Output: assert on 101
    assign found_it=currState[2]&a;

    // State register with async active-low reset
    always_ff@(posedge clock, negedge reset_N) begin
        if (~reset_N)
            currState<=NONE;
        else
            currState<=nextState;
    end
endmodule:seqdet_101_correct
