`default_nettype none
// Buggy variant: wrong NONE decoding on {A,B}=2'b01; should go B1 but stays in NONE
module hw5prob3_buggy
    (input logic A, B, clock, reset_N,
    output logic F);

    enum logic [2:0] {NONE=3'b000, A1=3'b001, A0=3'b010, A11=3'b011, 
    B1=3'b100, B0=3'b101, B11=3'b110} currState,nextState;
    
    always_comb begin
        case (currState)
            NONE: begin
                casez({A,B})
                    2'b00: nextState=NONE;
                    2'b01: nextState=NONE; // BUG: should be B1
                    2'b1?: nextState=A1;
                endcase
            end
            A1:   nextState = A ? A11 : A0;
            A0:   nextState = A ? A1  : A0;
            A11:  nextState = A ? NONE: A0;
            B1:   nextState = B ? B11 : B0;
            B0:   nextState = B ? B1  : B0;
            B11:  nextState = B ? NONE: B0;
        endcase
    end
        
    assign F=((currState==A11&A)|(currState==B11&B))?1:0;

    always_ff@(posedge clock, negedge reset_N) begin
        if (~reset_N)
            currState<=NONE;
        else
            currState<=nextState;
    end
endmodule:hw5prob3_buggy
