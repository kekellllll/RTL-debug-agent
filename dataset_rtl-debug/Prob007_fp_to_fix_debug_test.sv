`timescale 1ns/1ps
`default_nettype none

module tb_fp_to_fix;

  // --- configure this to match your RTL ---
  localparam int INT_BIAS = 127;  // Must be 127 to match the bias encoding used in the RTL (BIAS = 127)

  // DUT I/O
  logic [31:0] fp32_in;
  logic [7:0]  integer_out_ref;
  logic [7:0]  integer_out_dut;
  logic [3:0]  frac_out_ref;
  logic [3:0]  frac_out_dut;
  logic [4:0]  frac_out_ref_full;
  logic [4:0]  frac_out_dut_full;

  // Reference implementation
  RefModule ref_inst (
    .fp32_in(fp32_in),
    .integer_out(integer_out_ref),
    .frac_out(frac_out_ref_full)
  );
  assign frac_out_ref = frac_out_ref_full[3:0];

  // Device under test
  TopModule dut_inst (
    .fp32_in(fp32_in),
    .integer_out(integer_out_dut),
    .frac_out(frac_out_dut_full)
  );
  assign frac_out_dut = frac_out_dut_full[3:0];

  // Comparison logic
  wire tb_match;
  wire tb_mismatch = ~tb_match;
  assign tb_match = (integer_out_ref === integer_out_dut) && (frac_out_ref === frac_out_dut);

  // ---------- helpers ----------
  // Convert FP32 to real (Icarus Verilog doesn't support $bitstoshortreal)
  function real fp32_to_real(logic [31:0] fp32);
    logic [63:0] fp64_bits;
    // Convert 32-bit single precision to 64-bit double precision format
    if (fp32[30:23] == 8'd0) begin
      fp64_bits = {fp32[31], 63'd0};
    end else if (fp32[30:23] == 8'hFF) begin
      fp64_bits = {fp32[31], 11'h7FF, fp32[22:0], 29'd0};
    end else begin
      fp64_bits = {fp32[31], (11'(fp32[30:23]) - 8'd127 + 11'd1023), fp32[22:0], 29'd0};
    end
    return $bitstoreal(fp64_bits);
  endfunction
  
  // Convert real (64-bit double) to FP32 (32-bit single)
  // Icarus Verilog doesn't support $shortrealtobits, use manual conversion
  function automatic logic [31:0] real_to_fp32(real r);
    logic [63:0] fp64_bits;
    logic [31:0] fp32_bits;
    logic sign;
    logic [10:0] exp64;
    logic [52:0] mant64;
    logic [7:0] exp32;
    logic [22:0] mant32;
    
    fp64_bits = $realtobits(r);
    sign = fp64_bits[63];
    exp64 = fp64_bits[62:52];
    mant64 = fp64_bits[51:0];
    
    // Handle special cases
    if (exp64 == 11'h7FF) begin
      // Infinity or NaN
      exp32 = 8'hFF;
      mant32 = mant64[51:29]; // Take upper 23 bits
    end else if (exp64 == 11'd0) begin
      // Zero or subnormal
      exp32 = 8'd0;
      mant32 = mant64[51:29];
    end else begin
      // Normal number: convert from double (bias 1023) to single (bias 127)
      if (exp64 >= 11'd896 && exp64 <= 11'd1151) begin
        // Within single precision range
        exp32 = exp64[7:0] - 8'd896 + 8'd127;
        mant32 = mant64[51:29];
      end else if (exp64 < 11'd896) begin
        // Underflow to zero
        exp32 = 8'd0;
        mant32 = 23'd0;
      end else begin
        // Overflow to infinity
        exp32 = 8'hFF;
        mant32 = 23'd0;
      end
    end
    
    fp32_bits = {sign, exp32, mant32};
    return fp32_bits;
  endfunction

  // golden: compute k, idx (nearest 1/16 with carry), then **encode like your RTL**:
  //  - POS:  k_enc = k + INT_BIAS;          idx_enc = idx
  //  - NEG:  k_enc = (k + INT_BIAS) - 1;    idx_enc = (~idx + 4'd1) & 4'hF   // two's complement nibble
  //
  // Notes:
  //  * k = floor(y), f=y-k in [0,1), idx = round(f*16); if idx==16 => idx=0, k=k+1 (carry)
  //  * For negatives, RTL uses two's complement for idx, and k_enc = k_biased - 1
  // Icarus Verilog doesn't support void function with output parameters
  // Use task instead
  task automatic golden_fp_to_fix(input logic [31:0] fp32, output logic [7:0] k_enc, output logic [3:0] idx_enc);
    real y;
    int k;
    real f;
    int idx;
    logic sign;
    // Icarus Verilog doesn't support $bitstoshortreal, use helper function
    y = fp32_to_real(fp32);
    sign = fp32[31];
    if (y < 0.0) y = -y;
    k = $floor(y);
    f = y - real'(k);
    idx = $rtoi(f * 16.0 + 0.5);
    if (idx >= 16) begin
      idx = 0;
      k = k + 1;
    end
    if (sign) begin
      k_enc = 8'(INT_BIAS - k - 1);
      idx_enc = (~4'(idx) + 4'd1) & 4'hF;
    end else begin
      k_enc = 8'(k + INT_BIAS);
      idx_enc = 4'(idx);
    end
  endtask

  // ---------- test cases ----------
  // Declare variables outside initial block to avoid Icarus Verilog issues
  int errs, tests;
  initial begin
    logic [7:0] k_exp, k_got;
    logic [3:0] idx_exp, idx_got;
    errs = 0;
    tests = 0;

    $display("========================================");
    $display("  fp_to_fix Testbench");
    $display("========================================\n");

    // Test 1: Zero
    tests++;
    fp32_in = real_to_fp32(0.0);
    #10;
    golden_fp_to_fix(fp32_in, k_exp, idx_exp);
    k_got = integer_out_dut;
    idx_got = frac_out_dut;
    if (k_got != k_exp || idx_got != idx_exp) begin
      $display("FAIL Test %0d (zero): got k=%0d idx=%0d, exp k=%0d idx=%0d", tests, k_got, idx_got, k_exp, idx_exp);
      errs++;
    end else begin
      $display("PASS Test %0d (zero)", tests);
    end

    // Test 2: Small positive
    tests++;
    fp32_in = real_to_fp32(1.5);
    #10;
    golden_fp_to_fix(fp32_in, k_exp, idx_exp);
    k_got = integer_out_dut;
    idx_got = frac_out_dut;
    if (k_got != k_exp || idx_got != idx_exp) begin
      $display("FAIL Test %0d (1.5): got k=%0d idx=%0d, exp k=%0d idx=%0d", tests, k_got, idx_got, k_exp, idx_exp);
      errs++;
    end else begin
      $display("PASS Test %0d (1.5)", tests);
    end

    // Test 3: Negative
    tests++;
    fp32_in = real_to_fp32(-2.25);
    #10;
    golden_fp_to_fix(fp32_in, k_exp, idx_exp);
    k_got = integer_out_dut;
    idx_got = frac_out_dut;
    if (k_got != k_exp || idx_got != idx_exp) begin
      $display("FAIL Test %0d (-2.25): got k=%0d idx=%0d, exp k=%0d idx=%0d", tests, k_got, idx_got, k_exp, idx_exp);
      errs++;
    end else begin
      $display("PASS Test %0d (-2.25)", tests);
    end

    // Test 4: Fractional only
    tests++;
    fp32_in = real_to_fp32(0.125);
    #10;
    golden_fp_to_fix(fp32_in, k_exp, idx_exp);
    k_got = integer_out_dut;
    idx_got = frac_out_dut;
    if (k_got != k_exp || idx_got != idx_exp) begin
      $display("FAIL Test %0d (0.125): got k=%0d idx=%0d, exp k=%0d idx=%0d", tests, k_got, idx_got, k_exp, idx_exp);
      errs++;
    end else begin
      $display("PASS Test %0d (0.125)", tests);
    end

    // Test 5: Large value
    tests++;
    fp32_in = real_to_fp32(100.0);
    #10;
    golden_fp_to_fix(fp32_in, k_exp, idx_exp);
    k_got = integer_out_dut;
    idx_got = frac_out_dut;
    if (k_got != k_exp || idx_got != idx_exp) begin
      $display("FAIL Test %0d (100.0): got k=%0d idx=%0d, exp k=%0d idx=%0d", tests, k_got, idx_got, k_exp, idx_exp);
      errs++;
    end else begin
      $display("PASS Test %0d (100.0)", tests);
    end

    // Random tests
    for (int i = 0; i < 100; i++) begin
      tests++;
      fp32_in = $random;
      #10;
      golden_fp_to_fix(fp32_in, k_exp, idx_exp);
      k_got = integer_out_dut;
      idx_got = frac_out_dut;
      if (k_got != k_exp || idx_got != idx_exp) begin
        $display("FAIL Test %0d (random): got k=%0d idx=%0d, exp k=%0d idx=%0d", tests, k_got, idx_got, k_exp, idx_exp);
        errs++;
      end
    end

    $display("\n========================================");
    $display("  Summary: %0d/%0d tests passed", tests - errs, tests);
    $display("========================================");
    if (errs == 0) begin
      $display("ALL TESTS PASSED!");
    end else begin
      $display("%0d TESTS FAILED", errs);
    end
    $finish;
  end

endmodule

// Stub module for fp_split
module fp_split (
    input logic [31:0] in,
    output logic sign,
    output logic [7:0] exponent,
    output logic [22:0] mantissa
);
    assign sign = in[31];
    assign exponent = in[30:23];
    assign mantissa = in[22:0];
endmodule

