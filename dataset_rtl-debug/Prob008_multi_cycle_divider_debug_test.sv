`timescale 1ns/1ps
`default_nettype none

module tb_multi_cycle_divider;

    localparam BITS_PER_STAGE = 1;
    localparam CLK_PERIOD = 10;

    // DUT signals
    logic clk;
    logic rst_b;
    logic start;
    logic [46:0] dividend;
    logic [23:0] divisor;
    logic [23:0] quotient_ref;
    logic [23:0] quotient_dut;
    logic done_ref;
    logic done_dut;

    // Reference implementation
    RefModule #(
        .BITS_PER_STAGE(BITS_PER_STAGE)
    ) ref_inst (
        .clk(clk),
        .rst_b(rst_b),
        .start(start),
        .dividend(dividend),
        .divisor(divisor),
        .quotient(quotient_ref),
        .done(done_ref)
    );

    // Device under test
    TopModule #(
        .BITS_PER_STAGE(BITS_PER_STAGE)
    ) dut_inst (
        .clk(clk),
        .rst_b(rst_b),
        .start(start),
        .dividend(dividend),
        .divisor(divisor),
        .quotient(quotient_dut),
        .done(done_dut)
    );

    // Comparison logic
    wire tb_match;
    wire tb_mismatch = ~tb_match;
    assign tb_match = (quotient_ref === quotient_dut) && (done_ref === done_dut);

    // Clock generation
    initial begin
        clk = 1'b0;
        forever #(CLK_PERIOD/2) clk = ~clk;
    end

    // Test stimulus
    initial begin
        $display("\n===============================================");
        $display("   Multi-Cycle Divider Testbench");
        $display("   BITS_PER_STAGE = %0d", BITS_PER_STAGE);
        $display("===============================================\n");

        // Initialize
        rst_b = 1'b0;
        start = 1'b0;
        dividend = 47'd0;
        divisor = 24'd0;

        // Reset release
        #(CLK_PERIOD);
        rst_b = 1'b1;
        #(CLK_PERIOD);

        // Test case 1: 100 / 10 = 10
        dividend = 47'hAF8000 << 16;
        divisor = 24'hA38000;
        $display("Test 1: %0d / %0d", dividend, divisor);
        start = 1'b1;
        #(CLK_PERIOD);
        start = 1'b0;
        wait(done_ref && done_dut);
        #(CLK_PERIOD);
        $display("  Ref Result: %0d, DUT Result: %0d (expected: %0d) %s", 
                 quotient_ref, quotient_dut, dividend/divisor,
                 (quotient_ref == quotient_dut && quotient_dut == (dividend/divisor)) ? "PASS" : "FAIL");

        // Test case 2: 255 / 15 = 17
        dividend = 47'd240;
        divisor = 24'd15;
        $display("Test 2: %0d / %0d", dividend, divisor);
        start = 1'b1;
        #(CLK_PERIOD);
        start = 1'b0;
        wait(done_ref && done_dut);
        #(CLK_PERIOD);
        $display("  Ref Result: %0d, DUT Result: %0d (expected: %0d) %s", 
                 quotient_ref, quotient_dut, dividend/divisor,
                 (quotient_ref == quotient_dut && quotient_dut == (dividend/divisor)) ? "PASS" : "FAIL");

        // Test case 3: 1000000 / 256 = 3906
        dividend = 47'd1000000;
        divisor = 24'd256;
        $display("Test 3: %0d / %0d", dividend, divisor);
        start = 1'b1;
        #(CLK_PERIOD);
        start = 1'b0;
        wait(done_ref && done_dut);
        #(CLK_PERIOD);
        $display("  Ref Result: %0d, DUT Result: %0d (expected: %0d) %s", 
                 quotient_ref, quotient_dut, dividend/divisor,
                 (quotient_ref == quotient_dut && quotient_dut == (dividend/divisor)) ? "PASS" : "FAIL");

        // Test case 4: Large numerator / Small denominator
        $display("Test 4: 140737488355328 / 1 (max dividend / 1)");
        dividend = 47'h7FFFFFFFFFFF;  // max 47-bit value
        divisor = 24'd1;
        start = 1'b1;
        #(CLK_PERIOD);
        start = 1'b0;
        wait(done_ref && done_dut);
        #(CLK_PERIOD);
        $display("  Ref Result: 0x%h, DUT Result: 0x%h %s", 
                 quotient_ref, quotient_dut,
                 (quotient_ref == quotient_dut) ? "PASS" : "FAIL");

        // Test case 5: Small numerator / Large denominator
        $display("Test 5: 100 / 1000000");
        dividend = 47'd100;
        divisor = 24'd1000000;
        start = 1'b1;
        #(CLK_PERIOD);
        start = 1'b0;
        wait(done_ref && done_dut);
        #(CLK_PERIOD);
        $display("  Ref Result: %0d, DUT Result: %0d (expected: 0) %s", 
                 quotient_ref, quotient_dut,
                 (quotient_ref == quotient_dut && quotient_dut == 0) ? "PASS" : "FAIL");

        $display("\n===============================================");
        $display("   Testbench Complete");
        $display("===============================================\n");
        $finish;
    end

    // Monitor (optional: print cycle count)
    integer cycle_count = 0;
    always @(posedge clk) begin
        if (rst_b) cycle_count = cycle_count + 1;
    end

endmodule : tb_multi_cycle_divider

