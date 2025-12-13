`timescale 1ns/1ps
`default_nettype none

// Testbench for FPU module
// Tests the selection logic and special case handling

module tb();

    logic [31:0] a, b;
    logic sel;
    logic [31:0] y_ref, y_dut;

    // Stub modules for fp_adder and fp_multiplier
    logic [31:0] sum_stub, product_stub;
    
    fp_adder adder_stub (.a(a), .b(b), .sum(sum_stub));
    fp_multiplier mult_stub (.a(a), .b(b), .product(product_stub));

    // Reference implementation
    RefModule ref_inst (
        .a(a),
        .b(b),
        .sel(sel),
        .y(y_ref)
    );

    // Device under test
    TopModule dut_inst (
        .a(a),
        .b(b),
        .sel(sel),
        .y(y_dut)
    );

    wire tb_match;
    wire tb_mismatch = ~tb_match;
    
    // Compare DUT output with reference output
    assign tb_match = (y_dut === y_ref);
    
    typedef struct packed {
        int errors;
        int errortime;
        int errors_y;
        int errortime_y;
        int clocks;
    } stats;
    
    stats stats1;
    
    reg clk = 0;
    initial forever #5 clk = ~clk;

    // Statistics collection
    always @(posedge clk, negedge clk) begin
        stats1.clocks++;
        if (!tb_match) begin
            if (stats1.errors == 0) stats1.errortime = $time;
            stats1.errors++;
        end
        if (y_dut !== y_ref) begin
            if (stats1.errors_y == 0) stats1.errortime_y = $time;
            stats1.errors_y++;
        end
    end

    // Test stimulus
    initial begin
        // Test cases with random inputs
        repeat(100) @(posedge clk, negedge clk) begin
            a <= $random;
            b <= $random;
            sel <= $random;
        end
        
        // Specific test cases
        // Test 1: Addition with zero
        @(posedge clk);
        a = 32'h00000000; // 0.0
        b = 32'h40000000; // 2.0
        sel = 1'b0; // FP_ADD
        @(posedge clk);
        
        // Test 2: Multiplication with zero
        @(posedge clk);
        a = 32'h00000000; // 0.0
        b = 32'h40000000; // 2.0
        sel = 1'b1; // FP_MULTIPLY
        @(posedge clk);
        
        // Test 3: Infinity
        @(posedge clk);
        a = 32'h7F800000; // +Infinity
        b = 32'h40000000; // 2.0
        sel = 1'b0; // FP_ADD
        @(posedge clk);
        
        // Test 4: Normal addition
        @(posedge clk);
        a = 32'h40000000; // 2.0
        b = 32'h40000000; // 2.0
        sel = 1'b0; // FP_ADD
        @(posedge clk);
        
        // Test 5: Normal multiplication
        @(posedge clk);
        a = 32'h40000000; // 2.0
        b = 32'h40000000; // 2.0
        sel = 1'b1; // FP_MULTIPLY
        @(posedge clk);
        
        #100;
        $finish;
    end

    final begin
        if (stats1.errors_y) 
            $display("Hint: Output 'y' has %0d mismatches. First mismatch occurred at time %0d.", 
                    stats1.errors_y, stats1.errortime_y);
        else 
            $display("Hint: Output 'y' has no mismatches.");

        $display("Hint: Total mismatched samples is %1d out of %1d samples\\n", 
                stats1.errors, stats1.clocks);
        $display("Simulation finished at %0d ps", $time);
        $display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
    end
    
    // Timeout
    initial begin
        #100000
        $display("TIMEOUT");
        $finish();
    end

endmodule

// Stub modules for fp_adder and fp_multiplier
module fp_adder (
    input logic [31:0] a,
    input logic [31:0] b,
    output logic [31:0] sum
);
    assign sum = a + b;
endmodule

module fp_multiplier (
    input logic [31:0] a,
    input logic [31:0] b,
    output logic [31:0] product
);
    assign product = a * b;
endmodule

