`timescale 1ns/1ps
`default_nettype none

module tb_softmax_core;

    // Parameters
    parameter NUM_SIZE = 3;  // number of logits
    parameter CLK_PERIOD = 20;
    parameter real TOLERANCE = 0.05;      // 5% error tolerance per element
    parameter real SUM_TOLERANCE = 0.05;  // 5% error tolerance for sum
    
    // DUT signals
    logic [31:0] fp32_in[NUM_SIZE-1:0];
    logic        valid;
    logic        clk;
    logic        rst_b;
    logic [31:0] fp32_logits_ref[NUM_SIZE-1:0];
    logic [31:0] fp32_logits_dut[NUM_SIZE-1:0];
    logic        valid_out_ref;
    logic        valid_out_dut;
    
    real expected_probs[NUM_SIZE-1:0];
    int error_count;
    int test_count;
    int timeout;
    int total_cycles;

    // Reference implementation
    RefModule #(
        .NUM_SIZE(NUM_SIZE)
    ) ref_inst (
        .fp32_in(fp32_in),
        .valid(valid),
        .clk(clk),
        .rst_b(rst_b),
        .fp32_logits(fp32_logits_ref),
        .valid_out(valid_out_ref)
    );

    // Device under test
    TopModule #(
        .NUM_SIZE(NUM_SIZE)
    ) dut_inst (
        .fp32_in(fp32_in),
        .valid(valid),
        .clk(clk),
        .rst_b(rst_b),
        .fp32_logits(fp32_logits_dut),
        .valid_out(valid_out_dut)
    );
    
    // Comparison logic
    // Icarus Verilog doesn't support direct comparison of unpacked arrays
    // So we compare element by element
    wire tb_match;
    wire tb_mismatch = ~tb_match;
    wire array_match;
    assign array_match = (fp32_logits_ref[0] === fp32_logits_dut[0]) &&
                         (fp32_logits_ref[1] === fp32_logits_dut[1]) &&
                         (fp32_logits_ref[2] === fp32_logits_dut[2]);
    assign tb_match = array_match && (valid_out_ref === valid_out_dut);


    initial clk = 1'b0;
    always #(CLK_PERIOD/2) clk = ~clk;

    // Convert FP32 to real
    // Icarus Verilog doesn't support $bitstoshortreal, use $bitstoreal instead
    // Note: shortreal is 32-bit, real is 64-bit, but for IEEE-754 single precision
    // we can use $bitstoreal by padding with zeros
    function real fp32_to_real(logic [31:0] fp32);
        logic [63:0] fp64_bits;
        // Convert 32-bit single precision to 64-bit double precision format
        // Sign bit: same
        // Exponent: adjust from 8-bit (bias 127) to 11-bit (bias 1023)
        // Mantissa: pad with zeros
        if (fp32[30:23] == 8'd0) begin
            // Zero or subnormal
            fp64_bits = {fp32[31], 63'd0};
        end else if (fp32[30:23] == 8'hFF) begin
            // Inf or NaN
            fp64_bits = {fp32[31], 11'h7FF, fp32[22:0], 29'd0};
        end else begin
            // Normal: adjust exponent from bias 127 to bias 1023
            fp64_bits = {fp32[31], (11'(fp32[30:23]) - 8'd127 + 11'd1023), fp32[22:0], 29'd0};
        end
        return $bitstoreal(fp64_bits);
    endfunction
    
    // Convert real to FP32
    // Icarus Verilog doesn't support $shortrealtobits, use $realtobits and extract
    function logic [31:0] real_to_fp32(real r);
        logic [63:0] fp64_bits;
        logic [31:0] fp32_bits;
        logic [10:0] exp64;
        logic [7:0] exp32;
        fp64_bits = $realtobits(r);
        // Convert 64-bit double precision to 32-bit single precision
        // Sign bit: same
        // Exponent: adjust from 11-bit (bias 1023) to 8-bit (bias 127)
        // Mantissa: truncate
        if (fp64_bits[62:52] == 11'd0) begin
            // Zero or subnormal
            fp32_bits = {fp64_bits[63], 31'd0};
        end else if (fp64_bits[62:52] == 11'h7FF) begin
            // Inf or NaN
            fp32_bits = {fp64_bits[63], 8'hFF, fp64_bits[51:29]};
        end else begin
            // Normal: adjust exponent from bias 1023 to bias 127
            // Icarus Verilog doesn't support 'automatic' keyword, declare variables at function start
            exp64 = fp64_bits[62:52];
            if (exp64 < 11'd896) begin
                // Underflow to zero
                exp32 = 8'd0;
            end else if (exp64 > 11'd1150) begin
                // Overflow to Inf
                exp32 = 8'hFF;
            end else begin
                exp32 = 8'(exp64 - 11'd896); // 1023 - 127 = 896
            end
            fp32_bits = {fp64_bits[63], exp32, fp64_bits[51:29]};
        end
        return fp32_bits;
    endfunction
    
    // gold reference calculation 
    // Note: Icarus Verilog doesn't support unpacked arrays in function ports
    // So we use a task instead or pass by reference
    task compute_expected;
        input real input0, input1, input2;
        real exp_vals[NUM_SIZE-1:0];
        real sum_exp;
        int i;
        
        sum_exp = 0.0;
        
        exp_vals[0] = $exp(input0);
        exp_vals[1] = $exp(input1);
        if (NUM_SIZE > 2) exp_vals[2] = $exp(input2);
        
        for (i = 0; i < NUM_SIZE; i++) begin
            sum_exp += exp_vals[i];
        end
        
        for (i = 0; i < NUM_SIZE; i++) begin
            expected_probs[i] = exp_vals[i] / sum_exp;
        end
    endtask
    
    // Icarus Verilog doesn't support unpacked arrays in task ports
    // So we use individual parameters instead
    task run_test(input string test_name, input real input0, input real input1, input real input2);
        real actual_vals[NUM_SIZE-1:0];
        real errors[NUM_SIZE-1:0];
        real max_error, sum_actual, sum_error;
        logic test_passed;
        real inputs[NUM_SIZE-1:0];
        
        // Copy inputs to local array
        inputs[0] = input0;
        if (NUM_SIZE > 1) inputs[1] = input1;
        if (NUM_SIZE > 2) inputs[2] = input2;
        
        test_count++;
        test_passed = 1'b1;
        
        $display("\n========================================");
        $display("Test %0d: %s", test_count, test_name);
        $display("========================================");
        
        $display("Inputs:");
        for (int i = 0; i < NUM_SIZE; i++) begin
            fp32_in[i] = real_to_fp32(inputs[i]);
            $display("  [%0d] = %f", i, inputs[i]);
        end
        
        if (NUM_SIZE == 3) begin
            compute_expected(inputs[0], inputs[1], inputs[2]);
        end else if (NUM_SIZE == 2) begin
            compute_expected(inputs[0], inputs[1], 0.0);
        end else begin
            compute_expected(inputs[0], 0.0, 0.0);
        end
        
        @(posedge clk);
        valid = 1'b1;
        @(posedge clk);
        valid = 1'b0;

        timeout = 0;
        while (!valid_out_dut && timeout < 1000) begin
            @(posedge clk);
            timeout++;
        end
        
        if (timeout >= 1000) begin
            $display("ERROR: Timeout!");
            error_count++;
            // Icarus Verilog doesn't support return in tasks, use disable instead
            disable run_test;
        end
        
        total_cycles += timeout;
        $display("Latency: %0d cycles", timeout);
        
        $display("\nResults:");
        max_error = 0.0;
        sum_actual = 0.0;
        
        for (int i = 0; i < NUM_SIZE; i++) begin
            actual_vals[i] = fp32_to_real(fp32_logits_dut[i]);
            sum_actual += actual_vals[i];
            errors[i] = (actual_vals[i] > expected_probs[i]) ? 
                        (actual_vals[i] - expected_probs[i]) : 
                        (expected_probs[i] - actual_vals[i]);
            
            if (errors[i] > max_error) max_error = errors[i];
            
            $display("  [%0d] Got: %f  Expected: %f  (error: %f)", 
                     i, actual_vals[i], expected_probs[i], errors[i]);
            
            if (errors[i] > TOLERANCE) test_passed = 1'b0;
        end
        
        // Check if probabilities sum to 1
        sum_error = (sum_actual > 1.0) ? (sum_actual - 1.0) : (1.0 - sum_actual);
        
        $display("\nSum: %f (expected 1.0, error: %f)", sum_actual, sum_error);
        $display("Max error: %f (tolerance: %f)", max_error, TOLERANCE);
        
        if (sum_error > SUM_TOLERANCE) begin
            $display("ERROR: Sum not normalized!");
            test_passed = 1'b0;
        end
        
        if (test_passed) begin
            $display("PASS");
        end else begin
            $display("FAIL");
            error_count++;
        end
        
        repeat(5) @(posedge clk);
    endtask

    initial begin
        error_count = 0;
        test_count = 0;
        total_cycles = 0;  
        
        rst_b = 1'b0;
        valid = 1'b0;
        for (int i = 0; i < NUM_SIZE; i++)
            fp32_in[i] = 32'd0;
        
        repeat(3) @(posedge clk);
        rst_b = 1'b1;
        repeat(2) @(posedge clk);
        
        $display("\n================================================");
        $display("           SOFTMAX CORE TESTBENCH               ");
        $display("================================================");
        $display("Number of Logits:  %0d", NUM_SIZE);
        $display(" Error Tolerance:   %.1f%%", TOLERANCE * 100);
        $display("================================================");
        $display("");
        
        // test case 1: positive values
        run_test("Positive", 1.0, 2.0, 3.0);
        
        // test case 2: all zeros 
        run_test("All Zeros", 0.0, 0.0, 0.0);
        
        // test case 3: small positive values
        run_test("Small Positive", 0.1, 0.2, 0.3);
        
        // test case 4: negative values
        run_test("Negative Values", -1.0, -2.0, -3.0);
        
        // test case 5: mixed positive and negative
        run_test("Mixed Values", -1.0, 0.0, 1.0);
        
        // test case 6: large positive values
        run_test("Large Positive", -10.0, 6.0, 16.0);
        run_test("Large Positive", -80.0, 6.0, 70.115);
        run_test("Large and Small", -7.0, 6.0, 7.0);
        // test case 7: large negative values
        run_test("Large Negative", -5.0, -6.0, -7.0);
        run_test("Larger Negative", -5.0, -6.0, -10.0);
        
        // test case 8: small differences
        run_test("Small Differences", 0.02, 0.04, 0.06);
        

        // ADD YOUR OWN TEST CASES HERE

        
        
        // Final summary
        $display("\n================================================");
        $display("                TEST SUMMARY                    ");
        $display("================================================");
        $display("  Total Tests:       %3d", test_count);
        $display("  Passed:            %3d", test_count - error_count);
        $display("  Failed:            %3d", error_count);
        $display("  Total Cycles:      %0d", total_cycles);
        $display("  Average Latency:   %0d cycles/test", total_cycles / test_count);
        $display("================================================\n");
        
        if (error_count == 0) begin
            $display("ALL TESTS PASSED!\n");
        end else begin
            $display("SOME TESTS FAILED\n");
        end
        
        $finish;
    end
    
    // Timeout
    initial begin
        #1000000;
        $display("\nERROR: Simulation timeout!");
        $finish;
    end

endmodule

// Stub modules for dependencies
module exp_core #(
    parameter int NUM_SIZE = 3
) (
    input  logic [31:0] fp32_in[NUM_SIZE-1:0],
    output logic [31:0] fp32_out[NUM_SIZE-1:0]
);
    // Simple stub: just pass through (for testing)
    genvar i;
    generate
        for (i = 0; i < NUM_SIZE; i++) begin
            assign fp32_out[i] = fp32_in[i]; // Placeholder
        end
    endgenerate
endmodule

module acc_core #(
    parameter int NUM_SIZE = 3
) (
    input  logic [31:0] fp32_in[NUM_SIZE-1:0],
    output logic [31:0] fp32_sum_out
);
    // Simple stub: sum all inputs
    logic [31:0] sum;
    assign sum = fp32_in[0] + fp32_in[1] + (NUM_SIZE > 2 ? fp32_in[2] : 32'd0);
    assign fp32_sum_out = sum;
endmodule

module div_core #(
    parameter int NUM_SIZE = 3
) (
    input  logic        clk,
    input  logic        rst_b,
    input  logic        valid_in,
    input  logic [31:0] numerators[NUM_SIZE-1:0],
    input  logic [31:0] denominator,
    output logic [31:0] fp32_out[NUM_SIZE-1:0],
    output logic        valid_out
);
    // Simple stub: divide numerators by denominator
    logic valid_out_reg;
    always_ff @(posedge clk or negedge rst_b) begin
        if (!rst_b) begin
            valid_out_reg <= 1'b0;
        end else begin
            valid_out_reg <= valid_in;
        end
    end
    assign valid_out = valid_out_reg;
    
    genvar i;
    generate
        for (i = 0; i < NUM_SIZE; i++) begin
            assign fp32_out[i] = (denominator != 32'd0) ? (numerators[i] / denominator) : 32'd0;
        end
    endgenerate
endmodule
