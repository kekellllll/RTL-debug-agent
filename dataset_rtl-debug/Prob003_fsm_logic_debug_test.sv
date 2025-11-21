`timescale 1 ps/1 ps
`define OK 12
`define INCORRECT 13

module stimulus_gen (
	input clk,
	output logic reset,
	output logic in,
	output reg[511:0] wavedrom_title,
	output reg wavedrom_enable	
);

	task wavedrom_start(input[511:0] title = "");
	endtask
	
	task wavedrom_stop;
		#1;
	endtask	

	initial begin
		reset <= 1'b1;
		in <= 1'b0;
		@(negedge clk) wavedrom_start("");
		@(posedge clk) reset <= 1'b0;
		
		// Test sequence: 0, 1, 1, 0, 1, 0, 1, 1, 1, 0
		@(posedge clk) in <= 1'b0;
		@(posedge clk) in <= 1'b1;
		@(posedge clk) in <= 1'b1;  // Should reach S2
		@(posedge clk) in <= 1'b0;
		@(posedge clk) in <= 1'b1;
		@(posedge clk) in <= 1'b0;
		@(posedge clk) in <= 1'b1;
		@(posedge clk) in <= 1'b1;  // Should reach S2
		@(posedge clk) in <= 1'b1;  // Stay in S2
		@(posedge clk) in <= 1'b0;
		
		repeat(20) @(posedge clk) in <= $random;
		
		wavedrom_stop();
		$finish;
	end
	
endmodule

module tb();

	typedef struct packed {
		int errors;
		int errortime;
		int errors_out;
		int errortime_out;
		int clocks;
	} stats;
	
	stats stats1;
	
	wire[511:0] wavedrom_title;
	wire wavedrom_enable;
	int wavedrom_hide_after_time;
	
	reg clk=0;
	initial forever
		#5 clk = ~clk;

	logic reset;
	logic in;
	logic out_ref;
	logic out_dut;

	initial begin 
		$dumpfile("wave.vcd");
		$dumpvars(1, stim1.clk, tb_mismatch, reset, in, out_ref, out_dut);
	end

	wire tb_match;
	wire tb_mismatch = ~tb_match;
	
	stimulus_gen stim1 (
		.clk,
		.* ,
		.reset,
		.in
	);
	
	RefModule good1 (
		.clk,
		.reset,
		.in,
		.out(out_ref)
	);
		
	TopModule top_module1 (
		.clk,
		.reset,
		.in,
		.out(out_dut)
	);

	bit strobe = 0;
	task wait_for_end_of_timestep;
		repeat(5) begin
			strobe <= !strobe;
			@(strobe);
		end
	endtask	

	final begin
		if (stats1.errors_out) $display("Hint: Output '%s' has %0d mismatches. First mismatch occurred at time %0d.", "out", stats1.errors_out, stats1.errortime_out);
		else $display("Hint: Output '%s' has no mismatches.", "out");

		$display("Hint: Total mismatched samples is %1d out of %1d samples\n", stats1.errors, stats1.clocks);
		$display("Simulation finished at %0d ps", $time);
		$display("Mismatches: %1d in %1d samples", stats1.errors, stats1.clocks);
	end
	
	assign tb_match = ( { out_ref } === ( { out_ref } ^ { out_dut } ^ { out_ref } ) );
	
	always @(posedge clk, negedge clk) begin
		stats1.clocks++;
		if (!tb_match) begin
			if (stats1.errors == 0) stats1.errortime = $time;
			stats1.errors++;
		end
		if (out_ref !== ( out_ref ^ out_dut ^ out_ref ))
		begin 
			if (stats1.errors_out == 0) stats1.errortime_out = $time;
			stats1.errors_out = stats1.errors_out+1'b1; 
		end
	end

	initial begin
		#100000
		$display("TIMEOUT");
		$finish();
	end

endmodule

