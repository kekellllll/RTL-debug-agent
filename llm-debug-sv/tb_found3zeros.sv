`default_nettype none

// Define which DUT to use via +define+BUGGY on the simulator command line
`ifdef BUGGY
  `define DUT found3zeros_buggy
`else
  `define DUT found3zeros_correct
`endif

module tb_found3zeros;
  logic clock, reset, b;
  logic found3zeros_N;

  // Instantiate DUT
  `DUT dut (
    .b(b), .clock(clock), .reset(reset), .found3zeros_N(found3zeros_N)
  );

  // Clock
  initial begin
    clock = 0;
    forever #5 clock = ~clock;
  end

  // Reset
  initial begin
    reset = 1'b1;
    b = 1'b1; // start with ones
    repeat (2) @(posedge clock);
    reset = 1'b0;
  end

  // Directed stimulus sequences to check detection and overlap handling
  task send_bit(input logic val);
    b <= val;
    @(posedge clock);
  endtask

  // Simple reference model: shift register of last 3 inputs
  logic [2:0] last3;
  always_ff @(posedge clock or posedge reset) begin
    if (reset) last3 <= 3'b111; // avoid accidental detect on reset
    else       last3 <= {last3[1:0], b};
  end
  wire golden_detect_low = (last3 == 3'b000);

  // Assertions: DUT output should be low exactly when last3 == 000
  // Allow one-cycle alignment, since output corresponds to state after sampling current b
  // Therefore compare after clocking the new bit in (as modeled above)
  property p_detect_match;
    @(posedge clock) disable iff (reset)
      (found3zeros_N === ~golden_detect_low);
  endproperty
  assert property (p_detect_match)
    else $error("Mismatch: last3=%b found3zeros_N=%b time=%0t", last3, found3zeros_N, $time);

  // Generate stimulus
  initial begin
    // Sequence with a 000 run
    send_bit(1);
    send_bit(0);
    send_bit(0);
    send_bit(0); // expect detect low
    send_bit(0); // overlapping 000 still low
    send_bit(1);

    // Randomized stress
    repeat (40) begin
      send_bit($urandom_range(0,1));
    end

    // Tail zeros
    send_bit(0);
    send_bit(0);
    send_bit(0);

    // Finish
    #20;
    $display("Test completed");
    $finish;
  end

  // Optional waveform dump
  initial begin
    $dumpfile("found3zeros.vcd");
    $dumpvars(0, tb_found3zeros);
  end
endmodule
