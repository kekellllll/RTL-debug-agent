#!/usr/bin/env python3
"""
AST-based DFG (Data Flow Graph) analyzer.
Uses a simple recursive-descent parser to build an AST and then generate a DFG.

This is an improved version that is more accurate than the pure regex-based approach.
"""

import re
from typing import Dict, List, Set, Tuple, Optional, Any
from enum import Enum


class NodeType(Enum):
    """AST node types."""
    MODULE = "module"
    SIGNAL_DECL = "signal_decl"
    ASSIGNMENT = "assignment"
    IF_STMT = "if_stmt"
    CASE_STMT = "case_stmt"
    ALWAYS_BLOCK = "always_block"
    EXPRESSION = "expression"
    CONDITION = "condition"


class ASTNode:
    """AST node."""
    def __init__(self, node_type: NodeType, value: str = "", children: List['ASTNode'] = None):
        self.node_type = node_type
        self.value = value
        self.children = children or []
        self.start_pos = 0
        self.end_pos = 0
    
    def __repr__(self):
        return f"ASTNode({self.node_type.value}, {self.value[:30] if self.value else ''}, {len(self.children)} children)"


class SimpleASTParser:
    """Simple SystemVerilog AST parser (recursive descent)."""
    
    def __init__(self, code: str):
        self.code = code
        self.pos = 0
        self.tokens = self._tokenize(code)
        self.token_idx = 0
    
    def _tokenize(self, code: str) -> List[Tuple[str, str]]:
        """Simple lexical analysis (tokenizer)."""
        tokens = []
        patterns = [
            (r'\bmodule\b', 'MODULE'),
            (r'\bendmodule\b', 'ENDMODULE'),
            (r'\balways_comb\b', 'ALWAYS_COMB'),
            (r'\balways_ff\b', 'ALWAYS_FF'),
            (r'\balways\b', 'ALWAYS'),
            (r'\bif\b', 'IF'),
            (r'\belse\b', 'ELSE'),
            (r'\bcase\b', 'CASE'),
            (r'\bendcase\b', 'ENDCASE'),
            (r'\bbegin\b', 'BEGIN'),
            (r'\bend\b', 'END'),
            (r'\binput\b', 'INPUT'),
            (r'\boutput\b', 'OUTPUT'),
            (r'\blogic\b', 'LOGIC'),
            (r'\breg\b', 'REG'),
            (r'\bwire\b', 'WIRE'),
            (r'\binteger\b', 'INTEGER'),
            (r'\bint\b', 'INT'),
            (r'<=', 'NONBLOCK_ASSIGN'),
            (r'=', 'ASSIGN'),
            (r'\(', 'LPAREN'),
            (r'\)', 'RPAREN'),
            (r'\[', 'LBRACKET'),
            (r'\]', 'RBRACKET'),
            (r'\{', 'LBRACE'),
            (r'\}', 'RBRACE'),
            (r';', 'SEMICOLON'),
            (r',', 'COMMA'),
            (r'==', 'EQ'),
            (r'!=', 'NE'),
            (r'[a-zA-Z_][a-zA-Z0-9_]*', 'IDENTIFIER'),
            (r'\d+\'[bdho][0-9a-fA-F_]+', 'NUMBER'),
            (r'\d+', 'NUMBER'),
            (r'\s+', 'WHITESPACE'),
            (r'//.*', 'COMMENT'),
            (r'/\*.*?\*/', 'COMMENT_MULTI'),
        ]
        
        pos = 0
        while pos < len(code):
            matched = False
            for pattern, token_type in patterns:
                match = re.match(pattern, code[pos:], re.MULTILINE)
                if match:
                    if token_type != 'WHITESPACE' and token_type != 'COMMENT' and token_type != 'COMMENT_MULTI':
                        tokens.append((token_type, match.group(0)))
                    pos += len(match.group(0))
                    matched = True
                    break
            if not matched:
                pos += 1
        
        return tokens
    
    def _peek(self) -> Optional[Tuple[str, str]]:
        """Look at the next token without consuming it."""
        if self.token_idx < len(self.tokens):
            return self.tokens[self.token_idx]
        return None
    
    def _consume(self, expected: str = None) -> Optional[Tuple[str, str]]:
        """Consume a token, optionally checking its type."""
        if self.token_idx < len(self.tokens):
            token = self.tokens[self.token_idx]
            if expected is None or token[0] == expected:
                self.token_idx += 1
                return token
            else:
                raise SyntaxError(f"Expected {expected}, got {token[0]}")
        return None
    
    def _skip_until(self, token_type: str):
        """Skip tokens until we encounter the specified type."""
        while self.token_idx < len(self.tokens):
            if self.tokens[self.token_idx][0] == token_type:
                return
            self.token_idx += 1
    
    def parse(self) -> ASTNode:
        """Parse the whole module."""
        root = ASTNode(NodeType.MODULE, "TopModule")
        
        # Skip tokens until we reach a module declaration
        while self._peek() and self._peek()[0] != 'MODULE':
            self._consume()
        
        if self._peek() and self._peek()[0] == 'MODULE':
            self._consume('MODULE')
            module_name = self._consume('IDENTIFIER')
            if module_name:
                root.value = module_name[1]
            
            # Parse the port list
            if self._peek() and self._peek()[0] == 'LPAREN':
                self._parse_port_list(root)
            
            # Parse the module contents
            while self._peek() and self._peek()[0] != 'ENDMODULE':
                node = self._parse_statement()
                if node:
                    root.children.append(node)
            
            self._consume('ENDMODULE')
        
        return root
    
    def _parse_port_list(self, parent: ASTNode):
        """Parse the port list (simplified: skip its contents)."""
        self._consume('LPAREN')
        # Simplified: skip detailed port list parsing
        depth = 1
        while depth > 0 and self._peek():
            token = self._peek()
            if token[0] == 'LPAREN':
                depth += 1
            elif token[0] == 'RPAREN':
                depth -= 1
            self._consume()
    
    def _parse_statement(self) -> Optional[ASTNode]:
        """Parse a single statement."""
        if not self._peek():
            return None
        
        token_type = self._peek()[0]
        
        if token_type == 'ALWAYS_COMB' or token_type == 'ALWAYS_FF' or token_type == 'ALWAYS':
            return self._parse_always_block()
        elif token_type == 'LOGIC' or token_type == 'REG' or token_type == 'WIRE' or token_type == 'INTEGER' or token_type == 'INT':
            return self._parse_signal_declaration()
        elif token_type == 'IF':
            return self._parse_if_statement()
        elif token_type == 'IDENTIFIER':
            # Could be an assignment
            return self._parse_assignment()
        else:
            # Skip unknown tokens
            self._consume()
            return None
    
    def _parse_always_block(self) -> ASTNode:
        """Parse an always block."""
        always_type = self._consume()[0]  # ALWAYS_COMB, ALWAYS_FF, or ALWAYS
        node = ASTNode(NodeType.ALWAYS_BLOCK, always_type)
        
        if self._peek() and self._peek()[0] == 'BEGIN':
            self._consume('BEGIN')
            
            # Parse statements inside the always block
            depth = 1
            while depth > 0 and self._peek():
                token = self._peek()
                if token[0] == 'BEGIN':
                    depth += 1
                elif token[0] == 'END':
                    depth -= 1
                    if depth == 0:
                        self._consume('END')
                        break
                
                stmt = self._parse_statement()
                if stmt:
                    node.children.append(stmt)
                else:
                    self._consume()
            
        return node
    
    def _parse_signal_declaration(self) -> ASTNode:
        """Parse a signal declaration."""
        type_token = self._consume()[1]  # logic, reg, wire, etc.
        
        # Skip bit width [N:0]
        if self._peek() and self._peek()[0] == 'LBRACKET':
            self._skip_until('RBRACKET')
            self._consume('RBRACKET')
        
        # Get the signal name
        signal_name = None
        if self._peek() and self._peek()[0] == 'IDENTIFIER':
            signal_name = self._consume('IDENTIFIER')[1]
        
        if self._peek() and self._peek()[0] == 'SEMICOLON':
            self._consume('SEMICOLON')
        
        if signal_name:
            return ASTNode(NodeType.SIGNAL_DECL, signal_name)
        return None
    
    def _parse_assignment(self) -> Optional[ASTNode]:
        """Parse an assignment statement."""
        if not self._peek() or self._peek()[0] != 'IDENTIFIER':
            return None
        
        lhs = self._consume('IDENTIFIER')[1]
        
        # Check that this is actually an assignment
        if not self._peek():
            return None
        
        assign_op = None
        if self._peek()[0] == 'ASSIGN':
            assign_op = self._consume('ASSIGN')[1]
        elif self._peek()[0] == 'NONBLOCK_ASSIGN':
            assign_op = self._consume('NONBLOCK_ASSIGN')[1]
        else:
            return None
        
        # Parse the right-hand-side expression (simplified: until semicolon)
        rhs_tokens = []
        depth = 0
        while self._peek():
            token = self._peek()
            if token[0] == 'SEMICOLON' and depth == 0:
                break
            if token[0] in ['LPAREN', 'LBRACKET', 'LBRACE']:
                depth += 1
            elif token[0] in ['RPAREN', 'RBRACKET', 'RBRACE']:
                depth -= 1
            rhs_tokens.append(self._consume()[1])
        
        if self._peek() and self._peek()[0] == 'SEMICOLON':
            self._consume('SEMICOLON')
        
        rhs_expr = ' '.join(rhs_tokens)
        return ASTNode(NodeType.ASSIGNMENT, f"{lhs} {assign_op} {rhs_expr}")
    
    def _parse_if_statement(self) -> ASTNode:
        """Parse an if statement."""
        self._consume('IF')
        node = ASTNode(NodeType.IF_STMT, "if")
        
        # Parse condition
        if self._peek() and self._peek()[0] == 'LPAREN':
            self._consume('LPAREN')
            condition_tokens = []
            depth = 1
            while depth > 0 and self._peek():
                token = self._peek()
                if token[0] == 'LPAREN':
                    depth += 1
                elif token[0] == 'RPAREN':
                    depth -= 1
                    if depth == 0:
                        break
                condition_tokens.append(self._consume()[1])
            self._consume('RPAREN')
            
            condition_expr = ' '.join(condition_tokens)
            node.children.append(ASTNode(NodeType.CONDITION, condition_expr))
        
        # Parse the 'if' block
        if self._peek() and self._peek()[0] == 'BEGIN':
            self._consume('BEGIN')
            depth = 1
            while depth > 0 and self._peek():
                token = self._peek()
                if token[0] == 'BEGIN':
                    depth += 1
                elif token[0] == 'END':
                    depth -= 1
                    if depth == 0:
                        self._consume('END')
                        break
                
                stmt = self._parse_statement()
                if stmt:
                    node.children.append(stmt)
                else:
                    self._consume()
        
        # Parse the 'else' block (if present)
        if self._peek() and self._peek()[0] == 'ELSE':
            self._consume('ELSE')
            if self._peek() and self._peek()[0] == 'BEGIN':
                self._consume('BEGIN')
                depth = 1
                while depth > 0 and self._peek():
                    token = self._peek()
                    if token[0] == 'BEGIN':
                        depth += 1
                    elif token[0] == 'END':
                        depth -= 1
                        if depth == 0:
                            self._consume('END')
                            break
                    
                    stmt = self._parse_statement()
                    if stmt:
                        node.children.append(stmt)
                    else:
                        self._consume()
            elif self._peek() and self._peek()[0] == 'IF':
                # else if
                node.children.append(self._parse_if_statement())
        
        return node


def extract_signals_from_ast(ast: ASTNode) -> Set[str]:
    """Extract signal declarations from the AST."""
    signals = set()
    
    def traverse(node: ASTNode):
        if node.node_type == NodeType.SIGNAL_DECL:
            signals.add(node.value)
        for child in node.children:
            traverse(child)
    
    traverse(ast)
    return signals


def extract_assignments_from_ast(ast: ASTNode) -> List[Tuple[str, str]]:
    """Extract assignments from the AST."""
    assignments = []
    
    def traverse(node: ASTNode):
        if node.node_type == NodeType.ASSIGNMENT:
            # 解析 "lhs = rhs" 或 "lhs <= rhs"
            parts = node.value.split(None, 2)
            if len(parts) >= 3:
                lhs = parts[0]
                rhs = parts[2]
                assignments.append((lhs, rhs))
        
        for child in node.children:
            traverse(child)
    
    traverse(ast)
    return assignments


def extract_conditions_from_ast(ast: ASTNode) -> List[str]:
    """Extract conditional expressions from the AST."""
    conditions = []
    
    def traverse(node: ASTNode):
        if node.node_type == NodeType.CONDITION:
            conditions.append(node.value)
        elif node.node_type == NodeType.IF_STMT:
            # For IF_STMT, the first child is the condition
            if node.children and node.children[0].node_type == NodeType.CONDITION:
                conditions.append(node.children[0].value)
        
        for child in node.children:
            traverse(child)
    
    traverse(ast)
    return conditions


def find_output_assignments_in_always(always_node: ASTNode, output_signals: Set[str]) -> List[str]:
    """Find assignments to output signals inside an always block."""
    output_assignments = []
    
    def traverse(node: ASTNode):
        if node.node_type == NodeType.ASSIGNMENT:
            # Check whether the assignment target is an output signal.
            # Format: "lhs = rhs" or "lhs <= rhs"
            parts = node.value.split(None, 2)
            if len(parts) >= 1:
                lhs = parts[0]
                if lhs in output_signals:
                    output_assignments.append(lhs)
        
        for child in node.children:
            traverse(child)
    
    traverse(always_node)
    return output_assignments


def build_dfg_from_ast(ast: ASTNode, signals: Set[str], code: str = "") -> Dict[str, Set[str]]:
    """Build a DFG from the AST."""
    # Extract output signals (for relating conditions and outputs)
    output_signals = set()
    output_pattern = r'output\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
    for match in re.finditer(output_pattern, code):
        output_signals.add(match.group(1))
    
    # Ensure all signals (including outputs) exist in the DFG
    all_signals = signals | output_signals
    dfg = {signal: set() for signal in all_signals}
    
    # Extract dependencies from assignment statements
    assignments = extract_assignments_from_ast(ast)
    for lhs, rhs in assignments:
        if lhs in dfg:
            for signal in signals:
                pattern = r'\b' + re.escape(signal) + r'\b'
                if re.search(pattern, rhs):
                    dfg[lhs].add(signal)
    
    # Extract dependencies from conditional expressions (key improvement).
    # Traverse the AST, locate always blocks, and associate conditions with output assignments.
    def traverse_always(node: ASTNode):
        if node.node_type == NodeType.ALWAYS_BLOCK:
            # Find output assignments in this always block
            always_outputs = find_output_assignments_in_always(node, output_signals)
            
            # Find condition expressions within this always block
            def find_conditions_in_node(n: ASTNode) -> List[str]:
                conditions = []
                if n.node_type == NodeType.CONDITION:
                    conditions.append(n.value)
                elif n.node_type == NodeType.IF_STMT:
                    if n.children and n.children[0].node_type == NodeType.CONDITION:
                        conditions.append(n.children[0].value)
                for child in n.children:
                    conditions.extend(find_conditions_in_node(child))
                return conditions
            
            conditions = find_conditions_in_node(node)
            
            # If the always block has output assignments and conditions, create dependencies
            if always_outputs and conditions:
                for condition in conditions:
                    # Normalize the condition expression (remove extra spaces and fix tokenization artifacts).
                    # Tokenization might create "sign = = 1'b1"; normalize it to "sign == 1'b1".
                    condition_clean = re.sub(r'\s+', ' ', condition).strip()
                    condition_normalized = re.sub(r'\s*=\s*=\s*', ' == ', condition_clean)
                    condition_normalized = re.sub(r'\s*!=\s*', ' != ', condition_normalized)
                    
                    for signal in signals:
                        # Use word-boundary matching
                        pattern = r'\b' + re.escape(signal) + r'\b'
                        if re.search(pattern, condition_normalized):
                            # Signals that appear in conditions influence outputs
                            for output_sig in always_outputs:
                                if output_sig in dfg:
                                    dfg[output_sig].add(signal)
        
        for child in node.children:
            traverse_always(child)
    
    traverse_always(ast)
    
    return dfg


def analyze_data_flow_ast(code: str) -> Dict[str, any]:
    """Analyze data flow using the AST-based parser."""
    try:
        parser = SimpleASTParser(code)
        ast = parser.parse()
        
        signals = extract_signals_from_ast(ast)
        assignments = extract_assignments_from_ast(ast)
        dfg = build_dfg_from_ast(ast, signals, code)
        
        # Extract input/output signals using regex (AST parser simplifies port parsing)
        output_signals = set()
        output_pattern = r'output\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
        for match in re.finditer(output_pattern, code):
            output_signals.add(match.group(1))
        
        input_signals = set()
        input_pattern = r'input\s+(?:logic|reg|wire)\s+(?:\[[^\]]+\]\s+)?(\w+)'
        for match in re.finditer(input_pattern, code):
            input_signals.add(match.group(1))
        
        # Analyze key control signals
        warnings = []
        key_signals = {'sign', 'reset', 'enable', 'valid', 'ready'}
        for key_signal in key_signals:
            if key_signal in signals:
                used_in_output = False
                for output_sig in output_signals:
                    if output_sig in dfg and key_signal in dfg[output_sig]:
                        used_in_output = True
                        break
                
                if not used_in_output:
                    warnings.append({
                        'type': 'unused_key_signal',
                        'signal': key_signal,
                        'message': f'Key signal {key_signal} exists but is not used in output computations; this may indicate a logic bug.'
                    })
        
        # Check for unused signals
        used_signals = set()
        for deps in dfg.values():
            used_signals.update(deps)
        
        unused_signals = signals - used_signals - output_signals
        if unused_signals:
            warnings.append({
                'type': 'unused_signals',
                'signals': unused_signals,
                'message': f'Unused signals: {unused_signals}'
            })
        
        return {
            'signals': signals,
            'input_signals': input_signals,
            'output_signals': output_signals,
            'dfg': dfg,
            'warnings': warnings,
            'ast': ast  # 包含 AST 用于调试
        }
    
    except Exception as e:
        # If AST parsing fails, fall back to the regex-based method
        from simple_dfg_analyzer import analyze_data_flow
        result = analyze_data_flow(code)
        result['error'] = f"AST parsing failed, using regex fallback: {str(e)}"
        return result


if __name__ == '__main__':
    # 测试
    test_code = """
module TopModule (
    input logic [31:0] fp32_in,
    output logic [7:0] integer_out,
    output logic [4:0] frac_out
);
    logic sign;
    logic [7:0] integer_raw;
    
    always_comb begin
        if (sign == 1'b1) begin
            integer_out = 127 - integer_raw - 1;
        end else begin
            integer_out = integer_raw + 127;
        end
    end
endmodule
"""
    
    result = analyze_data_flow_ast(test_code)
    print("Signals:", result['signals'])
    print("DFG:", result['dfg'])
    print("Warnings:", result['warnings'])

