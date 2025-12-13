`timescale 1ns/1ps
`default_nettype none

module TopModule #(
    parameter BITS_PER_STAGE = 3
)(
    input  logic        clk,
    input  logic        rst_b,
    input  logic        start,
    input  logic [46:0] dividend,
    input  logic [23:0] divisor,
    output logic [23:0] quotient,
    output logic        done
);

    // FSM state encoding
    typedef enum logic [1:0] {
        IDLE   = 2'b00,
        DIVIDE = 2'b01,
        DONE   = 2'b10
    } state_t;

    state_t state;

    // Number of multi-bit stages to process 24 quotient bits
    localparam int NUM_STAGES = (24 + BITS_PER_STAGE - 1) / BITS_PER_STAGE;

    // Stage index
    logic [$clog2(NUM_STAGES)-1:0] bit_index;

    // Working registers
    logic [46:0] curr_dividend;   // kept for completeness, not used in algorithm
    logic [23:0] curr_quotient;
    logic [24:0] curr_remainder;

    logic [23:0] working_quotient;
    logic [24:0] working_remainder;

    // Loop index must be declared at module level for Icarus Verilog
    int i;

    // Sequential logic
    always_ff @(posedge clk or negedge rst_b) begin
        if (!rst_b) begin
            done           <= 1'b0;
            bit_index      <= '0;
            curr_dividend  <= '0;
            curr_quotient  <= '0;
            curr_remainder <= '0;
            state          <= IDLE;
        end else begin
            case (state)
                IDLE: begin
                    done      <= 1'b0;
                    bit_index <= '0;

                    if (start) begin
                        // Handle divisor == 0 as a special case:
                        // here we choose quotient = 0, done immediately.
                        if (divisor == 24'd0) begin
                            curr_dividend  <= dividend;
                            curr_quotient  <= 24'd0;
                            curr_remainder <= 25'd0;
                            state          <= DONE;
                        end else begin
                            // Initialize registers for division
                            curr_dividend  <= dividend;
                            // Take top 23 bits of dividend into remainder with 2 leading zeros
                            curr_remainder <= {2'b0, dividend[46:24]};
                            // Lower 24 bits of dividend become initial quotient shift register
                            curr_quotient  <= dividend[23:0];
                            state          <= DIVIDE;
                        end
                    end
                end

                DIVIDE: begin
                    // Copy current working values
                    working_remainder = curr_remainder;
                    working_quotient  = curr_quotient;

                    // Process BITS_PER_STAGE single-bit iterations
                    // NOTE: i is declared at module level (Icarus-compatible)
                    for (i = 0; i < BITS_PER_STAGE; i = i + 1) begin
                        // Shift remainder left and bring in next MSB of quotient
                        working_remainder = working_remainder << 1;
                        working_remainder[0] = working_quotient[23];

                        // Shift quotient left
                        working_quotient = working_quotient << 1;

                        // Restoring division step
                        if (working_remainder[24:0] >= {1'b0, divisor}) begin
                            // Subtract divisor from lower 24 bits of remainder
                            working_remainder[23:0] =
                                working_remainder[23:0] - divisor;
                            // Set new quotient LSB
                            working_quotient[0] = 1'b1;
                        end else begin
                            working_quotient[0] = 1'b0;
                        end
                    end

                    // Update registers for next stage
                    curr_remainder <= working_remainder;
                    curr_quotient  <= working_quotient;

                    // Check if all stages are done
                    if (bit_index == NUM_STAGES - 1) begin
                        state <= DONE;
                    end else begin
                        bit_index <= bit_index + 1;
                    end
                end

                DONE: begin
                    // One-cycle done pulse; result is in curr_quotient
                    done  <= 1'b1;
                    state <= IDLE;
                end

                default: begin
                    // Safe default: go to IDLE
                    state <= IDLE;
                    done  <= 1'b0;
                end
            endcase
        end
    end

    // Output assignment
    assign quotient = curr_quotient;

endmodule
